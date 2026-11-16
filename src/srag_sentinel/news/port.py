"""The news provider port."""

from typing import Protocol

from srag_sentinel.news.models import Article, NewsQuery


class NewsProvider(Protocol):
    """Searches news; raises :class:`~srag_sentinel.news.models.NewsError` on failure."""

    @property
    def name(self) -> str:
        """Provider identifier recorded on each article."""
        ...

    async def search(self, query: NewsQuery) -> list[Article]:
        """Return up to ``query.max_results`` articles."""
        ...
