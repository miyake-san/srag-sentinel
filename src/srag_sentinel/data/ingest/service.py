"""Wiring for the ``ingest`` command: discover sources, connect as the ingest user, run."""

import logging
from collections.abc import Sequence

import httpx

from srag_sentinel.data.ingest.discovery import resolve_parquet_url
from srag_sentinel.data.ingest.pipeline import IngestManifest, run_ingest
from srag_sentinel.data.repository import SurrealCountersWriter
from srag_sentinel.db.client import open_connection
from srag_sentinel.settings import Settings

logger = logging.getLogger(__name__)

MIN_SOURCES = 2


async def resolve_sources(years: Sequence[int]) -> list[str]:
    """Resolve the current Parquet URL of each year from the portal."""
    async with httpx.AsyncClient(headers={"User-Agent": "srag-sentinel"}) as client:
        return [await resolve_parquet_url(year, client) for year in years]


class PartialIngestError(ValueError):
    """Refusing to ingest a single yearly file, which would overwrite days with partial counts."""


async def ingest(
    settings: Settings, sources: Sequence[str], *, allow_partial: bool = False
) -> IngestManifest:
    """Ingest ``sources`` (Parquet paths/URLs) using the least-privileged writer account.

    One day can be split across yearly files (late notifications live in the file of the
    symptom-onset year), so a single file would overwrite that day with partial counts. Loading
    fewer than two files therefore needs ``allow_partial=True``.
    """
    if len(sources) < MIN_SOURCES and not allow_partial:
        raise PartialIngestError(
            "ingest at least two yearly files together (current and previous year), or pass "
            "--allow-partial to accept partial counts for days that span several files"
        )
    if len(sources) < MIN_SOURCES:
        logger.warning("partial ingestion allowed: days spanning several files may be understated")
    auth = {
        "namespace": settings.surreal_namespace,
        "database": settings.surreal_data_database,
        "username": settings.surreal_ingest_user,
        "password": settings.surreal_ingest_password.get_secret_value(),
    }
    async with open_connection(
        settings.surreal_url,
        auth=auth,
        namespace=settings.surreal_namespace,
        database=settings.surreal_data_database,
    ) as connection:
        return await run_ingest(SurrealCountersWriter(connection), sources)
