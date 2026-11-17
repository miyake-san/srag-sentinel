"""Measure what the solution does on real data, without any LLM (reproducible, no API key).

    SURREAL_ROOT_PASSWORD=<pw> uv run python scripts/measure_impact.py [--runs 20] [--json out.json]

What is measured: data minimisation of the ingestion, latency of the deterministic parts (metrics,
series, rendering, audit), the size of the artifacts and the audit trail per run. What is NOT
measured here: LLM latency, cost and text quality (they need a model), and any comparison with
manual work. The report runs are *degraded* on purpose: a model that always fails exercises the
whole graph except the LLM, so the numbers are the orchestration overhead, not the real
end-to-end time.
"""

import argparse
import asyncio
import json
import os
import secrets
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from srag_sentinel.agent.tools.metrics import ScopeArgs
from srag_sentinel.agent.tools.runner import load_metrics_and_series
from srag_sentinel.cli import default_years
from srag_sentinel.data.ingest.service import ingest, resolve_sources
from srag_sentinel.db.client import open_connection, rows, run
from srag_sentinel.db.init import init_database
from srag_sentinel.governance.chain import verify_chain
from srag_sentinel.governance.service import read_chain
from srag_sentinel.llm.ports import ModelError, T
from srag_sentinel.news.chain import ChainedNewsProvider
from srag_sentinel.news.fake import FakeNewsProvider
from srag_sentinel.service import ReportService
from srag_sentinel.settings import Settings


class DownModel:
    """A model that always fails: runs the whole graph except the LLM (degraded report)."""

    name = "fake:down"

    async def invoke_structured(self, schema: type[T], *, system: str, user: str) -> T:
        raise ModelError("no model in the measurement")


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))]


def summary(values: list[float]) -> dict[str, float]:
    """p50/p95/max of a sample."""
    return {
        "n": len(values),
        "p50": round(percentile(values, 0.5), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.fmean(values), 3),
    }


async def measure(runs: int) -> dict[str, Any]:
    root_password = os.environ["SURREAL_ROOT_PASSWORD"]
    namespace = f"impact_{secrets.token_hex(4)}"

    def secret() -> Any:
        return secrets.token_urlsafe(12)

    with TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            surreal_namespace=namespace,
            surreal_root_password=root_password,  # type: ignore[arg-type]
            surreal_ingest_password=secret(),
            surreal_api_ro_password=secret(),
            surreal_api_rw_password=secret(),
            surreal_audit_writer_password=secret(),
            surreal_audit_reader_password=secret(),
            surreal_kg_writer_password=secret(),
            reports_dir=Path(tmp),
        )
        try:
            await init_database(settings)
            started = time.monotonic()
            manifest = await ingest(settings, await resolve_sources(default_years()))
            ingest_seconds = time.monotonic() - started

            root = {"username": "root", "password": root_password}
            async with open_connection(
                settings.surreal_url,
                auth=root,
                namespace=namespace,
                database=settings.surreal_data_database,
            ) as db:
                stored = (await rows(db, "SELECT count() AS n FROM srag_daily GROUP ALL"))[0]["n"]

            tools: dict[str, list[float]] = {"BR": [], "SP": []}
            for scope, samples in tools.items():
                for _ in range(runs):
                    began = time.monotonic()
                    await load_metrics_and_series(settings, ScopeArgs(uf=scope))
                    samples.append(time.monotonic() - began)

            service = ReportService(
                settings,
                large=DownModel(),
                judge=DownModel(),
                news=ChainedNewsProvider([FakeNewsProvider([])]),
            )
            await service.start()
            durations: list[float] = []
            sizes: dict[str, int] = {}
            run_id = ""
            try:
                for _ in range(runs):
                    began = time.monotonic()
                    result = await service.generate({"uf": "BR"})
                    durations.append(time.monotonic() - began)
                    run_id = result.run_id
                    sizes = {fmt: path.stat().st_size for fmt, path in result.files.items()}
                events_last = len(await service.audit_events(run_id))
            finally:
                await service.stop()

            began = time.monotonic()
            chain = await read_chain(settings)
            verified = verify_chain(chain)
            verify_seconds = time.monotonic() - began
            return {
                "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "ingestion": {
                    "rows_read": manifest.rows_read,
                    "rows_kept": manifest.rows_kept,
                    "daily_counter_rows_stored": stored,
                    "reduction_factor": round(manifest.rows_read / stored, 1),
                    "seconds": round(ingest_seconds, 1),
                    "sources": len(manifest.source_urls),
                },
                "metrics_and_series_seconds": {k: summary(v) for k, v in tools.items()},
                "report_without_llm_seconds": summary(durations),
                "artifact_bytes": sizes,
                "audit": {
                    "events_in_last_run": events_last,
                    "events_total": len(chain),
                    "chain_verified": verified.ok,
                    "read_and_verify_seconds": round(verify_seconds, 3),
                },
            }
        finally:
            async with open_connection(settings.surreal_url, auth=root) as admin:
                await run(admin, f"REMOVE NAMESPACE IF EXISTS {namespace};")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args()
    results = asyncio.run(measure(args.runs))
    text = json.dumps(results, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
