"""Ingestion pipeline: read allowlisted columns, clean, aggregate, merge, store, record manifest."""

import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl
from pydantic import BaseModel, ConfigDict

from srag_sentinel.data.ingest.transform import (
    ALLOWLIST,
    aggregate,
    clean,
    merge,
    to_counters,
    validate_schema,
)
from srag_sentinel.data.ports import CountersWriter
from srag_sentinel.domain.models import DailyCounters


class IngestManifest(BaseModel):
    """What one ingestion run read and stored (written to ``ingest_manifest``)."""

    model_config = ConfigDict(frozen=True)

    source_urls: list[str]
    retrieved_at: datetime
    rows_read: int
    rows_kept: int
    dropped: dict[str, int]
    snapshot_sha256: str


def snapshot_sha256(rows: Sequence[DailyCounters]) -> str:
    """Hash of the canonical, sorted aggregates; equal data always gives the same hash."""
    ordered = sorted(rows, key=lambda row: (row.uf, row.day))
    canonical = json.dumps(
        [row.model_dump(mode="json") for row in ordered], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_allowlisted(source: str) -> pl.DataFrame:
    """Read only the allowlisted columns from a Parquet path or URL (projection pushdown)."""
    lazy = pl.scan_parquet(source)
    validate_schema(lazy.collect_schema())
    return lazy.select(ALLOWLIST).collect()


async def run_ingest(
    writer: CountersWriter,
    sources: Sequence[str],
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> IngestManifest:
    """Ingest every source, merge the aggregates and upsert them idempotently."""
    today = today or datetime.now(UTC).date()
    retrieved_at = now or datetime.now(UTC)

    aggregates: list[pl.DataFrame] = []
    rows_read = rows_kept = 0
    dropped: dict[str, int] = {}
    for source in sources:
        frame = await asyncio.to_thread(read_allowlisted, source)
        cleaned, stats = clean(frame, today=today)
        aggregates.append(aggregate(cleaned))
        rows_read += stats.rows_read
        rows_kept += stats.rows_kept
        for name, count in stats.dropped.items():
            dropped[name] = dropped.get(name, 0) + count

    counters = to_counters(merge(aggregates))
    await writer.upsert_daily(counters)
    manifest = IngestManifest(
        source_urls=list(sources),
        retrieved_at=retrieved_at,
        rows_read=rows_read,
        rows_kept=rows_kept,
        dropped=dropped,
        snapshot_sha256=snapshot_sha256(counters),
    )
    await writer.record_manifest(manifest.model_dump())
    return manifest
