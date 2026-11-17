"""API perimeter: bearer-key authentication, rate and concurrency caps, body limits, headers.

Implements docs/specs/09 §3 (A1-A7) as one pure-ASGI middleware, so the checks run before routing
and before the request body is parsed. Refusals are fixed RFC 9457 problems that never echo the
request or the key, and each one is counted as ``srag.api.rejections{reason}``.
"""

import hashlib
import hmac
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from srag_sentinel.api.errors import problem
from srag_sentinel.settings import Settings

LOGGER = logging.getLogger(__name__)

PUBLIC_PATHS = frozenset({"/healthz", "/readyz"})
GENERATE = ("POST", "/v1/reports")
WINDOW_SECONDS = 60.0
BUSY_RETRY_SECONDS = 5
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _ignore(reason: str) -> None:
    """Default rejection hook (the app replaces it with the telemetry counter)."""


@dataclass
class Perimeter:
    """Limits and counters shared by every request (single process, see ADR 0020)."""

    keys: tuple[str, ...]
    rate_per_minute: int
    max_concurrent: int
    max_body_bytes: int
    clock: Callable[[], float] = time.monotonic
    on_reject: Callable[[str], None] = _ignore
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _running: int = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> Perimeter:
        """Build from settings; outside ``dev`` a missing key list is a boot error (A1)."""
        raw = settings.api_keys.get_secret_value()
        keys = tuple(key.strip() for key in raw.split(",") if key.strip())
        if not keys and settings.environment != "dev":
            raise RuntimeError("SRAG_API_KEYS is required when SRAG_ENVIRONMENT is not 'dev'")
        if not keys:
            LOGGER.warning("API authentication is disabled (dev environment, no SRAG_API_KEYS)")
        return cls(
            keys=keys,
            rate_per_minute=settings.api_rate_per_minute,
            max_concurrent=settings.api_max_concurrent,
            max_body_bytes=settings.api_max_body_bytes,
        )

    def identify(self, authorization: str | None, client: str) -> str | None:
        """Caller identity for rate limiting, or None when the credentials are not accepted."""
        if not self.keys:
            return f"ip:{client}"
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        accepted = False
        for key in self.keys:  # no early exit: the time does not reveal which key matched
            accepted |= hmac.compare_digest(key.encode(), token.encode())
        if scheme.lower() != "bearer" or not accepted:
            return None
        return "key:" + hashlib.sha256(token.encode()).hexdigest()[:12]

    def retry_after(self, identity: str) -> int | None:
        """Register a hit; return seconds to wait when the caller is over its rate."""
        now = self.clock()
        hits = self._hits.setdefault(identity, deque())
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.rate_per_minute:
            return max(1, math.ceil(WINDOW_SECONDS - (now - hits[0])))
        hits.append(now)
        return None

    def acquire(self) -> bool:
        """Reserve one generation slot; False when the process is already at its cap."""
        if self._running >= self.max_concurrent:
            return False
        self._running += 1
        return True

    def release(self) -> None:
        """Give a generation slot back."""
        self._running = max(0, self._running - 1)


async def _read_body(receive: Receive, limit: int) -> bytes | None:
    """Read the whole body, or None as soon as it exceeds ``limit`` bytes."""
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay(body: bytes) -> Receive:
    """A ``receive`` that hands the already-read body to the application once."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _with_security_headers(send: Send) -> Send:
    """Add the A5 headers to every response without overriding what a route already set."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            message.setdefault("headers", [])
            headers = MutableHeaders(scope=message)
            for name, value in _BASE_HEADERS.items():
                headers.setdefault(name, value)
            content_type = headers.get("content-type", "")
            if content_type.startswith("text/html"):
                headers.setdefault("Content-Security-Policy", HTML_CSP)
            elif content_type.startswith("application/pdf"):
                headers.setdefault("Content-Disposition", 'inline; filename="srag-report.pdf"')
        await send(message)

    return wrapped


class PerimeterMiddleware:
    """Apply :class:`Perimeter` to every HTTP request."""

    def __init__(self, app: ASGIApp, perimeter: Perimeter) -> None:
        self.app = app
        self.perimeter = perimeter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Authenticate, then guard the expensive route, then hand over to the application."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        send = _with_security_headers(send)
        if scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        client = scope["client"][0] if scope.get("client") else "unknown"
        identity = self.perimeter.identify(headers.get("authorization"), client)
        if identity is None:
            await self._refuse(
                scope, receive, send, "unauthorized", 401, {"WWW-Authenticate": "Bearer"}
            )
            return
        if (scope["method"], scope["path"]) == GENERATE:
            await self._generate(scope, receive, send, identity, headers)
            return
        await self.app(scope, receive, send)

    async def _generate(
        self, scope: Scope, receive: Receive, send: Send, identity: str, headers: Headers
    ) -> None:
        perimeter = self.perimeter
        wait = perimeter.retry_after(identity)
        if wait is not None:
            await self._refuse(
                scope, receive, send, "rate_limited", 429, {"Retry-After": str(wait)}
            )
            return
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            await self._refuse(scope, receive, send, "unsupported_media_type", 415)
            return
        body = await _read_body(receive, perimeter.max_body_bytes)
        if body is None:
            await self._refuse(scope, receive, send, "body_too_large", 413)
            return
        if not perimeter.acquire():
            busy = {"Retry-After": str(BUSY_RETRY_SECONDS)}
            await self._refuse(scope, receive, send, "busy", 429, busy)
            return
        try:
            await self.app(scope, _replay(body), send)
        finally:
            perimeter.release()

    async def _refuse(  # noqa: PLR0913, PLR0917 - ASGI triple plus the refusal description
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        reason: str,
        status: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.perimeter.on_reject(reason)
        LOGGER.warning("api request refused", extra={"reason": reason, "status": status})
        response = problem(status, _TITLES[reason], detail=_DETAILS[reason])
        for name, value in (headers or {}).items():
            response.headers[name] = value
        await response(scope, receive, send)


_TITLES = {
    "unauthorized": "Unauthorized",
    "rate_limited": "Too many requests",
    "busy": "Too many requests",
    "unsupported_media_type": "Unsupported media type",
    "body_too_large": "Payload too large",
}
_DETAILS = {
    "unauthorized": "A valid bearer key is required.",
    "rate_limited": "The request rate for this key was exceeded.",
    "busy": "Too many reports are being generated right now; retry shortly.",
    "unsupported_media_type": "The body must be application/json.",
    "body_too_large": "The request body is larger than the allowed size.",
}
