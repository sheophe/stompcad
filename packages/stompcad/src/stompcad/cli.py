"""``stompcad``'s command line: one composed run over both tools.

Resolves the arguments a run needs, validates every requested target
together, then drives ``Driver`` under ``track()`` with a presentation that
is also the sink -- the plain writer without a terminal, decision 11's
headless path, or the inline app's on a worker thread with one. The exit
convention is the four codes both tools share, reduced from the worse of the
two halves' findings, plus spec decision 9's fifth code, 130, for a run the
user cancelled.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO

from stompdrill.emitters import available
from stompmodel.diagnostics import EXIT_CLEAN, EXIT_USAGE, Severity, exit_for_severity
from stompmodel.errors import StompError
from stompmodel.progress import track
from stompmodel.protocols import check_target_set

from .cancel import EXIT_CANCELLED, Cancelled
from .drive import DOCK_TARGET_NAMES, Driver, RunOptions
from .inline import InlineApp, TerminalPresentation
from .plan import DRILL_AND_DOCK
from .present import NoTerminal, PlainWriter, Presentation

__all__ = [
    "UsageError",
    "build_parser",
    "parse_emit",
    "validate_targets",
    "resolve",
    "worst_severity",
    "choose_presentation",
    "main",
]


class UsageError(Exception):
    """A bad argument, or a target neither half can render. Exit 3.

    Stays a plain ``Exception`` rather than joining ``StompError``, the same
    choice stompdrill's own ``UsageError`` makes and for the same reason:
    it is caught beside, not through, the library faults ``_run`` may also
    raise.
    """


def build_parser() -> argparse.ArgumentParser:
    """The orchestrator's surface: one panel, any number of boards, the targets."""
    parser = argparse.ArgumentParser(
        prog="stompcad",
        description="Drill a panel and dock its boards inside the drilled case, in one run.",
    )
    parser.add_argument("panel", metavar="PANEL.ai", help="Illustrator file to read")
    parser.add_argument(
        "boards",
        metavar="BOARD.stp",
        nargs="*",
        help="board models to seat in the drilled case; docking is skipped with none",
    )
    parser.add_argument(
        "--case",
        metavar="PART",
        default=None,
        help="the catalogue base designator the panel is drawn for, e.g. 1590B",
    )
    parser.add_argument(
        "--case-model",
        metavar="PATH",
        default=None,
        help="a STEP model of the enclosure; required to dock a board "
        "(see tools/fetch_case_model.py)",
    )
    parser.add_argument(
        "--panel-reference",
        metavar="EXPR",
        default=None,
        help="which designators are panel references, e.g. 'RV*,SW*,D(3..4),!RV5'; "
        "required to dock a board, because a default would be a pedal-specific fact",
    )
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
    return frozenset(available()) | DOCK_TARGET_NAMES


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


def resolve(args: argparse.Namespace) -> RunOptions:
    """One run's inputs, with everything a command line can get wrong settled first.

    Both tools resolve their arguments before opening an input, and both
    refuse a target set two of whose members reach one file. Docking needs
    two facts nothing can supply on a run's behalf: the case the boards go
    into, and which designators are panel references. A run with no board
    needs neither, so neither is required until one is named.
    """
    targets = [parse_emit(spec) for spec in args.emit]
    validate_targets(targets)
    try:
        check_target_set([path for _name, path in targets])
    except ValueError as failure:
        raise UsageError(str(failure)) from failure
    boards = tuple(Path(board) for board in args.boards)
    if boards and args.panel_reference is None:
        raise UsageError(
            "--panel-reference is required to dock a board: it names the components "
            "chosen for this pedal, which no default can know"
        )
    if boards and args.case_model is None:
        raise UsageError("--case-model is required to dock a board: a board is seated in the case")
    return RunOptions(
        panel=Path(args.panel),
        boards=boards,
        case=args.case,
        case_model=None if args.case_model is None else Path(args.case_model),
        # Never parsed when no board is named: the dock half is the only
        # reader, and a run without one does not reach it.
        panel_reference=args.panel_reference or "",
        targets=tuple(targets),
    )


def worst_severity(severities: Iterable[Severity | None]) -> Severity | None:
    """The worse finding of the halves that ran -- one run reports one status."""
    found = [severity for severity in severities if severity is not None]
    return max(found) if found else None


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for bad input."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help exits 0; argparse usage errors do not
        return EXIT_CLEAN if not exit_.code else EXIT_USAGE
    try:
        return _run(args, sys.stdout)
    except Cancelled:
        return EXIT_CANCELLED
    except (UsageError, NoTerminal, StompError, OSError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return EXIT_USAGE


def choose_presentation(out: TextIO) -> bool:
    """Whether this stream can carry a drawn run rather than streamed lines.

    Decision 11: a pipe, a dumb terminal or a CI runner gets the plain
    writer -- the same step lines, without the drawing. ``TERM=dumb``
    cannot address a cursor, so an inline app would corrupt what it wrote.
    """
    return out.isatty() and os.environ.get("TERM", "") not in ("", "dumb")


def _run(args: argparse.Namespace, out: TextIO) -> int:
    """Drive one composed run, and return the exit code its findings earned.

    The presentation is also the sink ``track`` folds positions into, the
    same double duty either writer does. With a terminal the run happens on
    a worker and the app owns the main thread; without one it happens right
    here, and decision 2's step lines are the whole record either way.
    """
    options = resolve(args)
    if not choose_presentation(out):
        return _compose(options, PlainWriter(out))
    app = InlineApp()
    app.drive(lambda: _compose(options, TerminalPresentation(app)))
    return app.run(inline=True, inline_no_clear=True) or EXIT_CLEAN


def _compose(options: RunOptions, presentation: Presentation) -> int:
    """One run, against whichever presentation is drawing it."""
    driver = Driver(DRILL_AND_DOCK, presentation, options)
    with track(presentation) as scope:
        drill, dock = driver.run(scope)
    return exit_for_severity(
        worst_severity([drill.worst_severity, None if dock is None else dock.worst_severity])
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
