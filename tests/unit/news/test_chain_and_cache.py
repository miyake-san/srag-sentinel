import pytest

from srag_sentinel.news.cache import CachedNewsProvider, MemoryNewsCache, cache_key
from srag_sentinel.news.chain import ChainedNewsProvider
from srag_sentinel.news.fake import FakeNewsProvider
from srag_sentinel.news.models import Article, NewsError, NewsQuery, article_id

QUERY = NewsQuery(text="síndrome respiratória", max_results=5)


def make(url: str, title: str) -> Article:
    return Article(
        id=article_id(url), title=title, source="s", domain="d", url=url, provider="fake"
    )


async def test_chain_merges_providers_in_order_and_deduplicates() -> None:
    first = FakeNewsProvider(
        [make("https://a.com/1", "Gripe sobe"), make("https://a.com/2", "VSR")]
    )
    second = FakeNewsProvider(
        [make("https://A.com/1?utm=x", "Outro título"), make("https://b.com/9", "gripe  sobe!")]
    )

    result = await ChainedNewsProvider([first, second]).collect(QUERY)

    assert [a.url for a in result.articles] == ["https://a.com/1", "https://a.com/2"]
    assert result.failures == ()


async def test_a_failing_provider_is_absorbed_and_reported() -> None:
    broken = FakeNewsProvider(name="gdelt", error="rate limited (429)")
    good = FakeNewsProvider([make("https://a.com/1", "t")])

    result = await ChainedNewsProvider([broken, good]).collect(QUERY)

    assert len(result.articles) == 1
    assert result.failures == ("gdelt: rate limited (429)",)


async def test_search_raises_only_when_every_provider_failed() -> None:
    chain = ChainedNewsProvider(
        [FakeNewsProvider(name="a", error="down"), FakeNewsProvider(name="b", error="down")]
    )

    with pytest.raises(NewsError, match="all news providers failed"):
        await chain.search(QUERY)


async def test_search_returns_empty_when_providers_work_but_find_nothing() -> None:
    assert await ChainedNewsProvider([FakeNewsProvider([])]).search(QUERY) == []


async def test_results_are_capped_at_max_results() -> None:
    many = FakeNewsProvider([make(f"https://a.com/{i}", f"title {i}") for i in range(20)])

    result = await ChainedNewsProvider([many]).collect(NewsQuery(text="gripe forte", max_results=3))

    assert len(result.articles) == 3


def test_a_chain_needs_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ChainedNewsProvider([])


async def test_cache_serves_repeated_queries_without_calling_the_provider() -> None:
    inner = FakeNewsProvider([make("https://a.com/1", "t")])
    cached = CachedNewsProvider(inner, MemoryNewsCache())

    first = await cached.search(QUERY)
    second = await cached.search(QUERY)

    assert first == second
    assert len(inner.queries) == 1
    assert cached.name == "fake"


async def test_cache_entries_expire() -> None:
    now = [0.0]
    cache = MemoryNewsCache(ttl_seconds=10, clock=lambda: now[0])
    inner = FakeNewsProvider([make("https://a.com/1", "t")])
    cached = CachedNewsProvider(inner, cache)

    await cached.search(QUERY)
    now[0] = 11.0
    await cached.search(QUERY)

    assert len(inner.queries) == 2


async def test_failures_are_never_cached() -> None:
    cache = MemoryNewsCache()
    failing = CachedNewsProvider(FakeNewsProvider(error="down"), cache)

    with pytest.raises(NewsError):
        await failing.search(QUERY)

    assert cache.get(cache_key("fake", QUERY)) is None


def test_cache_keys_differ_by_provider_and_query() -> None:
    other = NewsQuery(text="síndrome respiratória", max_results=6)

    assert cache_key("a", QUERY) != cache_key("b", QUERY)
    assert cache_key("a", QUERY) != cache_key("a", other)
    assert cache_key("a", QUERY) == cache_key(
        "a", NewsQuery(text="SÍNDROME RESPIRATÓRIA", max_results=5)
    )
