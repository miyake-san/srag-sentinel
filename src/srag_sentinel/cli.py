"""Command line entry point (``srag-sentinel``)."""

import argparse
from collections.abc import Sequence

from srag_sentinel import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="srag-sentinel",
        description="Generate SRAG outbreak reports from OpenDATASUS metrics and news.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
