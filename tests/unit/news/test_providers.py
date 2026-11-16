import httpx
import pytest
import respx
from pydantic import ValidationError

from srag_sentinel.news.gdelt import ENDPOINT as GDELT_URL
from srag_sentinel.news.gdelt import GdeltProvider, MinIntervalLimiter, parse_gdelt
from srag_sentinel.news.models import Article, NewsError, NewsQuery, article_id, canonical_url
from srag_sentinel.news.rss import ENDPOINT as RSS_URL
from srag_sentinel.news.rss import GoogleNewsRssProvider, parse_rss

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>x</title>
<item>
  <title>SRAG avança em cinco estados - Agência Brasil</title>
  <link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link>
  <pubDate>Thu, 05 Nov 2026 08:00:00 GMT</pubDate>
  <description>
    &lt;a href="https://x"&gt;SRAG avan&amp;ccedil;a&lt;/a&gt;&lt;b&gt;AB&lt;/b&gt;
  </description>
  <source url="https://agenciabrasil.ebc.com.br">Agência Brasil</source>
</item>
<item>
  <title>Casos de influenza sobem - G1</title>
  <link>https://news.google.com/rss/articles/CBMiBBB</link>
  <pubDate>not a date</pubDate>
  <source url="https://g1.globo.com">G1</source>
</item>
<item><title>no link</title></item>
<item><title>http link</title><link>http://insecure.example/a</link></item>
</channel></rss>"""

GDELT = {
    "articles": [
        {
            "url": "https://example.com.br/a",
            "title": "  Gripe   e SRAG  ",
            "seendate": "20261023T230000Z",
            "domain": "Example.com.br",
            "language": "Portuguese",
        },
        {"url": "javascript:alert(1)", "title": "bad"},
        {"url": "https://example.com.br/b", "title": ""},
    ]
}


def query(text: str = "síndrome respiratória", **kw: int) -> NewsQuery:
    return NewsQuery(text=text, **kw)


# ---- query validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["ab", "x" * 121, "site:evil.com", "a OR (b)", "a|b", "<script>", "sourcelang:spanish gripe"],
)
def test_queries_with_operators_or_bad_length_are_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        NewsQuery(text=text)


def test_reasonable_portuguese_queries_are_accepted() -> None:
    assert NewsQuery(text='"síndrome respiratória aguda grave" influenza').text


@pytest.mark.parametrize("kw", [{"lookback_days": 0}, {"lookback_days": 31}, {"max_results": 26}])
def test_query_limits_are_enforced(kw: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        NewsQuery(text="gripe forte", **kw)


def test_article_ids_ignore_query_strings_fragments_and_host_case() -> None:
    assert article_id("https://A.com/x?utm=1#f") == article_id("https://a.com/x/")
    assert canonical_url("https://A.com/x/?q=1") == "https://a.com/x"


# ---- Google News RSS ---------------------------------------------------------------


def test_rss_parsing_cleans_titles_snippets_and_skips_bad_items() -> None:
    articles = parse_rss(RSS.encode())

    assert [a.title for a in articles] == [
        "SRAG avança em cinco estados",
        "Casos de influenza sobem",
    ]
    first = articles[0]
    assert first.source == "Agência Brasil"
    assert first.domain == "agenciabrasil.ebc.com.br"
    assert "<" not in first.snippet
    assert first.published_at is not None and first.published_at.year == 2026
    assert articles[1].published_at is None  # unparsable date is tolerated
    assert first.provider == "google_news"


def test_rss_rejects_entity_expansion_attacks() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;">]>'
        b"<rss><channel><item><title>&b;</title>"
        b"<link>https://x.example/a</link></item></channel></rss>"
    )

    with pytest.raises(NewsError, match="unreadable"):
        parse_rss(bomb)


def test_rss_rejects_garbage() -> None:
    with pytest.raises(NewsError):
        parse_rss(b"<<<not xml")


@respx.mock
async def test_rss_provider_builds_the_query_and_limits_results() -> None:
    route = respx.get(RSS_URL).mock(return_value=httpx.Response(200, content=RSS.encode()))

    async with httpx.AsyncClient() as client:
        found = await GoogleNewsRssProvider(client).search(query(lookback_days=7, max_results=1))

    assert len(found) == 1
    params = route.calls[0].request.url.params
    assert params["q"] == "síndrome respiratória when:7d"
    assert (params["hl"], params["gl"]) == ("pt-BR", "BR")


@respx.mock
@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(302, headers={"location": "https://evil.example"}), "HTTP 302"),
        (httpx.Response(200, content=b"x" * 2_000_001), "too large"),
    ],
)
async def test_rss_provider_turns_failures_into_news_errors(
    response: httpx.Response, match: str
) -> None:
    respx.get(RSS_URL).mock(return_value=response)

    async with httpx.AsyncClient() as client:
        with pytest.raises(NewsError, match=match):
            await GoogleNewsRssProvider(client).search(query())


@respx.mock
async def test_rss_provider_wraps_network_errors() -> None:
    respx.get(RSS_URL).mock(side_effect=httpx.ConnectTimeout("slow"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(NewsError, match="ConnectTimeout"):
            await GoogleNewsRssProvider(client).search(query())


# ---- GDELT -------------------------------------------------------------------------


def test_gdelt_parsing_filters_unsafe_urls_and_normalises_fields() -> None:
    articles = parse_gdelt(GDELT)

    assert len(articles) == 1
    assert articles[0].title == "Gripe e SRAG"
    assert articles[0].domain == "example.com.br"
    assert articles[0].published_at is not None and articles[0].published_at.hour == 23


def test_gdelt_empty_object_means_no_results_but_other_shapes_are_errors() -> None:
    assert parse_gdelt({}) == []
    with pytest.raises(NewsError):
        parse_gdelt(["not", "a", "dict"])


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_limiter_spaces_consecutive_calls() -> None:
    clock = Clock()
    limiter = MinIntervalLimiter(6.0, clock=clock, sleep=clock.sleep)

    await limiter.wait()  # first call is immediate
    clock.now += 2.0
    await limiter.wait()  # 4 s short of the interval
    await limiter.wait()  # a full interval again

    assert clock.slept == [pytest.approx(4.0), pytest.approx(6.0)]


@respx.mock
async def test_gdelt_provider_sends_pt_br_filters_and_respects_the_limiter() -> None:
    route = respx.get(GDELT_URL).mock(return_value=httpx.Response(200, json=GDELT))
    clock = Clock()
    limiter = MinIntervalLimiter(6.0, clock=clock, sleep=clock.sleep)

    async with httpx.AsyncClient() as client:
        provider = GdeltProvider(client, limiter=limiter)
        await provider.search(query(max_results=5))
        await provider.search(query(max_results=5))

    params = route.calls[0].request.url.params
    assert "sourcelang:portuguese" in params["query"]
    assert "sourcecountry:brazil" in params["query"]
    assert (params["mode"], params["format"], params["maxrecords"]) == ("artlist", "json", "5")
    assert clock.slept == [pytest.approx(6.0)]


@respx.mock
@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(429, text="Please limit requests to one every 5 seconds"), "rate limited"),
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, text="<html>nope</html>"), "not JSON"),
    ],
)
async def test_gdelt_failures_become_news_errors(response: httpx.Response, match: str) -> None:
    respx.get(GDELT_URL).mock(return_value=response)
    clock = Clock()

    async with httpx.AsyncClient() as client:
        provider = GdeltProvider(
            client, limiter=MinIntervalLimiter(0, clock=clock, sleep=clock.sleep)
        )
        with pytest.raises(NewsError, match=match):
            await provider.search(query())


@respx.mock
async def test_gdelt_empty_object_response_is_an_empty_list() -> None:
    respx.get(GDELT_URL).mock(return_value=httpx.Response(200, json={}))
    clock = Clock()

    async with httpx.AsyncClient() as client:
        provider = GdeltProvider(
            client, limiter=MinIntervalLimiter(0, clock=clock, sleep=clock.sleep)
        )
        assert await provider.search(query()) == []


def article(url: str, title: str, provider: str = "fake") -> Article:
    return Article(
        id=article_id(url), title=title, source="s", domain="d", url=url, provider=provider
    )
