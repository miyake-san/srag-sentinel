"""Command line entry point (``srag-sentinel``)."""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from srag_sentinel import __version__
from srag_sentinel.data.ingest.discovery import SourceDiscoveryError
from srag_sentinel.data.ingest.pipeline import IngestManifest
from srag_sentinel.data.ingest.service import ingest, resolve_sources
from srag_sentinel.data.ingest.transform import SchemaMismatchError
from srag_sentinel.db.init import SchemaInitError, init_database
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

    db = commands.add_parser("db", help="database administration")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="create namespace, databases, schema and role users")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "db" and args.db_command == "init":
        return _db_init()
    if args.command == "ingest":
        return _ingest(years=args.years, urls=args.url)

    parser.print_help()
    return 0


def _ingest(*, years: list[int] | None, urls: list[str] | None) -> int:
    async def _run() -> IngestManifest:
        settings = get_settings()
        sources = urls or await resolve_sources(years or default_years())
        return await ingest(settings, sources)

    try:
        manifest = asyncio.run(_run())
    except (SourceDiscoveryError, SchemaMismatchError) as error:
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
