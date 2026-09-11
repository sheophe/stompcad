"""``stompcad``'s command line: the orchestrator's own surface.

Later tasks add the stages that actually run ``stompdrill`` and
``stompcollider``; this module holds the argument surface, target
validation and the exit convention every member shares (0 clean, 3 usage),
plus spec decision 9's fifth code, 130, for a run the user cancelled.
``_run`` is the seam later work attaches a real pipeline to; today it only
parses and validates ``--emit``, so ``Cancelled`` never fires outside a
test that drives the mapping directly.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from stompdrill.emitters import available
from stompmodel.diagnostics import EXIT_CLEAN, EXIT_USAGE
from stompmodel.errors import StompError

from .cancel import EXIT_CANCELLED, Cancelled
from .drive import _DOCK_TARGET_NAMES
from .present import NoTerminal

__all__ = ["UsageError", "build_parser", "parse_emit", "main"]


class UsageError(Exception):
    """A bad argument, or a target neither half can render. Exit 3.

    Stays a plain ``Exception`` rather than joining ``StompError``, the same
    choice stompdrill's own ``UsageError`` makes and for the same reason:
    it is caught beside, not through, the library faults ``_run`` may also
    raise.
    """


def build_parser() -> argparse.ArgumentParser:
    """The orchestrator's surface. Options arrive with the tasks that need them."""
    parser = argparse.ArgumentParser(prog="stompcad")
    parser.add_argument("panel", help="the Illustrator artwork to drill from")
    parser.add_argument(
        "--emit",
        metavar="FORMAT=PATH",
        action="append",
        default=[],
        help="write an artifact; repeatable. FORMAT is one of: " + ", ".join(sorted(_known_targets())),
    )
    return parser


def parse_emit(spec: str) -> tuple[str, Path]:
    """``"fmt=path"`` -> ``("fmt", Path("path"))``. The format is not checked here."""
    name, separator, path = spec.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise UsageError(f"--emit expects FORMAT=PATH, got {spec!r}")
    return (name.strip(), Path(path.strip()))


def _known_targets() -> frozenset[str]:
    """Every format either half can render -- the union the two write steps split."""
    return frozenset(available()) | _DOCK_TARGET_NAMES


def validate_targets(targets: Sequence[tuple[str, Path]]) -> None:
    """Reject every unknown ``--emit`` format together, before any file opens.

    CLAUDE.md: "Validate all requested targets together before rendering."
    ``_write_case`` and ``_write_dock`` each filter to the names their own
    half owns; those two sets are disjoint, so a name outside their union
    would otherwise be silently dropped rather than reported. Collecting
    every bad name here, rather than raising on the first, is what makes one
    round trip enough for a caller who mistyped more than one flag.
    """
    known = _known_targets()
    bad = sorted({name for name, _path in targets if name not in known})
    if bad:
        raise UsageError(
            f"--emit: unknown format(s) {', '.join(bad)}; available: {', '.join(sorted(known))}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for bad input."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help exits 0; argparse usage errors do not
        return EXIT_CLEAN if not exit_.code else EXIT_USAGE
    try:
        _run(args)
    except Cancelled:
        return EXIT_CANCELLED
    except (UsageError, NoTerminal, StompError, OSError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_CLEAN


def _run(args: argparse.Namespace) -> None:
    """Validate the requested targets. A later task drives ``Driver`` from here."""
    targets = [parse_emit(spec) for spec in args.emit]
    validate_targets(targets)
