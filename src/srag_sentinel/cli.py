"""Command line entry point (``srag-sentinel``)."""

import argparse
import asyncio
from collections.abc import Sequence

from srag_sentinel import __version__
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

    parser.print_help()
    return 0


def _db_init() -> int:
    try:
        asyncio.run(init_database(get_settings()))
    except SchemaInitError as error:
        print(f"error: {error}")
        return 2
    print("database initialised")
    return 0
