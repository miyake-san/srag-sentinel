"""Claim drafts: what the small model may extract from a headline (closed enums, bounded size)."""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

ClaimType = Literal[
    "alert_level",
    "case_trend",
    "death_trend",
    "hospital_pressure",
    "vaccination",
    "outbreak",
    "public_health_measure",
    "other",
]
Direction = Literal["up", "down", "stable", "unknown"]
CLAIM_TYPES: tuple[str, ...] = get_args(ClaimType)
DIRECTIONS: tuple[str, ...] = get_args(Direction)
MAX_CLAIMS_PER_ARTICLE = 3


class ClaimDraft(BaseModel):
    """One statement made by an article, tied to a literal span of its text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ClaimType
    text: str = Field(min_length=1, max_length=300, description="short paraphrase in Portuguese")
    evidence_span: str = Field(min_length=1, max_length=300, description="copied verbatim")
    uf_codes: tuple[str, ...] = Field(default=(), max_length=5)
    pathogen_ids: tuple[str, ...] = Field(default=(), max_length=5)
    direction: Direction


class ClaimDraftList(BaseModel):
    """Structured output of the ``kg.extract_claims`` task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: tuple[ClaimDraft, ...] = Field(default=(), max_length=8)


class ExtractionInput(BaseModel):
    """What the extraction task sees: one already-screened article (G2), nothing else."""

    model_config = ConfigDict(frozen=True)

    article_id: str
    title: str
    snippet: str

    @property
    def text(self) -> str:
        """The text claims must quote from, and the text the index searches."""
        return article_text(self.title, self.snippet)


def article_text(title: str, snippet: str) -> str:
    """Title and snippet joined the way the graph stores and indexes them."""
    return f"{title}. {snippet}" if snippet else title
