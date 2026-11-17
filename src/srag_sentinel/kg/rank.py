"""Ranking and cut-off: relevance x confidence x source trust x recency x graph proximity."""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

RECENCY_HALF_LIFE_DAYS = 14.0
RECENCY_FLOOR = 0.2
DISTANT_HOPS = 3  # about other UFs only: reached by text, not by the graph around the scope
PROXIMITY = {0: 1.0, 1: 0.7, 2: 0.5, DISTANT_HOPS: 0.3}
TEXT_ONLY_PROXIMITY = 0.6
EXPANSION_RELEVANCE = 0.3


@dataclass(frozen=True)
class Candidate:
    """A retrieved node before scoring."""

    kind: str
    record_id: str
    text: str
    graph_path: str
    article_id: str | None
    confidence: float
    trust: float
    created_at: datetime | None
    relevance: float
    hops: int | None
    produced_by: str
    judge: dict[str, object] | None
    source_domain: str | None
    run_id: str | None
    url: str | None
    published_at: datetime | None


def recency(moment: datetime | None, now: datetime) -> float:
    """Exponential decay with a floor; unknown dates get the floor."""
    if moment is None:
        return RECENCY_FLOOR
    age_days = max((now - moment).total_seconds() / 86400, 0.0)
    return max(RECENCY_FLOOR, math.pow(0.5, age_days / RECENCY_HALF_LIFE_DAYS))


def normalise_relevance(scores: Sequence[float]) -> list[float]:
    """Scale BM25 scores to ``[0, 1]`` by the best one (all zero stays zero)."""
    top = max(scores, default=0.0)
    return [score / top if top > 0 else 0.0 for score in scores]


def score_candidate(candidate: Candidate, now: datetime) -> float:
    """Combine the signals; every factor is in ``[0, 1]`` so the product is too."""
    relevance = candidate.relevance if candidate.relevance > 0 else EXPANSION_RELEVANCE
    proximity = (
        TEXT_ONLY_PROXIMITY if candidate.hops is None else PROXIMITY.get(candidate.hops, 0.4)
    )
    moment = candidate.published_at or candidate.created_at
    return relevance * candidate.confidence * candidate.trust * recency(moment, now) * proximity


def select_top(
    candidates: Iterable[Candidate], now: datetime, k: int
) -> list[tuple[Candidate, float]]:
    """Score, keep the best item per article (a claim beats its own article) and cut at ``k``."""
    pool = list(candidates)
    article_relevance = {c.article_id: c.relevance for c in pool if c.kind == "article"}
    with_claims = {c.article_id for c in pool if c.kind == "claim" and c.article_id is not None}
    # A claim is the more specific, provenance-carrying evidence: it replaces its own article
    # and inherits the article's text relevance (the paraphrase may not repeat the query terms).
    pool = [
        replace(c, relevance=max(c.relevance, article_relevance.get(c.article_id, 0.0)))
        if c.kind == "claim"
        else c
        for c in pool
        if not (c.kind == "article" and c.article_id in with_claims)
    ]
    scored = sorted(
        ((candidate, score_candidate(candidate, now)) for candidate in pool),
        key=lambda pair: (-pair[1], pair[0].record_id),
    )
    chosen: list[tuple[Candidate, float]] = []
    seen_records: set[str] = set()
    seen_articles: set[str] = set()
    for candidate, value in scored:
        if candidate.record_id in seen_records:
            continue
        if candidate.article_id is not None and candidate.article_id in seen_articles:
            continue
        seen_records.add(candidate.record_id)
        if candidate.article_id is not None:
            seen_articles.add(candidate.article_id)
        chosen.append((candidate, value))
        if len(chosen) == k:
            break
    return chosen
