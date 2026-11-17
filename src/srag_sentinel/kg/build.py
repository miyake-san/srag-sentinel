"""``build_kg``: turn screened articles into graph nodes, edges and verified claims.

Entities are linked by dictionary (no model). Claims come from the small model through the
router; only claims that passed the validators (and the judge, when the policy asks for it) are
written. Everything else is quarantined with its reason and reported through ``on_event`` so it
reaches the audit trail.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from srag_sentinel.guardrails.news import SafeArticle
from srag_sentinel.guardrails.pii import scrub
from srag_sentinel.kg.claims import ClaimDraft, ExtractionInput
from srag_sentinel.kg.entities import link_entities
from srag_sentinel.kg.extract import extraction_prompt, extraction_task
from srag_sentinel.kg.models import (
    ArticleNode,
    ClaimNode,
    QuarantineNode,
    claim_id,
    content_sha256,
)
from srag_sentinel.kg.store import KgStore
from srag_sentinel.llm.router.cascade import CallBudget, JudgeInfo, Router, TaskOutcome

EventCallback = Callable[[str, Mapping[str, Any]], None]
UNJUDGED_CONFIDENCE = 0.8
CONCURRENCY = 3
MAX_REASON = 200


@dataclass(frozen=True)
class BuildResult:
    """What one build wrote."""

    articles: int
    claims: int
    quarantined: int


def _confidence(trust: float, judge: JudgeInfo | None) -> float:
    """Source trust scaled by the judge score (or a fixed prior when no judge ran)."""
    quality = judge.score / 5 if judge is not None else UNJUDGED_CONFIDENCE
    return round(trust * quality, 3)


def _node(item: SafeArticle, run_id: str, now: datetime, ttl_days: int) -> ArticleNode:
    article = item.article
    found = link_entities(f"{article.title}. {article.snippet}")
    return ArticleNode(
        id=article.id,
        title=article.title,
        snippet=article.snippet,
        url=article.url,
        domain=article.domain,
        trust=item.trust,
        published_at=article.published_at,
        sha256=content_sha256(article.title, article.snippet),
        run_id=run_id,
        retrieved_at=now,
        expires_at=now + timedelta(days=ttl_days),
        ufs=found.ufs,
        pathogens=found.pathogens,
    )


def _claim_node(  # noqa: PLR0913 - provenance needs these independent pieces
    draft: ClaimDraft,
    *,
    article: ArticleNode,
    outcome: TaskOutcome[Any],
    prompt_ref: str,
    now: datetime,
    ttl_days: int,
) -> ClaimNode:
    judge = (
        {
            "rubric": outcome.judge.rubric,
            "score": outcome.judge.score,
            "passed": outcome.judge.passed,
        }
        if outcome.judge
        else None
    )
    return ClaimNode(
        id=claim_id(article.id, draft),
        article_id=article.id,
        type=draft.type,
        direction=draft.direction,
        text=scrub(draft.text).text,
        evidence_span=draft.evidence_span,
        uf_codes=draft.uf_codes,
        pathogen_ids=draft.pathogen_ids,
        confidence=_confidence(article.trust, outcome.judge),
        produced_by=f"{outcome.tier}/{outcome.model}/{prompt_ref}",
        judge=judge,
        run_id=article.run_id,
        created_at=now,
        expires_at=now + timedelta(days=ttl_days),
    )


async def build_kg(  # noqa: PLR0913 - dependency injection of the collaborators
    articles: Sequence[SafeArticle],
    *,
    run_id: str,
    router: Router,
    store: KgStore,
    budget: CallBudget | None = None,
    on_event: EventCallback | None = None,
    ttl_days: int = 30,
    now: datetime | None = None,
) -> BuildResult:
    """Write ``articles`` and their verified claims; propagate :class:`KgUnavailableError`."""
    emit = on_event or (lambda kind, details: None)
    moment = now or datetime.now(UTC)
    task = extraction_task()
    prompt_ref = extraction_prompt().ref
    gate = asyncio.Semaphore(CONCURRENCY)

    async def process(item: SafeArticle) -> tuple[int, int]:
        node = _node(item, run_id, moment, ttl_days)
        await store.write_article(node)
        emit(
            "kg_write",
            {"kind": "article", "id": node.id, "entities": len(node.ufs) + len(node.pathogens)},
        )
        async with gate:
            outcome = await router.run(
                task,
                ExtractionInput(article_id=node.id, title=node.title, snippet=node.snippet),
                budget=budget,
            )
        if not outcome.accepted or outcome.output is None:
            reason = "; ".join(outcome.feedback)[:MAX_REASON] or "extraction not accepted"
            await store.quarantine(
                QuarantineNode(
                    kind="claims",
                    reason=reason,
                    article_id=node.id,
                    run_id=run_id,
                    produced_by=f"router/{prompt_ref}",
                    created_at=moment,
                )
            )
            emit(
                "kg_quarantine",
                {"kind": "claims", "article_id": node.id, "attempts": outcome.attempts},
            )
            return 1, 0
        for draft in outcome.output.claims:
            claim = _claim_node(
                draft,
                article=node,
                outcome=outcome,
                prompt_ref=prompt_ref,
                now=moment,
                ttl_days=ttl_days,
            )
            await store.write_claim(claim)
            emit(
                "kg_write",
                {"kind": "claim", "id": claim.id, "type": claim.type, "tier": outcome.tier or ""},
            )
        return 0, len(outcome.output.claims)

    results = await asyncio.gather(*(process(item) for item in articles))
    return BuildResult(
        articles=len(articles),
        claims=sum(claims for _, claims in results),
        quarantined=sum(rejected for rejected, _ in results),
    )
