import httpx
import pytest
import respx

from srag_sentinel.data.ingest.discovery import (
    PARQUET_RESOURCE_IDS,
    PORTAL,
    SourceDiscoveryError,
    extract_parquet_url,
    resolve_parquet_url,
)

GOOD = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2026/INFLUD26-16-11-2026.parquet"
OTHER = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2026/INFLUD26-09-11-2026.parquet"


def page(*links: str) -> str:
    anchors = "".join(f'<a href="{link}">Baixar</a>' for link in links)
    return f"<html><body>{anchors}</body></html>"


def test_extracts_the_single_trusted_link() -> None:
    assert extract_parquet_url(page(GOOD)) == GOOD


def test_repeated_identical_link_is_fine() -> None:
    assert extract_parquet_url(page(GOOD, GOOD)) == GOOD


@pytest.mark.parametrize(
    "html",
    [
        page(),  # no link
        page(GOOD, OTHER),  # ambiguous
        page("https://evil.example.com/SRAG/2026/INFLUD26-16-11-2026.parquet"),  # wrong host
        page(
            "https://s3.sa-east-1.amazonaws.com/other-bucket/SRAG/2026/INFLUD26-16-11-2026.parquet"
        ),
        page(
            "http://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2026/INFLUD26-16-11-2026.parquet"
        ),
    ],
)
def test_untrusted_or_ambiguous_pages_are_rejected(html: str) -> None:
    with pytest.raises(SourceDiscoveryError):
        extract_parquet_url(html)


@respx.mock
async def test_resolve_reads_the_resource_page() -> None:
    resource = PARQUET_RESOURCE_IDS[2026]
    route = respx.get(f"{PORTAL}/dataset/srag-2019-a-2026/resource/{resource}").mock(
        return_value=httpx.Response(200, text=page(GOOD))
    )

    async with httpx.AsyncClient() as client:
        assert await resolve_parquet_url(2026, client) == GOOD
    assert route.called


@respx.mock
async def test_resolve_propagates_http_errors() -> None:
    respx.get(url__startswith=PORTAL).mock(return_value=httpx.Response(503))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await resolve_parquet_url(2025, client)


async def test_resolve_rejects_unknown_year() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceDiscoveryError, match="1999"):
            await resolve_parquet_url(1999, client)
