"""Scripted news provider for tests and offline runs."""

from srag_sentinel.news.models import Article, NewsError, NewsQuery


class FakeNewsProvider:
    """Returns fixed articles, or raises :class:`NewsError` when ``error`` is set."""

    def __init__(
        self, articles: list[Article] | None = None, *, name: str = "fake", error: str | None = None
    ) -> None:
        self._articles = articles or []
        self._error = error
        self.name = name
        self.queries: list[NewsQuery] = []

    async def search(self, query: NewsQuery) -> list[Article]:
        """Record the query and return the fixed articles."""
        self.queries.append(query)
        if self._error is not None:
            raise NewsError(f"{self.name}: {self._error}")
        return self._articles[: query.max_results]
