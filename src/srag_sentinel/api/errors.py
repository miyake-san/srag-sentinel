"""RFC 9457 problem details. Messages are fixed text: no traces, queries or provider output."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from srag_sentinel.observability.setup import current_trace_id

PROBLEM_JSON = "application/problem+json"


def problem(  # noqa: PLR0913 - the fields of an RFC 9457 document
    status: int,
    title: str,
    *,
    detail: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a ``application/problem+json`` response."""
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if run_id:
        body["run_id"] = run_id
    if trace_id:
        body["trace_id"] = trace_id
    body.update(extra or {})
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None) or current_trace_id()


def install_error_handlers(app: FastAPI) -> None:
    """Turn every error into a problem document."""

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, error: RequestValidationError) -> JSONResponse:
        # Only field locations and rule types: the rejected values are never echoed back.
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "rule": e["type"]}
            for e in error.errors()
        ]
        return problem(
            422,
            "Invalid request",
            detail="The request body did not pass validation.",
            trace_id=_trace_id(request),
            extra={"errors": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return problem(
            error.status_code, _TITLES.get(error.status_code, "Error"), trace_id=_trace_id(request)
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        return problem(
            500,
            "Internal error",
            detail="The report could not be produced. See the audit trail for this run.",
            trace_id=_trace_id(request),
        )


_TITLES = {404: "Not found", 405: "Method not allowed", 401: "Unauthorized", 403: "Forbidden"}
