"""Locate the current yearly Parquet file on the OpenDATASUS portal (ADR 0012).

The portal's CKAN API is not available and file names change with every weekly update
(``INFLUD26-16-11-2026.parquet``), so the download link is read from the resource page.
"""

import re

import httpx

PORTAL = "https://dadosabertos.saude.gov.br"
DATASET = "srag-2019-a-2026"

# Stable resource ids of the Parquet resource per epidemiological year (portal listing, 2026-11).
PARQUET_RESOURCE_IDS: dict[int, str] = {
    2019: "53854458-36a9-447f-a8d4-6836396fea30",
    2020: "a29de31f-db28-43fc-92fd-f45bea2d39ee",
    2021: "b2adb027-6397-44e0-9557-e72b82e7b9c0",
    2022: "9410b844-f321-47c3-8136-0043c341b68b",
    2023: "795704b2-05bb-412b-a105-d44ff16353c0",
    2024: "0df883b2-4c71-4e7d-ab77-1767e6b956c5",
    2025: "66d478cf-1b6c-4bdb-a069-5b5fc4caeb2e",
    2026: "d3f164bd-0a1d-43eb-9410-357ad410d49c",
}

_FILE_URL = re.compile(
    r"https://s3\.sa-east-1\.amazonaws\.com/ckan\.saude\.gov\.br/SRAG/\d{4}/"
    r"INFLUD\d{2}-\d{2}-\d{2}-\d{4}\.parquet"
)
_TIMEOUT_SECONDS = 30.0


class SourceDiscoveryError(RuntimeError):
    """The portal page did not yield exactly one trusted Parquet URL."""


def extract_parquet_url(page_html: str) -> str:
    """Return the single trusted Parquet URL found in a resource page."""
    found: set[str] = {match.group(0) for match in _FILE_URL.finditer(page_html)}
    if len(found) != 1:
        raise SourceDiscoveryError(
            f"expected exactly one trusted Parquet link on the resource page, found {len(found)}"
        )
    return found.pop()


async def resolve_parquet_url(year: int, client: httpx.AsyncClient) -> str:
    """Return the current Parquet file URL for an epidemiological ``year``."""
    resource_id = PARQUET_RESOURCE_IDS.get(year)
    if resource_id is None:
        raise SourceDiscoveryError(f"no Parquet resource configured for year {year}")
    page = await client.get(
        f"{PORTAL}/dataset/{DATASET}/resource/{resource_id}",
        timeout=_TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    page.raise_for_status()
    return extract_parquet_url(page.text)
