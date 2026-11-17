"""Composition root: wires settings into a ready-to-run report service.

One :class:`ReportService` per process. It owns the database connections (each with the least
privileged account for its job), the model tiers, the news providers and the report store, and it
builds a fresh :class:`AgentDeps` (recorder, router, budget) for every run.
"""

import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from surrealdb import AsyncSurrealConnection

from srag_sentinel.agent.deps import AgentDeps, KgConfig
from srag_sentinel.agent.graph import run_report
from srag_sentinel.agent.state import ReportState
from srag_sentinel.agent.validators import report_validators
from srag_sentinel.data.repository import SurrealCountersReader
from srag_sentinel.db.client import open_connection
from srag_sentinel.governance.model import AuditEvent
from srag_sentinel.governance.recorder import AuditRecorder
from srag_sentinel.governance.store import AuditStore, SurrealAuditStore
from srag_sentinel.guardrails.budget import BudgetLimits, RunBudget
from srag_sentinel.kg.retrieve import GraphRetriever
from srag_sentinel.kg.store import SurrealKgStore
from srag_sentinel.llm.factory import LLMConfigError, build_large_model, build_structured_model
from srag_sentinel.llm.ports import StructuredModel
from srag_sentinel.llm.router.cascade import Router
from srag_sentinel.llm.router.judge import LlmJudge
from srag_sentinel.llm.router.policy import load_default_policy
from srag_sentinel.news.cache import CachedNewsProvider, MemoryNewsCache
from srag_sentinel.news.chain import ChainedNewsProvider
from srag_sentinel.news.gdelt import GdeltProvider
from srag_sentinel.news.rss import GoogleNewsRssProvider
from srag_sentinel.observability.telemetry import Telemetry
from srag_sentinel.reporting.bundle import ReportBundle, build_bundle, write_bundle
from srag_sentinel.settings import Settings

RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FORMATS = {"json": "report.json", "html": "report.html", "pdf": "report.pdf"}


class ReportNotFoundError(LookupError):
    """No stored report for the requested run id."""


@dataclass(frozen=True)
class RunResult:
    """Outcome of one run: the graph state and the files that were written."""

    run_id: str
    state: ReportState
    files: dict[str, Path]

    @property
    def rejected(self) -> bool:
        """Whether the request was refused by the input guardrail."""
        return self.state.rejected

    @property
    def status(self) -> str:
        """``ok``, ``degraded`` or ``rejected``."""
        if self.state.rejected:
            return "rejected"
        return self.state.report.status if self.state.report else "failed"


def _db(settings: Settings, database: str, auth: dict[str, Any]) -> Any:
    return open_connection(
        settings.surreal_url,
        auth={"namespace": settings.surreal_namespace, "database": database, **auth},
        namespace=settings.surreal_namespace,
        database=database,
    )


class ReportService:
    """Runs reports and serves the stored artifacts."""

    def __init__(  # noqa: PLR0913 - optional collaborators, injectable for tests
        self,
        settings: Settings,
        *,
        large: StructuredModel | None = None,
        small: StructuredModel | None = None,
        judge: StructuredModel | None = None,
        news: ChainedNewsProvider | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._settings = settings
        self._telemetry = telemetry or Telemetry()
        self._large = large
        self._small = small
        self._judge_model = judge
        self._news = news
        self._stack = AsyncExitStack()
        self._reader: SurrealCountersReader | None = None
        self._audit_writer: AuditStore | None = None
        self._audit_reader: AuditStore | None = None
        self._kg: KgConfig | None = None
        self._models: dict[str, StructuredModel] = {}

    # -- lifecycle -------------------------------------------------------------------------

    async def start(self) -> None:
        """Open connections and build the model tiers (fails fast on bad configuration)."""
        settings = self._settings
        ro = {
            "username": settings.surreal_api_ro_user,
            "password": settings.surreal_api_ro_password.get_secret_value(),
        }
        data = await self._stack.enter_async_context(
            _db(settings, settings.surreal_data_database, ro)
        )
        self._reader = SurrealCountersReader(data)
        writer = await self._stack.enter_async_context(
            _db(
                settings,
                settings.surreal_audit_database,
                {
                    "access": "audit_writer",
                    "variables": {
                        "name": settings.surreal_audit_writer_name,
                        "pass": settings.surreal_audit_writer_password.get_secret_value(),
                    },
                },
            )
        )
        self._audit_writer = SurrealAuditStore(writer)
        reader = await self._stack.enter_async_context(
            _db(
                settings,
                settings.surreal_audit_database,
                {
                    "username": settings.surreal_audit_reader_user,
                    "password": settings.surreal_audit_reader_password.get_secret_value(),
                },
            )
        )
        self._audit_reader = SurrealAuditStore(reader)
        if settings.kg_enabled:
            await self._start_kg(ro)

        if self._large is None:
            self._large = build_large_model(settings)
        self._models = {"large": self._large}
        if self._small is None and settings.router_small_provider and settings.router_small_model:
            self._small = build_structured_model(
                settings,
                provider=settings.router_small_provider,
                model=settings.router_small_model,
            )
        if self._small is not None:
            self._models["small"] = self._small
        if self._judge_model is None:
            self._judge_model = self._build_judge(settings)
        if self._news is None:
            client = await self._stack.enter_async_context(
                httpx.AsyncClient(follow_redirects=False)
            )
            cache = MemoryNewsCache()
            self._news = ChainedNewsProvider(
                [
                    CachedNewsProvider(GoogleNewsRssProvider(client), cache),
                    CachedNewsProvider(GdeltProvider(client), cache),
                ]
            )
        self._settings.reports_dir.mkdir(parents=True, exist_ok=True)

    def _build_judge(self, settings: Settings) -> StructuredModel:
        if settings.router_judge_provider and settings.router_judge_model:
            return build_structured_model(
                settings,
                provider=settings.router_judge_provider,
                model=settings.router_judge_model,
            )
        assert self._large is not None  # noqa: S101 - set just above
        return self._large  # no dedicated judge: the main model judges (spec 08 §2)

    async def _start_kg(self, ro: dict[str, str]) -> None:
        settings = self._settings
        write: AsyncSurrealConnection = await self._stack.enter_async_context(
            _db(
                settings,
                settings.surreal_kg_database,
                {
                    "username": settings.surreal_kg_writer_user,
                    "password": settings.surreal_kg_writer_password.get_secret_value(),
                },
            )
        )
        read: AsyncSurrealConnection = await self._stack.enter_async_context(
            _db(settings, settings.surreal_kg_database, ro)
        )
        self._kg = KgConfig(
            store=SurrealKgStore(write),
            retriever=GraphRetriever(read),
            top_k=settings.kg_top_k,
            max_hops=settings.kg_max_hops,
            ttl_days=settings.kg_claim_ttl_days,
        )

    async def stop(self) -> None:
        """Close every connection."""
        await self._stack.aclose()

    # -- operations ------------------------------------------------------------------------

    async def ready(self) -> bool:
        """Whether the database answers and holds SRAG data."""
        if self._reader is None:
            return False
        try:
            return await self._reader.latest_day() is not None
        except Exception:
            return False

    async def generate(self, raw_request: dict[str, Any]) -> RunResult:
        """Run one report, render and store its artifacts, and return the outcome."""
        assert self._reader and self._audit_writer and self._news and self._judge_model  # noqa: S101
        run_id = str(uuid4())
        recorder = AuditRecorder(run_id, self._audit_writer, telemetry=self._telemetry)
        router = Router(
            load_default_policy(),
            models=self._models,  # type: ignore[arg-type]
            validators=report_validators(),
            judge=LlmJudge(self._judge_model),
            sink=recorder.router_sink(),
        )
        deps = AgentDeps(
            reader=self._reader,
            news=self._news,
            router=router,
            recorder=recorder,
            budget=RunBudget(BudgetLimits()),
            models={tier: model.name for tier, model in self._models.items()},
            kg=self._kg,
            telemetry=self._telemetry,
            bundler=build_bundle,
            clock=lambda: datetime.now(UTC),
        )
        state = await run_report(deps, raw_request, run_id=run_id)
        files = self._store(run_id, state.bundle)
        return RunResult(run_id=run_id, state=state, files=files)

    def _store(self, run_id: str, bundle: ReportBundle | None) -> dict[str, Path]:
        if bundle is None:
            return {}
        return write_bundle(bundle, self._settings.reports_dir / run_id)

    def artifact(self, run_id: str, fmt: str) -> Path:
        """Path of a stored artifact; raises :class:`ReportNotFoundError` when it is missing."""
        name = FORMATS.get(fmt)
        if name is None or not RUN_ID.fullmatch(run_id):
            raise ReportNotFoundError(run_id)
        path = self._settings.reports_dir / run_id / name
        if not path.is_file():
            raise ReportNotFoundError(run_id)
        return path

    async def audit_events(self, run_id: str) -> list[AuditEvent]:
        """The audit events of one run (hashes and scalar details only)."""
        if self._audit_reader is None or not RUN_ID.fullmatch(run_id):
            return []
        return [e for e in await self._audit_reader.read_all() if e.run_id == run_id]


__all__ = ["LLMConfigError", "ReportNotFoundError", "ReportService", "RunResult"]
