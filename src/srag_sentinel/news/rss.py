"""Google News RSS (pt-BR) provider: keyless, fast and on-topic in the T0d spike (ADR 0014).

Redirect links are never followed; the XML is parsed with defusedxml (no entity expansion).
Terms of use limit the feed to non-commercial use: documented in the README.
"""

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from srag_sentinel.news.models import Article, NewsError, NewsQuery, article_id, clip

ENDPOINT = "https://news.google.com/rss/search"
MAX_BYTES = 2_000_000
_TAG = re.compile(r"<[^>]+>")


def _text(value: str | None) -> str:
    return clip(html.unescape(_TAG.sub(" ", value or "")))


def _published(value: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if value else None
    except TypeError, ValueError:
        return None


def parse_rss(content: bytes) -> list[Article]:
    """Parse a Google News RSS document into articles (malformed items are skipped)."""
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise NewsError(f"google_news: unreadable feed ({type(error).__name__})") from error

    articles: list[Article] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        title = _text(item.findtext("title"))
        source_node = item.find("source")
        source = _text(source_node.text if source_node is not None else "")
        if not link.startswith("https://") or not title:
            continue
        suffix = f" - {source}"
        if source and title.endswith(suffix):
            title = title[: -len(suffix)]
        source_url = source_node.get("url", "") if source_node is not None else ""
        articles.append(
            Article(
                id=article_id(link),
                title=title,
                source=source or "Google News",
                domain=urlsplit(source_url).netloc.lower(),
                url=link,
                published_at=_published(item.findtext("pubDate")),
                snippet=_text(item.findtext("description")),
                provider="google_news",
            )
        )
    return articles


class GoogleNewsRssProvider:
    """Searches Google News RSS for pt-BR results."""

    name = "google_news"

    def __init__(self, client: httpx.AsyncClient, *, timeout: float = 30.0) -> None:
        self._client = client
        self._timeout = timeout

    async def search(self, query: NewsQuery) -> list[Article]:
        """Return up to ``query.max_results`` articles from the last ``lookback_days``."""
        params = {
            "q": f"{query.text} when:{query.lookback_days}d",
            "hl": "pt-BR",
            "gl": "BR",
            "ceid": "BR:pt-419",
        }
        try:
            response = await self._client.get(
                ENDPOINT, params=params, timeout=self._timeout, follow_redirects=False
            )
        except httpx.HTTPError as error:
            raise NewsError(f"google_news: request failed ({type(error).__name__})") from error
        if response.status_code != httpx.codes.OK:
            raise NewsError(f"google_news: HTTP {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise NewsError("google_news: response too large")
        return parse_rss(response.content)[: query.max_results]
