"""SurrealDB adapters for the counters ports. All values are bound as query variables."""

from datetime import date
from typing import Any

from surrealdb import AsyncSurrealConnection

from srag_sentinel.db.client import rows, run
from srag_sentinel.domain.models import COUNTER_FIELDS, DailyCounters

_COLUMNS = ", ".join(("uf", "day", *COUNTER_FIELDS))
_BATCH_SIZE = 500


class WriteRejectedError(RuntimeError):
    """The database accepted the request but stored nothing (e.g. missing permissions)."""


class SurrealCountersReader:
    """Reads daily counters; intended for a read-only database user."""

    def __init__(self, connection: AsyncSurrealConnection) -> None:
        self._connection = connection

    async def daily_counters(self, *, uf: str, start: date, end: date) -> list[DailyCounters]:
        """Return per-UF daily counters in ``[start, end]``; ``uf='BR'`` means every UF."""
        found = await rows(
            self._connection,
            # _COLUMNS is a module constant of fixed column names; values are bound variables.
            f"SELECT {_COLUMNS} FROM srag_daily "  # noqa: S608
            "WHERE day >= $start AND day <= $end AND ($uf = 'BR' OR uf = $uf) ORDER BY day, uf;",
            {"start": start.isoformat(), "end": end.isoformat(), "uf": uf},
        )
        return [_to_counters(row) for row in found]

    async def latest_day(self) -> date | None:
        """Return the most recent notification day available, or None when empty."""
        found = await rows(
            self._connection, "SELECT day FROM srag_daily ORDER BY day DESC LIMIT 1;"
        )
        return date.fromisoformat(found[0]["day"]) if found else None


class SurrealCountersWriter:
    """Upserts daily counters; requires a database user with write access."""

    def __init__(self, connection: AsyncSurrealConnection) -> None:
        self._connection = connection

    async def upsert_daily(self, rows_to_store: list[DailyCounters]) -> None:
        """Insert or replace daily counters (idempotent, keyed by UF and day)."""
        for start in range(0, len(rows_to_store), _BATCH_SIZE):
            batch = rows_to_store[start : start + _BATCH_SIZE]
            payload = [_to_record(row) for row in batch]
            await run(
                self._connection,
                "FOR $r IN $rows { UPSERT type::record('srag_daily', [$r.uf, $r.day]) "
                "CONTENT $r; };",
                {"rows": payload},
            )
            # Permission denials return silently, so confirm the batch really landed.
            if not await self._exists(batch[-1]):
                raise WriteRejectedError("upsert stored nothing; check database permissions")

    async def record_manifest(self, manifest: dict[str, Any]) -> None:
        """Store the manifest describing an ingestion run."""
        stored = await rows(
            self._connection, "CREATE ingest_manifest CONTENT $manifest;", {"manifest": manifest}
        )
        if not stored:
            raise WriteRejectedError("manifest stored nothing; check database permissions")

    async def _exists(self, row: DailyCounters) -> bool:
        found = await rows(
            self._connection,
            "SELECT uf FROM srag_daily WHERE uf = $uf AND day = $day LIMIT 1;",
            {"uf": row.uf, "day": row.day.isoformat()},
        )
        return bool(found)


def _to_record(row: DailyCounters) -> dict[str, Any]:
    record = row.model_dump(mode="json")
    record["day"] = row.day.isoformat()
    return record


def _to_counters(row: dict[str, Any]) -> DailyCounters:
    values = {name: row[name] for name in COUNTER_FIELDS}
    return DailyCounters(uf=row["uf"], day=date.fromisoformat(row["day"]), **values)
