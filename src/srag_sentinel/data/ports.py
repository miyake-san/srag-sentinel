"""Ports (interfaces) the rest of the application depends on."""

from datetime import date
from typing import Protocol

from srag_sentinel.domain.models import DailyCounters


class CountersReader(Protocol):
    """Read access to the daily aggregates."""

    async def daily_counters(self, *, uf: str, start: date, end: date) -> list[DailyCounters]:
        """Return per-UF daily counters in ``[start, end]``; ``uf='BR'`` means every UF."""
        ...

    async def latest_day(self) -> date | None:
        """Return the most recent notification day available, or None when empty."""
        ...


class CountersWriter(Protocol):
    """Write access used only by the ingestion job."""

    async def upsert_daily(self, rows: list[DailyCounters]) -> None:
        """Insert or replace daily counters (idempotent, keyed by UF and day)."""
        ...
