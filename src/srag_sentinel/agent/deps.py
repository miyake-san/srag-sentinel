"""Dependencies injected into the graph (ports, never concrete adapters)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from srag_sentinel.data.ports import CountersReader
from srag_sentinel.governance.recorder import AuditRecorder
from srag_sentinel.guardrails.budget import RunBudget
from srag_sentinel.guardrails.news import NewsPolicy
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.news.models import NewsQuery, NewsResult


class NewsCollector(Protocol):
    """Collects news and reports which providers failed (the chained provider)."""

    async def collect(self, query: NewsQuery) -> NewsResult:
        """Return merged articles and provider failures."""
        ...


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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
