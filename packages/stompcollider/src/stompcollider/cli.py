"""``stompcollider``'s command line: seat every board, and say what clashes.

Stage order belongs to :func:`build_pipeline` -- match, then seat, then
clashes -- because no stage may assert another ran first. Exit codes are 0
clean, 1 findings, 2 errors, 3 usage or IO. There is no ``--case-face``: the
drill document carries the face frame ``stompdrill`` cut in, so this tool
reads that registration and checks against every solid of the case model.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from stompgeom.errors import StompgeomError
from stompgeom.kernel import KernelUnavailable
from stompgeom.step import StepSolid
from stompmodel.diagnostics import (
    EXIT_CLEAN,
    EXIT_ERRORS,
    EXIT_USAGE,
    Diagnostic,
    Severity,
    exit_for_severity,
)
from stompmodel.errors import StompError
from stompmodel.model import CaseRegistration
from stompmodel.protocols import (
    Emitter,
    Pipeline,
    Stage,
    check_target_set,
    commit_all,
    stage_all,
)
from stompmodel.units import Nanometre, format_nm, nm_from_mm

from .canonicalise import board_order, canonicalise
from .clash import Clashes
from .designators import Filter, parse_filter
from .emitters import AssemblyEmitter, ReportEmitter
from .emitters.assembly import Solids
from .errors import UsageError
from .match import Match
from .model import DockData, Placement
from .seat import Seat
from .sources import BoardGeometry, BoardScan, BoardSource

__all__ = [
    "main",
    "build_parser",
    "build_pipeline",
    "parse_targets",
    "parse_length",
    "parse_place",
    "parse_pin",
    "admit",
    "board_geometry",
]

#: The two fixed artefacts, named where the flags that request them are.
#: There is no registry: a two-element set does not earn one.
_REPORT = "report"
_ASSEMBLY = "assembly"

#: Severities in the order the report groups them: worst first.
_SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)

#: Width of the report's label column.
_LABEL = 15


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the parser. Every flag here resolves before any file is opened."""
    parser = argparse.ArgumentParser(
        prog="stompcollider",
        description="Seat PCB models inside a drilled case and report where they clash.",
    )
    parser.add_argument(
        "drill", metavar="DRILL.json", help="the drill document the case was cut from"
    )
    parser.add_argument(
        "boards", metavar="BOARD.stp", nargs="+", help="the board models to seat"
    )
    parser.add_argument(
        "--case-model", metavar="PATH", required=True, help="the drilled case model"
    )
    parser.add_argument(
        "--panel-reference",
        metavar="EXPR",
        required=True,
        help="which designators are panel references, e.g. 'RV*,SW*,D(3..4),!RV5'; "
        "required, because a default would be a pedal-specific fact",
    )
    parser.add_argument(
        "--match-tolerance",
        metavar="MM",
        required=True,
        help="recognition tolerance in millimetres: half the drill grid pitch",
    )
    parser.add_argument(
        "--place",
        metavar="N=X,Y,THETA",
        action="append",
        default=[],
        help="place board N explicitly, in millimetres and degrees; repeatable. "
        "Refused by this build: nothing downstream places a board explicitly",
    )
    parser.add_argument(
        "--pin",
        metavar="N=RANK",
        action="append",
        default=[],
        help="choose among board N's ranked placements; repeatable. Refused by "
        "this build: placements are ranked after their clashes are known",
    )
    parser.add_argument("--report", metavar="PATH", default=None, help="write the dock report")
    parser.add_argument(
        "--assembly", metavar="PATH", default=None, help="write the assembly model"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show what each pipeline stage did"
    )
    return parser


def parse_targets(args: argparse.Namespace) -> list[tuple[str, Path]]:
    """The artefacts this run was asked for, as a set to be checked as one.

    Named here rather than resolved through a registry: two fixed outputs
    are the whole set, and it is that set ``check_target_set`` is asked
    about before anything is rendered.
    """
    requested = ((_REPORT, args.report), (_ASSEMBLY, args.assembly))
    return [(name, Path(value)) for name, value in requested if value is not None]


def parse_length(text: str, flag: str) -> Nanometre:
    """A positive, finite millimetre value from the command line, in nanometres."""
    try:
        millimetres = float(text)
    except ValueError:
        raise UsageError(f"{flag} expects a number of millimetres, got {text!r}") from None
    if not math.isfinite(millimetres) or millimetres <= 0:
        raise UsageError(f"{flag} must be a positive, finite number of millimetres, got {text!r}")
    return nm_from_mm(millimetres)


def _ordinal_and_rest(spec: str, flag: str, shape: str) -> tuple[int, str]:
    """``"N=REST"`` split, refusing an ordinal no board could ever carry."""
    ordinal_text, separator, rest = spec.partition("=")
    if not separator or not rest.strip():
        raise UsageError(f"{flag} expects {shape}, got {spec!r}")
    try:
        ordinal = int(ordinal_text.strip())
    except ValueError:
        raise UsageError(f"{flag} expects {shape}, got {spec!r}") from None
    if ordinal < 1:
        raise UsageError(
            f"{flag} {spec!r}: boards are numbered from 1, so board {ordinal} can never exist"
        )
    return ordinal, rest.strip()


def parse_place(spec: str) -> tuple[int, tuple[float, float, float]]:
    """``"N=X,Y,THETA"`` -> the board's ordinal and its explicit placement."""
    ordinal, rest = _ordinal_and_rest(spec, "--place", "N=X,Y,THETA")
    fields = [field.strip() for field in rest.split(",")]
    if len(fields) != 3:
        raise UsageError(f"--place expects N=X,Y,THETA, got {spec!r}")
    try:
        placement = tuple(float(field) for field in fields)
    except ValueError:
        raise UsageError(f"--place expects N=X,Y,THETA in millimetres, got {spec!r}") from None
    if not all(math.isfinite(value) for value in placement):
        raise UsageError(f"--place needs finite values, got {spec!r}")
    return ordinal, (placement[0], placement[1], placement[2])


def parse_pin(spec: str) -> tuple[int, int]:
    """``"N=RANK"`` -> the board's ordinal and the placement rank chosen."""
    ordinal, rest = _ordinal_and_rest(spec, "--pin", "N=RANK")
    try:
        rank = int(rest)
    except ValueError:
        raise UsageError(f"--pin expects N=RANK, got {spec!r}") from None
    if rank < 1:
        raise UsageError(f"--pin {spec!r}: placements are ranked from 1, not {rank}")
    return ordinal, rank


def _refuse_unhonoured(args: argparse.Namespace) -> None:
    """Refuse the two flags nothing downstream can act on, having parsed them.

    An accepted flag that changed nothing would be the worse failure: the
    operator would read back a placement they never got. Placing a board
    explicitly needs a stage no package here owns, and a pinned rank cannot
    survive ``Clashes``, which re-ranks once every placement's clashes are
    known. Both are parsed and validated first, so a bad ordinal is still
    reported as the bad ordinal it is.
    """
    for spec in args.place:
        parse_place(spec)
    for spec in args.pin:
        parse_pin(spec)
    if args.place:
        raise UsageError(
            "--place is understood but not honoured by this build: no stage places a "
            "board explicitly, so an under-constrained board reaches no artefact at all"
        )
    if args.pin:
        raise UsageError(
            "--pin is understood but not honoured by this build: placements are ranked "
            "after their clashes are known, so nothing here could hold a pinned rank"
        )


# ---------------------------------------------------------------------------
# building the run
# ---------------------------------------------------------------------------


def build_pipeline(
    tolerance_nm: Nanometre,
    case_solids: Sequence[StepSolid],
    board_solids: dict[int, tuple[StepSolid, ...]],
) -> Pipeline[DockData]:
    """Match, then seat, then clashes: the one statement of this order.

    Matching decides which face points at the panel and which holes each
    protrusion pairs with; seating reduces those correspondences to a
    depth; clashes need a seated placement to check. No stage asserts that
    another ran, which is why the order lives here and not in a stage.
    """
    return Pipeline([Match(tolerance_nm), Seat(), Clashes(case_solids, board_solids)])


def board_geometry(scan: BoardScan, case: CaseRegistration) -> dict[int, BoardGeometry]:
    """Each board's ordinal paired with the solids that board was measured from.

    The ordinal comes from ``canonicalise``'s own ordering rule, read
    through :func:`~stompcollider.canonicalise.board_order` rather than
    restated: a second statement of it here would pair a board with another
    board's geometry the day either copy changed.
    """
    order = board_order(scan.raw.boards, case.frame.basis)
    return {ordinal: scan.geometry[index] for ordinal, index in enumerate(order, start=1)}


def _registration(scan: BoardScan, path: Path) -> CaseRegistration:
    """The face frame the drill document registered, never a face chosen here.

    A document that registered no case model carries no frame, and
    inventing one would seat every board somewhere plausible and wrong.
    """
    case = scan.drill.case
    if case is None:
        raise UsageError(
            f"{path}: this drill document registers no case model, so it carries no "
            f"face frame to dock against"
        )
    return case


def _docked(scan: BoardScan, case: CaseRegistration) -> DockData:
    """Canonicalise the measurements, then give them the document's own holes.

    Every hole arrives numbered or not at all: ``stompmodel``'s codec
    refuses a document holding a hole with no drill number, so nothing is
    re-checked here -- ``DockData`` states the same requirement and would
    have no better answer than the reader's own.
    """
    return replace(canonicalise(scan.raw, case), holes=scan.drill.holes)


def admit(data: DockData, panel_reference: Filter) -> DockData:
    """Withhold the protrusion of every component the filter does not admit.

    Withheld rather than dropped: a part the expression passes over is
    still the board's, still named in the report and still a solid the
    clash check must place. Only ``Match`` reads a protrusion, so having
    none is exactly "this part is not a panel reference". A board the
    expression admits nothing of earns ``empty-group`` -- a flag that does
    not fit this board, which is a finding and not a parse failure.
    """
    admitted = panel_reference.admit(
        designator for board in data.boards for designator in board.designators
    )
    boards = []
    diagnostics = []
    for board in data.boards:
        boards.append(
            replace(
                board,
                components=tuple(
                    component
                    if component.designator in admitted
                    else replace(component, protrusion=None)
                    for component in board.components
                ),
            )
        )
        if not admitted.intersection(board.designators):
            diagnostics.append(
                Diagnostic.error(
                    "empty-group",
                    f"board {board.ordinal}: the panel-reference expression admits none "
                    f"of its designators",
                    data=(("board", board.ordinal),),
                )
            )
    return replace(data, boards=tuple(boards)).with_diagnostics(*diagnostics)


def _emitters(
    targets: Iterable[tuple[str, Path]], scan: BoardScan, geometry: dict[int, BoardGeometry]
) -> list[tuple[Emitter[DockData], Path]]:
    """One emitter per requested target, each given the geometry it writes.

    The assembly's timestamp is the case model's own, never a clock
    reading: two runs over one input must agree byte for byte (ADR-0006),
    and the case model is the input that carries a time at all.
    """
    case = Solids(scan.case.document, scan.case.solids)
    boards = {
        ordinal: Solids(board.document.document, board.solids)
        for ordinal, board in geometry.items()
    }
    built: list[tuple[Emitter[DockData], Path]] = []
    for name, path in targets:
        if name == _REPORT:
            built.append((ReportEmitter(), path))
        else:
            built.append((AssemblyEmitter(case, boards, timestamp=scan.case.timestamp), path))
    return built


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def _write(emitters: Sequence[tuple[Emitter[DockData], Path]], data: DockData) -> list[str]:
    """Render every artefact, then stage every one, then commit every one.

    Every payload is rendered before any target is touched. Neither loop
    below is this file's own: staging and the whole-set transaction are
    ``stompmodel``'s, and this keeps only the sentence it prints from the
    count each commit returned -- see ADR-0001 and ADR-0005.
    """
    rendered = [(emitter, path, emitter.emit(data)) for emitter, path in emitters]
    staged = stage_all([(path, payload) for _emitter, path, payload in rendered])
    sizes = commit_all(staged)
    return [
        f"wrote {written.path}  ({emitter.name}, {size} bytes)"
        for (emitter, _path, _payload), written, size in zip(
            rendered, staged, sizes, strict=True
        )
    ]


def _withheld(targets: Iterable[tuple[str, Path]]) -> list[str]:
    """Name every target withheld because errors make output unsafe."""
    return ["wrote nothing: this run has errors, so these were not written:"] + [
        f"  {path}  ({name})" for name, path in targets
    ]


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def _field(label: str, value: str) -> str:
    return f"  {label:<{_LABEL}}{value}"


def format_case(data: DockData) -> list[str]:
    """The case this run docked against, read from the drill document."""
    case = data.case
    return [
        "CASE",
        _field("part", f"{case.part}  ({case.face.value})"),
        _field("model", case.model),
    ]


def format_boards(data: DockData) -> list[str]:
    """Each board, its designators, and every placement found for it."""
    lines = ["", f"BOARDS ({len(data.boards)})"]
    if not data.boards:
        lines.append("  (none)")
    for board in data.boards:
        placements = sorted(data.placements.get(board.ordinal, ()), key=lambda p: p.rank)
        lines.append(
            _field(
                f"#{board.ordinal}",
                f"{', '.join(board.designators)}   face {board.panel_face or '(unresolved)'}"
                f"   {len(placements)} placement(s)",
            )
        )
        lines.extend(_placement_line(placement) for placement in placements)
    return lines


def _placement_line(placement: Placement) -> str:
    """One placement: where it puts the board, and what it found there."""
    return (
        f"      rank {placement.rank}   "
        f"x {format_nm(placement.x_nm)} mm  "
        f"y {format_nm(placement.y_nm)} mm  "
        f"z {format_nm(placement.z_nm)} mm  "
        f"theta {placement.theta_deg:.3f} deg   "
        f"{len(placement.correspondence)} paired, {len(placement.clashes)} clashing"
    )


def _diagnostic_lines(diagnostics: Iterable[Diagnostic]) -> list[str]:
    return [f"[{diagnostic.code}] {diagnostic.message}" for diagnostic in diagnostics]


def format_diagnostics(data: DockData) -> list[str]:
    """Every finding, grouped worst first and matched by code, never by message."""
    if not data.diagnostics:
        return ["", "DIAGNOSTICS", "  none"]
    lines = ["", f"DIAGNOSTICS ({len(data.diagnostics)})"]
    for severity in _SEVERITY_ORDER:
        found = data.of_severity(severity)
        if not found:
            continue
        lines.append(f"  {severity.value} ({len(found)})")
        lines.extend(f"    {line}" for line in _diagnostic_lines(found))
    return lines


def _counted(count: int, noun: str) -> str:
    """``count`` of ``noun``, pluralised: the one place this line's grammar lives."""
    return f"{count} {noun}{'s' if count != 1 else ''}"


def format_summary(data: DockData) -> list[str]:
    counts = {severity: len(data.of_severity(severity)) for severity in _SEVERITY_ORDER}
    placements = sum(len(found) for found in data.placements.values())
    parts = [_counted(len(data.boards), "board"), _counted(placements, "placement")]
    parts += [
        _counted(count, severity.value) for severity, count in counts.items() if count
    ]
    return ["", ", ".join(parts)]


def format_report(data: DockData) -> str:
    return "\n".join(format_case(data) + format_boards(data) + format_diagnostics(data))


def format_stage(stage: Stage[DockData], before: DockData, after: DockData) -> str:
    """One ``--verbose`` line per stage: what it found, never what it is."""
    added = after.diagnostics[len(before.diagnostics):]
    placements = sum(len(found) for found in after.placements.values())
    note = (
        ""
        if not added
        else f"   +{len(added)} diagnostics ({', '.join(sorted({d.code for d in added}))})"
    )
    return f"  {stage.name:<10} {len(after.boards):>2} boards, {placements:>2} placements{note}"


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _traced(pipeline: Pipeline[DockData], data: DockData, out: TextIO | None) -> DockData:
    """Run every stage, printing one line each when tracing is asked for."""
    if out is None:
        return pipeline.run(data)
    print("PIPELINE", file=out)
    for stage in pipeline:
        before, data = data, Pipeline([stage]).run(data)
        print(format_stage(stage, before, data), file=out)
    return data


def _degenerate(
    failure: StompgeomError, targets: Sequence[tuple[str, Path]], out: TextIO
) -> int:
    """A kernel operation that could not be evaluated, stated as the finding it is.

    ``degenerate-geometry`` is an ERROR in the spec's table, so it exits 2
    and withholds every artefact -- not 3, which would say the run never
    began. ``KernelUnavailable`` is deliberately not routed here: a missing
    dependency is not a fact about this board.
    """
    finding = Diagnostic.error("degenerate-geometry", str(failure))
    print("\nDIAGNOSTICS (1)", file=out)
    print(f"  {finding.severity.value} (1)", file=out)
    print(f"    {_diagnostic_lines([finding])[0]}", file=out)
    if targets:
        print("\n".join(_withheld(targets)), file=out)
    return EXIT_ERRORS


def _run(args: argparse.Namespace, out: TextIO) -> int:
    targets = parse_targets(args)
    try:
        check_target_set([path for _name, path in targets])
    except ValueError as failure:
        raise UsageError(str(failure)) from failure

    # Everything the command line can get wrong is resolved before an input
    # is opened: an unparseable expression, a tolerance that is not a
    # length, and an ordinal no board could carry are usage failures rather
    # than diagnostics about geometry nobody has read yet.
    panel_reference = parse_filter(args.panel_reference)
    tolerance_nm = parse_length(args.match_tolerance, "--match-tolerance")
    _refuse_unhonoured(args)

    drill = Path(args.drill)
    source = BoardSource(drill, [Path(board) for board in args.boards], Path(args.case_model))
    try:
        scan = source.scan()
        case = _registration(scan, drill)
        data = admit(_docked(scan, case), panel_reference)
        geometry = board_geometry(scan, case)
        pipeline = build_pipeline(
            tolerance_nm,
            scan.case.solids,
            {ordinal: board.solids for ordinal, board in geometry.items()},
        )
        data = _traced(pipeline, data, out if args.verbose else None)
    except KernelUnavailable:
        raise
    except StompgeomError as failure:
        return _degenerate(failure, targets, out)

    print(format_report(data), file=out)
    if targets:
        print(file=out)
        if data.worst_severity is Severity.ERROR:
            # Not rendered either: an emitter's bytes are of no use to
            # anybody here, and one may legitimately refuse data this broken.
            print("\n".join(_withheld(targets)), file=out)
        else:
            for line in _write(_emitters(targets, scan, geometry), data):
                print(line, file=out)
    print("\n".join(format_summary(data)), file=out)
    return exit_for_severity(data.worst_severity)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for bad input."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help exits 0; argparse usage errors do not
        return EXIT_CLEAN if not exit_.code else EXIT_USAGE

    # Expected user-facing failures share one handler. Unexpected faults keep
    # their tracebacks rather than being classified as invalid input.
    try:
        return _run(args, sys.stdout)
    except (StompError, OSError) as failure:
        print(f"{parser.prog}: error: {failure}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
