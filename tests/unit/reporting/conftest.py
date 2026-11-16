from datetime import UTC, date, datetime, timedelta

import pytest

from srag_sentinel.agent.report import ArticleRef, ReportDraft
from srag_sentinel.agent.schemas import Claim, Narrative
from srag_sentinel.domain.models import MetricResult, MetricsPayload
from srag_sentinel.domain.series import SeriesPayload, daily_series, monthly_series
from srag_sentinel.domain.windows import window_pair

AS_OF = date(2026, 11, 12)
HOSTILE_TITLE = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def make_metrics() -> MetricsPayload:
    previous, current = window_pair(AS_OF, 30)
    metrics = (
        MetricResult(
            metric_id="M1",
            label="Taxa de aumento de casos",
            value=-0.088,
            numerator=9120,
            denominator=10000,
            window_start=current.start,
            window_end=current.end,
            is_proxy=False,
        ),
        MetricResult(
            metric_id="M3",
            label="Taxa de ocupação de UTI",
            value=0.312,
            numerator=312,
            denominator=1000,
            window_start=current.start,
            window_end=current.end,
            is_proxy=True,
            completeness=0.536,
            caveats=("Só registros hospitalizados com UTI preenchida.",),
        ),
    )
    return MetricsPayload(
        scope="BR",
        as_of=AS_OF,
        window_days=30,
        current_window=current,
        previous_window=previous,
        cases_current=9120,
        cases_previous=10000,
        metrics=metrics,
        data_maturity=("Dias recentes ainda em digitação.",),
    )


def make_series() -> SeriesPayload:
    cases = {AS_OF - timedelta(days=offset): 300 + offset for offset in range(400)}
    return SeriesPayload(
        scope="BR",
        as_of=AS_OF,
        daily=daily_series(cases, as_of=AS_OF),
        monthly=monthly_series(cases, as_of=AS_OF),
    )


def make_draft(
    *,
    narrative: Narrative | None = None,
    articles: tuple[ArticleRef, ...] = (),
    degradations: tuple[str, ...] = (),
) -> ReportDraft:
    return ReportDraft(
        run_id="run-123",
        generated_at=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
        status="degraded" if degradations or narrative is None else "ok",
        degradations=degradations,
        metrics=make_metrics(),
        series=make_series(),
        narrative=narrative,
        articles=articles,
        models={"report.synthesize": "claude-sonnet-5-5"},
        prompts=("plan_news@1", "synthesize@1"),
    )


def make_article(
    title: str = "Casos de SRAG caem", url: str = "https://example.gov.br/a"
) -> ArticleRef:
    return ArticleRef(
        ref="A1",
        title=title,
        source="Agência Exemplo",
        domain="example.gov.br",
        url=url,
        published_at=datetime(2026, 11, 10, tzinfo=UTC),
        provider="google_news_rss",
    )


def make_narrative(summary: str = "Os casos recuaram no período.") -> Narrative:
    return Narrative(
        summary=summary,
        metric_commentary=(Claim(text="Queda dos casos na janela.", metric_refs=("M1",)),),
        news_context=(Claim(text="Imprensa registra queda.", article_refs=("A1",)),),
        limitations=("Dados sujeitos a revisão.",),
    )


@pytest.fixture
def draft() -> ReportDraft:
    return make_draft(narrative=make_narrative(), articles=(make_article(),))
