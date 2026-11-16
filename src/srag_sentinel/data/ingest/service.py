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


async def resolve_sources(years: Sequence[int]) -> list[str]:
    """Resolve the current Parquet URL of each year from the portal."""
    async with httpx.AsyncClient(headers={"User-Agent": "srag-sentinel"}) as client:
        return [await resolve_parquet_url(year, client) for year in years]


async def ingest(settings: Settings, sources: Sequence[str]) -> IngestManifest:
    """Ingest ``sources`` (Parquet paths/URLs) using the least-privileged writer account."""
    if len(sources) < 2:  # noqa: PLR2004 - a single file can hold only part of a day's cases
        logger.warning(
            "ingesting fewer than two yearly files: days notified across years will be "
            "overwritten with partial counts; use the current and previous year together"
        )
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
