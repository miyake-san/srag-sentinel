"""Structured outputs of the two LLM steps of the report (docs/specs/03 §4)."""

from pydantic import BaseModel, ConfigDict, Field


class NewsPlan(BaseModel):
    """Search queries proposed from the aggregated metrics (never from user text)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queries: list[str] = Field(min_length=1, max_length=5)


class Claim(BaseModel):
    """One statement of the narrative with its supporting references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=400)
    metric_refs: tuple[str, ...] = ()
    article_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class Narrative(BaseModel):
    """The model-written commentary. Every number must come from the metrics (G3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(min_length=1)
    metric_commentary: tuple[Claim, ...] = Field(min_length=1)
    news_context: tuple[Claim, ...] = ()
    limitations: tuple[str, ...] = ()
