"""Fallback chain over several providers with deduplication (ADR 0014)."""

import re
from collections.abc import Sequence

from srag_sentinel.news.models import Article, NewsError, NewsQuery, NewsResult, canonical_url
from srag_sentinel.news.port import NewsProvider

_NON_WORD = re.compile(r"\W+")


def _title_key(title: str) -> str:
    return _NON_WORD.sub(" ", title.lower()).strip()


class ChainedNewsProvider:
    """Queries every provider in order, merges results and absorbs partial failures."""

    name = "chain"

    def __init__(self, providers: Sequence[NewsProvider]) -> None:
        if not providers:
            raise ValueError("at least one news provider is required")
        self._providers = list(providers)

    async def collect(self, query: NewsQuery) -> NewsResult:
        """Return merged articles and the names of providers that failed."""
        articles: list[Article] = []
        failures: list[str] = []
        for provider in self._providers:
            try:
                articles.extend(await provider.search(query))
            except NewsError as error:
                failures.append(str(error))
        return NewsResult(
            articles=tuple(_dedupe(articles))[: query.max_results], failures=tuple(failures)
        )

    async def search(self, query: NewsQuery) -> list[Article]:
        """Return merged articles; raise only if every provider failed."""
        result = await self.collect(query)
        if not result.articles and len(result.failures) == len(self._providers):
            raise NewsError("all news providers failed: " + "; ".join(result.failures))
        return list(result.articles)


def _dedupe(articles: Sequence[Article]) -> list[Article]:
    """Keep the first article per canonical URL and per normalised title."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        url_key, title_key = canonical_url(article.url), _title_key(article.title)
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(article)
    return unique
