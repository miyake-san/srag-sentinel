"""The report content assembled by the graph (rendering to HTML/JSON/PDF comes in T12-T13)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from srag_sentinel.agent.schemas import Narrative
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.domain.series import SeriesPayload


class ArticleRef(BaseModel):
    """A source shown in the report (title and link only; no article body)."""

    model_config = ConfigDict(frozen=True)

    ref: str
    title: str
    source: str
    domain: str
    url: str
    published_at: datetime | None = None
    provider: str


class ReportDraft(BaseModel):
    """Everything the renderers need. ``narrative`` is ``None`` for a degraded report."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    generated_at: datetime
    status: Literal["ok", "degraded"]
    degradations: tuple[str, ...]
    metrics: MetricsPayload
    series: SeriesPayload
    narrative: Narrative | None
    articles: tuple[ArticleRef, ...]
    models: dict[str, str]
    prompts: tuple[str, ...]
