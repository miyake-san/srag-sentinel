"""Graph state: typed, serialisable data only (no clients or secrets)."""

import operator
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.agent.schemas import Narrative
from srag_sentinel.agent.tools.metrics import ScopeArgs
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.domain.series import SeriesPayload
from srag_sentinel.guardrails.news import SafeArticle
from srag_sentinel.reporting.bundle import ReportBundle

NEWS_UNAVAILABLE = "NEWS_UNAVAILABLE"
PLAN_FALLBACK = "PLAN_FALLBACK"
NARRATIVE_REJECTED = "NARRATIVE_REJECTED"
MAX_SYNTHESIS_ATTEMPTS = 2


class ReportState(BaseModel):
    """State passed between nodes. Each node returns only the fields it changes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    raw_request: dict[str, Any] = Field(default_factory=dict)
    request: ScopeArgs | None = None
    rejected: bool = False
    metrics: MetricsPayload | None = None
    series: SeriesPayload | None = None
    queries: list[str] = Field(default_factory=list)
    articles: list[SafeArticle] = Field(default_factory=list)
    narrative: Narrative | None = None
    feedback: list[str] = Field(default_factory=list)
    synthesis_attempts: int = 0
    verified: bool = False
    degradations: Annotated[list[str], operator.add] = Field(default_factory=list)
    report: ReportDraft | None = None
    bundle: ReportBundle | None = None
