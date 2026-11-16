"""Query-level cache decorator so repeated reports do not hammer the news services."""

import hashlib
import time
from collections.abc import Callable
from typing import Protocol

from srag_sentinel.news.models import Article, NewsQuery
from srag_sentinel.news.port import NewsProvider

DEFAULT_TTL_SECONDS = 6 * 60 * 60


class NewsCache(Protocol):
    """Stores article lists by key with a time-to-live."""

    def get(self, key: str) -> list[Article] | None:
        """Return the cached articles or None when absent/expired."""
        ...

    def put(self, key: str, articles: list[Article]) -> None:
        """Store ``articles`` under ``key``."""
        ...


class MemoryNewsCache:
    """In-process TTL cache (a SurrealDB-backed cache follows with the API wiring)."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict[str, tuple[float, list[Article]]] = {}

    def get(self, key: str) -> list[Article] | None:
        """Return the cached articles or None when absent/expired."""
        entry = self._items.get(key)
        if entry is None or self._clock() - entry[0] > self._ttl:
            self._items.pop(key, None)
            return None
        return list(entry[1])

    def put(self, key: str, articles: list[Article]) -> None:
        """Store ``articles`` under ``key``."""
        self._items[key] = (self._clock(), list(articles))


def cache_key(provider: str, query: NewsQuery) -> str:
    """Stable key for a provider and query."""
    raw = f"{provider}|{query.text.lower()}|{query.lookback_days}|{query.max_results}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CachedNewsProvider:
    """Serves repeated queries from the cache; failures are never cached."""

    def __init__(self, inner: NewsProvider, cache: NewsCache) -> None:
        self._inner = inner
        self._cache = cache

    @property
    def name(self) -> str:
        """Name of the wrapped provider."""
        return self._inner.name

    async def search(self, query: NewsQuery) -> list[Article]:
        """Return cached articles when fresh, otherwise query the provider and cache."""
        key = cache_key(self._inner.name, query)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        articles = await self._inner.search(query)
        self._cache.put(key, articles)
        return articles
