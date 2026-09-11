"""``stompcad``'s command line: the orchestrator's own surface.

Later tasks add the stages that actually run ``stompdrill`` and
``stompcollider``; this module holds only the argument surface and the exit
convention every member shares (0 clean, 3 usage), so those tasks have
somewhere to attach their options.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from stompmodel.diagnostics import EXIT_CLEAN, EXIT_USAGE

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """The orchestrator's surface. Options arrive with the tasks that need them."""
    parser = argparse.ArgumentParser(prog="stompcad")
    parser.add_argument("panel", help="the Illustrator artwork to drill from")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for bad input."""
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exit_:  # --help exits 0; argparse usage errors do not
        return EXIT_CLEAN if not exit_.code else EXIT_USAGE
    return EXIT_CLEAN
