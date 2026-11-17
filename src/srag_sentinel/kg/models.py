"""Graph node models written by the build step. Every generated node carries its provenance."""

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.kg.claims import ClaimDraft, ClaimType, Direction, article_text


class ArticleNode(BaseModel):
    """A screened (G2) article. Only title and a short snippet are stored, never the full text."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    snippet: str
    url: str
    domain: str
    trust: float = Field(ge=0, le=1)
    published_at: datetime | None
    sha256: str
    run_id: str
    retrieved_at: datetime
    expires_at: datetime
    ufs: tuple[str, ...] = ()
    pathogens: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """Indexed text (title and snippet)."""
        return article_text(self.title, self.snippet)


class ClaimNode(BaseModel):
    """An accepted claim with who produced it and who judged it."""

    model_config = ConfigDict(frozen=True)

    id: str
    article_id: str
    type: ClaimType
    direction: Direction
    text: str
    evidence_span: str
    uf_codes: tuple[str, ...]
    pathogen_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    produced_by: str
    judge: dict[str, Any] | None
    run_id: str
    created_at: datetime
    expires_at: datetime


class SummaryNode(BaseModel):
    """A verified regional summary; ``evidence_ids`` are the claim record ids it rests on."""

    model_config = ConfigDict(frozen=True)

    region: str
    text: str
    evidence_ids: tuple[str, ...]
    produced_by: str
    judge: dict[str, Any] | None
    run_id: str
    created_at: datetime
    valid_until: datetime


class SnapshotNode(BaseModel):
    """The metrics computed by code for one scope at one report (never extracted by a model)."""

    model_config = ConfigDict(frozen=True)

    id: str
    scope: str
    as_of: str
    window_days: int
    metrics: dict[str, Any]
    run_id: str
    created_at: datetime


class ReportNode(BaseModel):
    """A generated report and the evidence it actually cited."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    generated_at: datetime
    status: str
    snapshot_id: str
    cited: tuple[str, ...] = ()  # record ids such as ``claim:ab12`` / ``article:cd34``


class QuarantineNode(BaseModel):
    """Something that failed validation or judging: kept for audit, never part of the graph."""

    model_config = ConfigDict(frozen=True)

    kind: str
    reason: str
    article_id: str
    run_id: str
    produced_by: str
    created_at: datetime


def content_sha256(title: str, snippet: str) -> str:
    """Hash of the stored text, to detect an article whose content changed."""
    return hashlib.sha256(article_text(title, snippet).encode("utf-8")).hexdigest()


def claim_id(article_id: str, draft: ClaimDraft) -> str:
    """Stable id so rebuilding the same claim is an upsert, not a duplicate."""
    span = " ".join(draft.evidence_span.split())
    key = "|".join(
        [article_id, draft.type, draft.direction, span, *draft.uf_codes, "/", *draft.pathogen_ids]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
