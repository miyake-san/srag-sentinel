"""Dependencies injected into the graph (ports, never concrete adapters)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from srag_sentinel.agent.report import ReportDraft
from srag_sentinel.data.ports import CountersReader
from srag_sentinel.governance.recorder import AuditRecorder
from srag_sentinel.guardrails.budget import RunBudget
from srag_sentinel.guardrails.news import NewsPolicy
from srag_sentinel.kg.evidence import EvidencePack
from srag_sentinel.kg.retrieve import Question
from srag_sentinel.kg.store import KgStore
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.news.models import NewsQuery, NewsResult
from srag_sentinel.observability.telemetry import Telemetry
from srag_sentinel.reporting.bundle import ReportBundle


class NewsCollector(Protocol):
    """Collects news and reports which providers failed (the chained provider)."""

    async def collect(self, query: NewsQuery) -> NewsResult:
        """Return merged articles and provider failures."""
        ...


class KgRetriever(Protocol):
    """Read side of the knowledge graph (GraphRAG retrieval)."""

    async def retrieve(
        self,
        *,
        scope: str,
        questions: Sequence[Question],
        top_k: int,
        max_hops: int,
        now: datetime,
    ) -> EvidencePack:
        """Return ranked evidence for the scope."""
        ...


@dataclass(frozen=True)
class KgConfig:
    """Knowledge-graph collaborators and limits (no config in the deps disables GraphRAG)."""

    store: KgStore
    retriever: KgRetriever
    top_k: int = 12
    max_hops: int = 2
    ttl_days: int = 30


@dataclass
class AgentDeps:
    """Everything a run needs. Build one per report (the recorder and budget are per run)."""

    reader: CountersReader
    news: NewsCollector
    router: Router
    recorder: AuditRecorder
    budget: RunBudget
    models: dict[str, str] = field(default_factory=dict)
    news_policy: NewsPolicy | None = None
    kg: KgConfig | None = None
    """GraphRAG; ``None`` keeps the flat-news flow."""
    telemetry: Telemetry = field(default_factory=Telemetry)
    bundler: Callable[[ReportDraft], ReportBundle] | None = None
    """Renders HTML/JSON/PDF from the draft; ``None`` leaves the run with the draft only."""
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
