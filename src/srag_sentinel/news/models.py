"""News models. Articles are untrusted data: metadata and a short snippet, never full pages."""

import hashlib
import re
from datetime import datetime
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SNIPPET = 400
_QUERY_ALLOWED = re.compile(r"^[\w\s\"'\-.,%]{3,120}$")


class NewsError(RuntimeError):
    """A news provider failed (network, rate limit, malformed response)."""


class Article(BaseModel):
    """One retrieved item. ``id`` is a stable hash of the canonical URL."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    source: str
    domain: str
    url: str
    published_at: datetime | None = None
    snippet: str = Field(default="", max_length=MAX_SNIPPET)
    provider: str


class NewsQuery(BaseModel):
    """A validated search request. Provider operators (``site:``, ``when:``...) are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    lookback_days: int = Field(default=14, ge=1, le=30)
    max_results: int = Field(default=10, ge=1, le=25)

    @model_validator(mode="after")
    def _safe_text(self) -> Self:
        # The allowed set has no ':', '(', ')' or '|', so provider operators cannot be injected.
        if not _QUERY_ALLOWED.fullmatch(self.text):
            raise ValueError("query must be 3-120 letters, digits and basic punctuation")
        return self


class NewsResult(BaseModel):
    """Articles plus the providers that failed while collecting them."""

    model_config = ConfigDict(frozen=True)

    articles: tuple[Article, ...]
    failures: tuple[str, ...] = ()


def canonical_url(url: str) -> str:
    """Lower-case host, no fragment or query: the identity used for ids and deduplication."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def article_id(url: str) -> str:
    """Stable 16-hex-character id for an article URL."""
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def clip(text: str, limit: int = MAX_SNIPPET) -> str:
    """Collapse whitespace and truncate to ``limit`` characters."""
    return " ".join(text.split())[:limit]
