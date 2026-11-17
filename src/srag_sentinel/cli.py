"""Command line entry point (``srag-sentinel``)."""

import argparse
import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import ValidationError

from srag_sentinel import __version__
from srag_sentinel.agent.tools.metrics import DEFAULT_SETTLE_DAYS, NoDataError, ScopeArgs
from srag_sentinel.agent.tools.runner import load_metrics_and_series
from srag_sentinel.data.ingest.discovery import SourceDiscoveryError
from srag_sentinel.data.ingest.pipeline import IngestManifest
from srag_sentinel.data.ingest.service import PartialIngestError, ingest, resolve_sources
from srag_sentinel.data.ingest.transform import SchemaMismatchError
from srag_sentinel.db.init import SchemaInitError, init_database
from srag_sentinel.governance.service import export_jsonl, read_chain, verify
from srag_sentinel.reporting.text import format_metrics, format_series
from srag_sentinel.settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="srag-sentinel",
        description="Generate SRAG outbreak reports from OpenDATASUS metrics and news.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    ingest = commands.add_parser("ingest", help="load OpenDATASUS SRAG data into daily aggregates")
    ingest.add_argument(
        "--years",
        type=int,
        nargs="+",
        help="epidemiological years to load (default: previous and current year)",
    )
    ingest.add_argument(
        "--url",
        action="append",
        help="explicit Parquet URL or path (repeatable); skips portal discovery",
    )
    ingest.add_argument(
        "--allow-partial",
        action="store_true",
        help="accept a single yearly file (days spanning files may be understated)",
    )

    metrics = commands.add_parser("metrics", help="print the SRAG metrics and chart series")
    metrics.add_argument("--uf", default="BR", help="'BR' (default) or a UF code such as SP")
    metrics.add_argument("--as-of", type=date.fromisoformat, help="YYYY-MM-DD (default: latest)")
    metrics.add_argument("--window-days", type=int, default=30, help="window length, 7-90")
    metrics.add_argument(
        "--settle-days",
        type=int,
        default=DEFAULT_SETTLE_DAYS,
        help="newest days to leave out when --as-of is not given (notification lag)",
    )

    report = commands.add_parser("report", help="generate a report (HTML, JSON and PDF)")
    report.add_argument("--uf", default="BR", help="'BR' (default) or a UF code such as SP")
    report.add_argument("--as-of", type=date.fromisoformat, help="YYYY-MM-DD (default: latest)")
    report.add_argument("--window-days", type=int, default=30, help="window length, 7-90")

    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    audit = commands.add_parser("audit", help="audit trail operations")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    verify_cmd = audit_commands.add_parser("verify", help="verify the audit hash chain")
    verify_cmd.add_argument("--expected-head", help="head hash kept outside the database")
    export_cmd = audit_commands.add_parser("export", help="export the audit chain as JSONL")
    export_cmd.add_argument("--out", type=Path, required=True, help="target .jsonl file")

    db = commands.add_parser("db", help="database administration")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="create namespace, databases, schema and role users")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers: dict[str, Callable[[], int]] = {
        "db": _db_init,
        "audit": lambda: _audit(args),
        "serve": lambda: _serve(host=args.host, port=args.port),
        "report": lambda: _report(uf=args.uf, as_of=args.as_of, window_days=args.window_days),
        "ingest": lambda: _ingest(
            years=args.years, urls=args.url, allow_partial=args.allow_partial
        ),
        "metrics": lambda: _metrics(
            uf=args.uf,
            as_of=args.as_of,
            window_days=args.window_days,
            settle_days=args.settle_days,
        ),
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 0
    return handler()


def _audit(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.audit_command == "export":
        events = asyncio.run(read_chain(settings))
        head = export_jsonl(events, args.out)
        print(f"exported {len(events)} events to {args.out}; head {head}")
        return 0
    result = asyncio.run(verify(settings, expected_head=args.expected_head))
    if result.ok:
        print(f"audit chain ok: {result.checked} events, head {result.head_hash}")
        return 0
    print(f"AUDIT CHAIN BROKEN at seq {result.failed_seq}: {result.reason}")
    return 1


def _serve(*, host: str, port: int) -> int:
    import uvicorn  # noqa: PLC0415 - only the serve command needs the server

    from srag_sentinel.api.app import create_app  # noqa: PLC0415

    uvicorn.run(create_app(), host=host, port=port, log_config=None)
    return 0


def _report(*, uf: str, as_of: date | None, window_days: int) -> int:
    from srag_sentinel.llm.factory import LLMConfigError  # noqa: PLC0415
    from srag_sentinel.service import ReportService  # noqa: PLC0415

    async def _run() -> int:
        service = ReportService(get_settings())
        await service.start()
        try:
            request: dict[str, object] = {"uf": uf, "window_days": window_days}
            if as_of is not None:
                request["as_of"] = as_of.isoformat()
            result = await service.generate(request)
        finally:
            await service.stop()
        if result.rejected:
            print(f"error: request rejected by the input guardrail (run {result.run_id})")
            return 2
        print(f"run {result.run_id}: {result.status}")
        for fmt, path in result.files.items():
            print(f"  {fmt}: {path}")
        return 0

    try:
        return asyncio.run(_run())
    except LLMConfigError as error:
        print(f"error: {error}")
        return 2


def _metrics(*, uf: str, as_of: date | None, window_days: int, settle_days: int) -> int:
    try:
        scope = ScopeArgs(uf=uf, as_of=as_of, window_days=window_days, settle_days=settle_days)
        metrics, series = asyncio.run(load_metrics_and_series(get_settings(), scope))
    except (ValidationError, ValueError, NoDataError) as error:
        print(f"error: {error}")
        return 2
    print(format_metrics(metrics))
    print(format_series(series))
    return 0


def _ingest(*, years: list[int] | None, urls: list[str] | None, allow_partial: bool) -> int:
    async def _run() -> IngestManifest:
        settings = get_settings()
        sources = urls or await resolve_sources(years or default_years())
        return await ingest(settings, sources, allow_partial=allow_partial)

    try:
        manifest = asyncio.run(_run())
    except (SourceDiscoveryError, SchemaMismatchError, PartialIngestError) as error:
        print(f"error: {error}")
        return 2
    print(
        f"ingested {manifest.rows_kept}/{manifest.rows_read} rows from "
        f"{len(manifest.source_urls)} source(s); snapshot {manifest.snapshot_sha256[:12]}"
    )
    return 0


def default_years() -> list[int]:
    """Previous and current calendar year (covers the 12-month window)."""
    current = datetime.now(UTC).year
    return [current - 1, current]


def _db_init() -> int:
    try:
        asyncio.run(init_database(get_settings()))
    except SchemaInitError as error:
        print(f"error: {error}")
        return 2
    print("database initialised")
    return 0
