"""The FastAPI application (composition happens in the lifespan, never in module globals)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, ConfigDict, Field

from srag_sentinel import __version__
from srag_sentinel.api.errors import install_error_handlers, problem
from srag_sentinel.api.perimeter import Perimeter, PerimeterMiddleware
from srag_sentinel.governance.model import AuditEvent
from srag_sentinel.observability.setup import (
    configure_logging,
    current_trace_id,
    setup_telemetry,
)
from srag_sentinel.service import ReportNotFoundError, ReportService, RunResult
from srag_sentinel.settings import Settings, get_settings

MEDIA = {"json": "application/json", "html": "text/html; charset=utf-8", "pdf": "application/pdf"}


class ServicePort(Protocol):
    """What the routes need from the service (a fake in tests)."""

    async def start(self) -> None:
        """Open resources."""
        ...

    async def stop(self) -> None:
        """Release resources."""
        ...

    async def ready(self) -> bool:
        """Whether data is available."""
        ...

    async def generate(self, raw_request: dict[str, Any]) -> RunResult:
        """Run one report."""
        ...

    def artifact(self, run_id: str, fmt: str) -> Path:
        """Path of a stored artifact."""
        ...

    async def audit_events(self, run_id: str) -> list[AuditEvent]:
        """Audit events of one run."""
        ...


class ReportRequest(BaseModel):
    """Body of ``POST /v1/reports``. Unknown fields are rejected (guardrail G1 checks again)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uf: Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")] = "BR"
    as_of: date | None = None
    window_days: Annotated[int, Field(ge=7, le=90)] = 30


class ReportCreated(BaseModel):
    """Summary of a finished run with links to the artifacts."""

    run_id: str
    status: Literal["ok", "degraded"]
    degradations: list[str]
    links: dict[str, str]


def get_service(request: Request) -> ServicePort:
    """Dependency: the service built in the lifespan."""
    service: ServicePort = request.app.state.service
    return service


Service = Annotated[ServicePort, Depends(get_service)]


def create_app(settings: Settings | None = None, *, service: ServicePort | None = None) -> FastAPI:
    """Build the app. Tests pass a fake ``service``; production builds one from the settings."""

    config = settings or get_settings()
    perimeter = Perimeter.from_settings(config)  # fails the boot when keys are required

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        runtime = setup_telemetry(config.otel_endpoint, environment=config.environment)
        perimeter.on_reject = runtime.telemetry.api_rejected
        built = service or ReportService(config, telemetry=runtime.telemetry)
        await built.start()
        app.state.service = built
        try:
            yield
        finally:
            await built.stop()
            runtime.shutdown()

    app = FastAPI(title="SRAG Sentinel", version=__version__, lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(PerimeterMiddleware, perimeter=perimeter)
    if config.otel_endpoint:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    _add_health_routes(app)
    _add_report_routes(app)
    _add_audit_routes(app)
    return app


def _add_health_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", response_model=None)
    async def readyz(svc: Service) -> Response:
        if await svc.ready():
            return JSONResponse({"status": "ready"})
        return problem(503, "Not ready", detail="The database is unreachable or has no data.")


def _add_report_routes(app: FastAPI) -> None:
    @app.post("/v1/reports", response_model=None)
    async def create_report(body: ReportRequest, svc: Service) -> Response:
        result = await svc.generate(body.model_dump(mode="json", exclude_none=True))
        if result.rejected:
            return problem(
                422,
                "Request rejected",
                detail="The request was rejected by the input guardrail.",
                run_id=result.run_id,
                trace_id=current_trace_id(),
            )
        report = result.state.report
        assert report is not None  # noqa: S101 - a non-rejected run always produces a report
        created = ReportCreated(
            run_id=result.run_id,
            status=report.status,
            degradations=list(report.degradations),
            links={fmt: f"/v1/reports/{result.run_id}?format={fmt}" for fmt in result.files},
        )
        return JSONResponse(created.model_dump(), status_code=200)

    @app.get("/v1/reports/{run_id}", response_model=None)
    async def get_report(
        run_id: str,
        svc: Service,
        fmt: Annotated[Literal["json", "html", "pdf"], Query(alias="format")] = "json",
    ) -> Response:
        try:
            path = svc.artifact(run_id, fmt)
        except ReportNotFoundError:
            return problem(404, "Report not found", detail="No stored report for this run id.")
        return FileResponse(path, media_type=MEDIA[fmt], headers={"Cache-Control": "no-store"})


def _add_audit_routes(app: FastAPI) -> None:
    @app.get("/v1/audit/{run_id}")
    async def get_audit(run_id: str, svc: Service) -> dict[str, Any]:
        events = await svc.audit_events(run_id)
        if not events:
            raise ReportNotFoundError(run_id)
        return {
            "run_id": run_id,
            "events": [
                {
                    "seq": e.seq,
                    "ts": e.ts,
                    "node": e.node,
                    "event": e.event,
                    # Counters only (A6): free text and identifiers never leave through this route.
                    "details": {
                        key: value
                        for key, value in e.details.items()
                        if isinstance(value, int) and not isinstance(value, bool)
                    },
                    "hash": e.hash,
                }
                for e in events
            ],
        }

    @app.exception_handler(ReportNotFoundError)
    async def not_found(request: Request, error: ReportNotFoundError) -> JSONResponse:
        return problem(404, "Report not found", detail="No data for this run id.")
