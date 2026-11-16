"""GDELT DOC 2.0 provider (secondary source).

The service asks for at most one request every 5 seconds, answers 429 as plain text, and in the
T0d spike was slow (11-19 s) and sometimes returned ``{}``. This client therefore spaces calls,
uses a long timeout and treats every anomaly as a :class:`NewsError` for the chain to absorb.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from srag_sentinel.news.models import Article, NewsError, NewsQuery, article_id, clip

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_BYTES = 2_000_000
MIN_INTERVAL_SECONDS = 6.0
_SEEN_DATE = "%Y%m%dT%H%M%SZ"


class MinIntervalLimiter:
    """Allows one call at a time, at least ``interval`` seconds apart (injectable clock)."""

    def __init__(
        self,
        interval: float = MIN_INTERVAL_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def wait(self) -> None:
        """Block until the next call is allowed."""
        async with self._lock:
            if self._last is not None:
                remaining = self._interval - (self._clock() - self._last)
                if remaining > 0:
                    await self._sleep(remaining)
            self._last = self._clock()


def _seen(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value, _SEEN_DATE).replace(tzinfo=UTC) if value else None
    except ValueError:
        return None


def parse_gdelt(payload: Any) -> list[Article]:
    """Parse the ``artlist`` JSON into articles (``{}`` means no results)."""
    if not isinstance(payload, dict):
        raise NewsError("gdelt: unexpected response shape")
    articles: list[Article] = []
    for item in payload.get("articles", []):
        url = str(item.get("url", ""))
        title = clip(str(item.get("title", "")))
        if not url.startswith(("https://", "http://")) or not title:
            continue
        domain = str(item.get("domain", "")).lower()
        articles.append(
            Article(
                id=article_id(url),
                title=title,
                source=domain or "GDELT",
                domain=domain,
                url=url,
                published_at=_seen(item.get("seendate")),
                snippet="",
                provider="gdelt",
            )
        )
    return articles


class GdeltProvider:
    """Searches GDELT for Brazilian Portuguese articles."""

    name = "gdelt"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        limiter: MinIntervalLimiter | None = None,
        timeout: float = 45.0,
    ) -> None:
        self._client = client
        self._limiter = limiter or MinIntervalLimiter()
        self._timeout = timeout

    async def search(self, query: NewsQuery) -> list[Article]:
        """Return up to ``query.max_results`` articles from the last ``lookback_days``."""
        params = {
            "query": f"{query.text} sourcelang:portuguese sourcecountry:brazil",
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(query.max_results),
            "timespan": f"{query.lookback_days}d",
            "sort": "datedesc",
        }
        await self._limiter.wait()
        try:
            response = await self._client.get(
                ENDPOINT, params=params, timeout=self._timeout, follow_redirects=False
            )
        except httpx.HTTPError as error:
            raise NewsError(f"gdelt: request failed ({type(error).__name__})") from error
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise NewsError("gdelt: rate limited (429)")
        if response.status_code != httpx.codes.OK:
            raise NewsError(f"gdelt: HTTP {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise NewsError("gdelt: response too large")
        try:
            payload = response.json()
        except ValueError as error:
            raise NewsError("gdelt: response is not JSON") from error
        return parse_gdelt(payload)[: query.max_results]
