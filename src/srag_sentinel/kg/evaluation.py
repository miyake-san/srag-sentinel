"""Metrics for the labelled corpus: entity and claim F1, retrieval recall (docs/specs/07 §7)."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from srag_sentinel.kg.claims import ClaimDraft


@dataclass(frozen=True)
class Score:
    """Precision, recall and F1 over sets of hashable items."""

    precision: float
    recall: float
    f1: float


def score(expected: Collection[object], predicted: Collection[object]) -> Score:
    """F1 between two collections (both empty counts as a perfect match)."""
    expected_set, predicted_set = set(expected), set(predicted)
    if not expected_set and not predicted_set:
        return Score(1.0, 1.0, 1.0)
    hits = len(expected_set & predicted_set)
    precision = hits / len(predicted_set) if predicted_set else 0.0
    recall = hits / len(expected_set) if expected_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    return Score(precision, recall, f1)


def entity_keys(article_id: str, ufs: Iterable[str], pathogens: Iterable[str]) -> set[object]:
    """One item per (article, kind, id) so entities are scored across the whole corpus."""
    return {(article_id, "uf", uf) for uf in ufs} | {
        (article_id, "pathogen", pathogen) for pathogen in pathogens
    }


def claim_key(
    article_id: str,
    claim_type: str,
    direction: str,
    ufs: Iterable[str],
    pathogens: Iterable[str],
) -> object:
    """Identity of a claim for scoring: its type, direction and entities (the text may vary)."""
    return (article_id, claim_type, direction, tuple(sorted(ufs)), tuple(sorted(pathogens)))


def draft_key(article_id: str, claim: ClaimDraft) -> object:
    """:func:`claim_key` for an extracted draft."""
    return claim_key(article_id, claim.type, claim.direction, claim.uf_codes, claim.pathogen_ids)


def recall_at_k(relevant: Collection[str], ranked: Iterable[str], k: int) -> float:
    """Share of ``relevant`` ids found among the first ``k`` ranked ids."""
    if not relevant:
        return 1.0
    top = list(ranked)[:k]
    return len(set(relevant) & set(top)) / len(set(relevant))
