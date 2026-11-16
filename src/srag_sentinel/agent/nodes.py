"""Graph nodes. Each returns only the state fields it changes and is audited by ``_audited``."""

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from srag_sentinel.agent.deps import AgentDeps
from srag_sentinel.agent.report import ArticleRef, ReportDraft
from srag_sentinel.agent.schemas import Narrative, NewsPlan
from srag_sentinel.agent.state import (
    MAX_SYNTHESIS_ATTEMPTS,
    NARRATIVE_REJECTED,
    NEWS_UNAVAILABLE,
    PLAN_FALLBACK,
    ReportState,
)
from srag_sentinel.agent.tools.metrics import get_srag_metrics, get_srag_series
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.guardrails.grounding import verify_narrative
from srag_sentinel.guardrails.input import check_request
from srag_sentinel.guardrails.news import (
    SafeArticle,
    filter_articles,
    load_policy,
    references,
    wrap_untrusted,
)
from srag_sentinel.llm.prompts import Prompt, load_prompt
from srag_sentinel.llm.router.cascade import TaskSpec
from srag_sentinel.news.models import Article, NewsQuery

Update = dict[str, Any]
Node = Callable[[ReportState], Awaitable[Update]]

PLAN_TASK = "news.plan_queries"
SYNTHESIS_TASK = "report.synthesize"
DEFAULT_QUERIES = (
    "síndrome respiratória aguda grave",
    "influenza gripe casos hospitalizações",
    "covid-19 casos internações",
)
NEWS_LOOKBACK_DAYS = 14
NEWS_MAX_RESULTS = 10


def _pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "n/d"
    text = f"{value * 100:+.1f}" if signed else f"{value * 100:.1f}"
    return text.replace(".", ",") + "%"


def metrics_block(payload: MetricsPayload) -> str:
    """Render the metrics for the prompt: the only place the model may take numbers from."""
    lines = [
        f"escopo={payload.scope} as_of={payload.as_of.isoformat()} "
        f"janela={payload.window_days} dias "
        f"casos_atual={payload.cases_current} casos_anterior={payload.cases_previous}"
    ]
    for metric in payload.metrics:
        value = _pct(metric.value, signed=metric.metric_id == "M1")
        proxy = "sim" if metric.is_proxy else "nao"
        lines.append(
            f"{metric.metric_id} | {metric.label} | valor={value} "
            f"| numerador={metric.numerator} | denominador={metric.denominator} "
            f"| proxy={proxy} | completude={_pct(metric.completeness)}"
        )
    lines.extend(f"NOTA: {note}" for note in payload.data_maturity)
    return "\n".join(lines)


def _plan_user(payload: MetricsPayload, feedback: Sequence[str]) -> str:
    trend = "estável"
    growth = payload.metrics[0].value
    if growth is not None and growth > 0.01:  # noqa: PLR2004
        trend = "em alta"
    elif growth is not None and growth < -0.01:  # noqa: PLR2004
        trend = "em queda"
    base = f"Escopo: {payload.scope}. Tendência de casos: {trend}."
    return base + ("\nCorrija: " + "; ".join(feedback) if feedback else "")


def _synthesis_user(payload: dict[str, Any], feedback: Sequence[str]) -> str:
    parts = [
        "METRICAS:\n" + metrics_block(payload["metrics"]),
        "NOTICIAS:\n" + (payload["news"] or "(nenhuma notícia relevante)"),
    ]
    corrections = [*payload.get("feedback", []), *feedback]
    if corrections:
        parts.append("CORRECOES (o texto anterior foi reprovado):\n" + "\n".join(corrections))
    return "\n\n".join(parts)


def default_queries(scope: str) -> list[str]:
    """Template queries used when the planning task fails (deterministic fallback)."""
    queries = list(DEFAULT_QUERIES)
    if scope != "BR":
        queries.insert(0, f"{scope} síndrome respiratória aguda grave")
    return queries[:3]


def build_nodes(deps: AgentDeps) -> dict[str, Node]:
    """Create every node bound to ``deps``."""
    plan_prompt = load_prompt("plan_news")
    synthesis_prompt = load_prompt("synthesize")
    ctx = _Context(deps, plan_prompt, synthesis_prompt)
    steps: dict[str, Node] = {
        "validate_request": ctx.validate_request,
        "fetch_metrics": ctx.fetch_metrics,
        "plan_news": ctx.plan_news,
        "collect_news": ctx.collect_news,
        "synthesize": ctx.synthesize,
        "verify_narrative": ctx.verify_narrative,
        "render_report": ctx.render_report,
        "finalize": ctx.finalize,
    }
    return {name: _audited(deps, name, step) for name, step in steps.items()}


def _audited(deps: AgentDeps, name: str, step: Node) -> Node:
    async def run(state: ReportState) -> Update:
        started = time.monotonic()
        try:
            update = await step(state)
        except Exception:
            deps.recorder.record(
                actor="agent", node=name, event="decision", details={"status": "error"}
            )
            await deps.recorder.flush()
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)
        deps.recorder.record(
            actor="agent", node=name, event="decision", details={"status": "ok", "ms": elapsed_ms}
        )
        await deps.recorder.flush()
        return update

    return run


class _Context:
    """Node implementations sharing the injected dependencies."""

    def __init__(self, deps: AgentDeps, plan_prompt: Prompt, synthesis_prompt: Prompt) -> None:
        self.deps = deps
        self.plan_prompt = plan_prompt
        self.synthesis_prompt = synthesis_prompt

    async def validate_request(self, state: ReportState) -> Update:
        latest = await self.deps.reader.latest_day()
        check = check_request(state.raw_request, latest_day=latest)
        self.deps.recorder.record_verdicts(check.verdicts)
        if check.blocked:
            return {"rejected": True}
        return {"request": check.request}

    async def fetch_metrics(self, state: ReportState) -> Update:
        request = state.request
        assert request is not None  # noqa: S101 - set by validate_request
        metrics = await get_srag_metrics(self.deps.reader, request)
        series = await get_srag_series(self.deps.reader, request)
        self.deps.recorder.record(
            actor="tool",
            node="get_srag_metrics",
            event="tool_call",
            inputs=request.model_dump(mode="json"),
            outputs=metrics.model_dump(mode="json"),
        )
        self.deps.recorder.record(
            actor="tool",
            node="get_srag_series",
            event="tool_call",
            inputs=request.model_dump(mode="json"),
            outputs=series.model_dump(mode="json"),
        )
        return {"metrics": metrics, "series": series}

    async def plan_news(self, state: ReportState) -> Update:
        metrics = state.metrics
        assert metrics is not None  # noqa: S101
        task = TaskSpec(
            task_id=PLAN_TASK,
            output_schema=NewsPlan,
            system_prompt=self.plan_prompt.text,
            build_user=_plan_user,
        )
        self.deps.recorder.record(
            actor="agent",
            node="plan_news",
            event="llm_call",
            details={"prompt": self.plan_prompt.ref, "sha256": self.plan_prompt.sha256[:16]},
        )
        outcome = await self.deps.router.run(task, metrics, budget=self.deps.budget.model_calls)
        if outcome.accepted and outcome.output is not None:
            return {"queries": list(outcome.output.queries)}
        return {"queries": default_queries(metrics.scope), "degradations": [PLAN_FALLBACK]}

    async def collect_news(self, state: ReportState) -> Update:
        budget = self.deps.budget
        found: list[Article] = []
        failures: list[str] = []
        for text in state.queries:
            try:
                query = NewsQuery(
                    text=text, lookback_days=NEWS_LOOKBACK_DAYS, max_results=NEWS_MAX_RESULTS
                )
            except ValidationError:
                continue
            if not budget.try_news_query():
                break
            result = await self.deps.news.collect(query)
            found.extend(result.articles)
            failures.extend(result.failures)

        update: Update = {}
        if failures:
            self.deps.recorder.record(
                actor="tool",
                node="search_news",
                event="degradation",
                details={"providers_failed": len(failures)},
            )
        if not found and failures:
            update["degradations"] = [NEWS_UNAVAILABLE]
        filtered = filter_articles(
            found, policy=self.deps.news_policy or load_policy(), now=self.deps.clock()
        )
        self.deps.recorder.record_verdicts(filtered.verdicts)
        update["articles"] = budget.cap_articles(filtered.accepted)
        self.deps.recorder.record_verdicts(budget.verdicts)
        budget.verdicts.clear()
        return update

    async def synthesize(self, state: ReportState) -> Update:
        metrics = state.metrics
        assert metrics is not None  # noqa: S101
        attempts = state.synthesis_attempts + 1
        if self.deps.budget.deadline_exceeded():
            self.deps.recorder.record_verdicts(self.deps.budget.verdicts)
            return {
                "narrative": None,
                "synthesis_attempts": MAX_SYNTHESIS_ATTEMPTS,
                "degradations": [NARRATIVE_REJECTED],
            }
        payload = {
            "metrics": metrics,
            "news": wrap_untrusted(state.articles),
            "feedback": list(state.feedback),
        }
        task = TaskSpec(
            task_id=SYNTHESIS_TASK,
            output_schema=Narrative,
            system_prompt=self.synthesis_prompt.text,
            build_user=_synthesis_user,
        )
        self.deps.recorder.record(
            actor="agent",
            node="synthesize",
            event="llm_call",
            details={
                "prompt": self.synthesis_prompt.ref,
                "sha256": self.synthesis_prompt.sha256[:16],
                "attempt": attempts,
            },
        )
        outcome = await self.deps.router.run(task, payload, budget=self.deps.budget.model_calls)
        if outcome.accepted:
            return {"narrative": outcome.output, "synthesis_attempts": attempts}
        return {
            "narrative": None,
            "synthesis_attempts": MAX_SYNTHESIS_ATTEMPTS,
            "degradations": [NARRATIVE_REJECTED],
        }

    async def verify_narrative(self, state: ReportState) -> Update:
        narrative, metrics = state.narrative, state.metrics
        if narrative is None or metrics is None:
            return {"verified": False}
        texts = {
            item.ref: f"{item.article.title} {item.article.snippet}" for item in state.articles
        }
        result = verify_narrative(narrative, metrics, article_texts=texts)
        self.deps.recorder.record_verdicts(result.verdicts)
        if result.ok:
            return {"verified": True, "feedback": []}
        if state.synthesis_attempts >= MAX_SYNTHESIS_ATTEMPTS:
            return {"verified": False, "narrative": None, "degradations": [NARRATIVE_REJECTED]}
        return {"verified": False, "feedback": list(result.feedback())}

    async def render_report(self, state: ReportState) -> Update:
        metrics, series = state.metrics, state.series
        assert metrics is not None and series is not None  # noqa: S101
        narrative = state.narrative if state.verified else None
        shown = references(state.articles)
        draft = ReportDraft(
            run_id=state.run_id,
            generated_at=self.deps.clock(),
            status="ok" if not state.degradations and narrative is not None else "degraded",
            degradations=tuple(dict.fromkeys(state.degradations)),
            metrics=metrics,
            series=series,
            narrative=narrative,
            articles=tuple(_article_ref(ref, article) for ref, article in shown.items()),
            models=dict(self.deps.models),
            prompts=(self.plan_prompt.ref, self.synthesis_prompt.ref),
        )
        return {"report": draft}

    async def finalize(self, state: ReportState) -> Update:
        status = (
            "rejected" if state.rejected else (state.report.status if state.report else "failed")
        )
        self.deps.recorder.record(
            actor="system",
            node="finalize",
            event="run_end",
            outputs=state.report.model_dump(mode="json") if state.report else None,
            details={"status": status, "degradations": ",".join(dict.fromkeys(state.degradations))},
        )
        return {}


def _article_ref(ref: str, article: Article) -> ArticleRef:
    return ArticleRef(
        ref=ref,
        title=article.title,
        source=article.source,
        domain=article.domain,
        url=article.url,
        published_at=article.published_at,
        provider=article.provider,
    )


def used_articles(state: ReportState) -> Mapping[str, SafeArticle]:
    """Accepted articles by reference (helper for renderers and tests)."""
    return {item.ref: item for item in state.articles}
