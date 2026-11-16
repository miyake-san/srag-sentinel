"""Ports (interfaces) the rest of the application depends on."""

from datetime import date
from typing import Any, Protocol

from srag_sentinel.domain.models import DailyCounters


class CountersReader(Protocol):
    """Read access to the daily aggregates."""

    async def daily_counters(self, *, uf: str, start: date, end: date) -> list[DailyCounters]:
        """Return per-UF daily counters in ``[start, end]``; ``uf='BR'`` means every UF."""
        ...

    async def daily_cases(self, *, uf: str, start: date, end: date) -> dict[date, int]:
        """Return notified cases per day in ``[start, end]`` (days without data are absent)."""
        ...

    async def latest_day(self) -> date | None:
        """Return the most recent notification day available, or None when empty."""
        ...

    async def last_retrieved_on(self) -> date | None:
        """Return the date of the most recent ingestion, or None when nothing was ingested."""
        ...


class CountersWriter(Protocol):
    """Write access used only by the ingestion job."""

    async def upsert_daily(self, rows: list[DailyCounters]) -> None:
        """Insert or replace daily counters (idempotent, keyed by UF and day)."""
        ...

    async def record_manifest(self, manifest: dict[str, Any]) -> None:
        """Store the manifest describing an ingestion run."""
        ...
