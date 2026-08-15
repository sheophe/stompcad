"""Command-line entry point (SPEC §8).

This module is the only place allowed to name concrete classes (DIP): it picks a
source, builds the stages **in order**, resolves output formats through the
registry, and renders a report. It contains no drill-data logic of its own —
every number it prints was computed by a stage and every byte it writes was
produced by an emitter.

Three constraints are worth stating, because each one is a rule that could
plausibly have been broken here:

* **The stage order lives here, not in the stages.** snap → normalize → dedupe →
  validate → sort. No stage may assert its own position (LSP), so somebody has
  to choose, and that somebody is the caller.
* **Formats are never named.** ``--emit FORMAT=PATH`` is resolved purely through
  :func:`get_emitter`, and :func:`available` supplies both the help text and the
  error messages. Adding an output format must not require an edit to this file;
  ``tests/test_cli.py`` proves it by dispatching to an emitter registered only
  inside the test. Emitter *options* classes are named — they are this module's
  job to populate from the arguments — but the option builders below are keyed
  by options class, so an unknown emitter simply gets its own defaults.
* **Defaults are not restated.** ``--grid-warn`` defaults to ``grid / 4``, and
  the diameter tolerances default per strategy. Those rules live in the stages;
  passing ``None`` here means "whatever you already say it is".

Exit codes: 0 clean, 1 warnings, 2 errors, 3 usage or I/O failure.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TextIO, get_args, get_type_hints

from .emitters import DrawingOptions, ExcellonOptions, JsonOptions, available, get_emitter
from .errors import AidrillError
from .formatting import format_mm
from .model import Diagnostic, DrillData, Severity
from .pipeline import (
    CheckReferenceSize,
    ClusterDiameters,
    Deduplicate,
    DiameterStrategy,
    NoNormalization,
    NormalizeDiameters,
    SnapPositions,
    SortHoles,
    TableDiameters,
)
from .protocols import Emitter, Pipeline, Stage
from .sources import AiPdfSource

__all__ = ["main", "build_parser", "build_pipeline", "parse_true_size", "parse_drill_sizes"]

EXIT_CLEAN = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_USAGE = 3

#: The whole of the exit-code policy. Derived from ``DrillData.worst_severity``
#: rather than recounted, so the report and the exit code cannot disagree.
_EXIT_FOR_SEVERITY: dict[Severity | None, int] = {
    None: EXIT_CLEAN,
    Severity.INFO: EXIT_CLEAN,
    Severity.WARNING: EXIT_WARNINGS,
    Severity.ERROR: EXIT_ERRORS,
}

#: Severities in the order the report groups them: worst first.
_SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)

_SIZE_SEPARATORS = ("x", "X", "×")


class UsageError(Exception):
    """A bad argument, or an input we cannot even begin to process. Exit 3."""


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """The argument surface of SPEC §8, exactly."""
    parser = argparse.ArgumentParser(
        prog="aidrill",
        description="Extract drill data from Adobe Illustrator artwork and emit it.",
    )
    parser.add_argument("panel", metavar="PANEL.ai", help="Illustrator file to read")
    parser.add_argument(
        "--drill-layer", metavar="NAME", default="Drill", help="layer holding the drill circles"
    )
    parser.add_argument(
        "--reference-layer",
        metavar="NAME",
        default="Background",
        help="layer holding the panel outline that defines the frame",
    )
    parser.add_argument(
        "--grid", metavar="MM", type=float, default=0.25, help="snap grid; 0 disables snapping"
    )
    parser.add_argument(
        "--grid-warn",
        metavar="MM",
        type=float,
        default=None,
        help="warn when a hole moves further than this (default: grid/4)",
    )
    parser.add_argument(
        "--diameters",
        choices=("cluster", "table", "none"),
        default="cluster",
        help="how a nominal diameter is chosen (default: cluster)",
    )
    parser.add_argument(
        "--diameter-tolerance",
        metavar="MM",
        type=float,
        default=None,
        help="tolerance for the chosen strategy (default: 0.05 cluster / 0.15 table)",
    )
    parser.add_argument(
        "--drill-sizes",
        metavar="CSV",
        default=None,
        help="comma-separated stocked drill sizes; required by --diameters table",
    )
    parser.add_argument(
        "--dedupe-tolerance",
        metavar="MM",
        type=float,
        default=0.05,
        help="how close two holes of one size must be to count as one (default: 0.05)",
    )
    parser.add_argument(
        "--true-size",
        metavar="WxH",
        default=None,
        help="declared panel size in mm; enables the reference-outline check",
    )
    parser.add_argument(
        "--emit",
        metavar="FORMAT=PATH",
        action="append",
        default=[],
        help="write an artifact; repeatable. FORMAT is one of: " + ", ".join(available()),
    )
    parser.add_argument("--title", metavar="TEXT", default="", help="title for drawings and headers")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show what each pipeline stage did"
    )
    return parser


def parse_true_size(text: str) -> tuple[float, float]:
    """``"112.4x60.5"`` → ``(112.4, 60.5)``. Accepts ``x``, ``X`` and ``×``.

    The finiteness check is not belt and braces. ``float`` happily returns
    ``inf`` and ``nan`` for ``"inf"`` and ``"nan"``, and ``width <= 0`` rejects
    neither — every comparison against ``nan`` is False, and ``inf`` is
    positive. ``--true-size infx60`` therefore passed validation and reached the
    drawing, which exited 1 and wrote an SVG carrying ``x="-inf"`` and
    ``width="inf"``: a corrupt document delivered as a successful run. A size
    that is not a real number is a usage error, and usage errors exit 3.
    """
    normalised = text
    for separator in _SIZE_SEPARATORS[1:]:
        normalised = normalised.replace(separator, _SIZE_SEPARATORS[0])
    parts = [part.strip() for part in normalised.split(_SIZE_SEPARATORS[0])]
    if len(parts) != 2:
        raise UsageError(f"--true-size expects WxH in millimetres, got {text!r}")
    try:
        width, height = (float(part) for part in parts)
    except ValueError:
        raise UsageError(f"--true-size expects WxH in millimetres, got {text!r}") from None
    if not math.isfinite(width) or not math.isfinite(height):
        raise UsageError(f"--true-size must be a finite size in millimetres, got {text!r}")
    if width <= 0 or height <= 0:
        raise UsageError(f"--true-size must be positive, got {text!r}")
    return (width, height)


def parse_drill_sizes(text: str) -> tuple[float, ...]:
    """``"3.2,5,7"`` → ``(3.2, 5.0, 7.0)``.

    Finiteness is checked for the same reason as in :func:`parse_true_size`:
    ``size <= 0`` is False for ``nan``, so ``--drill-sizes 3,nan`` used to reach
    ``TableDiameters`` as a stocked size that no bit in any drawer matches.
    """
    fields = [field.strip() for field in text.split(",") if field.strip()]
    if not fields:
        raise UsageError("--drill-sizes needs at least one size")
    try:
        sizes = tuple(float(field) for field in fields)
    except ValueError:
        raise UsageError(f"--drill-sizes expects comma-separated millimetres, got {text!r}") from None
    if not all(math.isfinite(size) for size in sizes):
        raise UsageError(f"--drill-sizes must all be finite millimetres, got {text!r}")
    if any(size <= 0 for size in sizes):
        raise UsageError(f"--drill-sizes must all be positive, got {text!r}")
    return sizes


def parse_emit(spec: str) -> tuple[str, Path]:
    """``"fmt=path"`` → ``("fmt", Path("path"))``. The format is not checked here."""
    name, separator, path = spec.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise UsageError(
            f"--emit expects FORMAT=PATH, got {spec!r}; formats: {', '.join(available())}"
        )
    return (name.strip(), Path(path.strip()))


# ---------------------------------------------------------------------------
# building the run
# ---------------------------------------------------------------------------


def build_strategy(args: argparse.Namespace) -> DiameterStrategy:
    """Choose the diameter strategy, leaving its default tolerance alone (DRY)."""
    tolerance = args.diameter_tolerance

    if args.diameters == "cluster":
        return ClusterDiameters() if tolerance is None else ClusterDiameters(tolerance)

    if args.diameters == "table":
        if not args.drill_sizes:
            raise UsageError("--diameters table requires --drill-sizes")
        sizes = parse_drill_sizes(args.drill_sizes)
        return TableDiameters(sizes) if tolerance is None else TableDiameters(sizes, tolerance)

    return NoNormalization()


def build_pipeline(args: argparse.Namespace) -> Pipeline:
    """snap → normalize → dedupe → validate → sort.

    The order is a property of *this* call, not of the stages: no stage knows or
    may ask what ran before it.
    """
    stages: list[Stage] = [
        SnapPositions(args.grid, args.grid_warn),
        NormalizeDiameters(build_strategy(args)),
        Deduplicate(args.dedupe_tolerance),
    ]
    if args.true_size is not None:
        stages.append(CheckReferenceSize(parse_true_size(args.true_size)))
    stages.append(SortHoles())
    return Pipeline(stages)


def read_source(args: argparse.Namespace) -> DrillData:
    source = AiPdfSource(
        args.panel,
        drill_layer=args.drill_layer,
        reference_layer=args.reference_layer,
    )
    return source.read()


@dataclass(frozen=True, slots=True)
class OutputSettings:
    """The handful of arguments that emitters may care about.

    Not a shared options bag (ISP): it is the *input* to the per-emitter options
    builders below, each of which picks out only what its own emitter declares.
    """

    title: str = ""
    true_size: tuple[float, float] | None = None


#: Keyed by options **class**, never by format name. An emitter whose options
#: type is not listed — including one this file has never seen — is constructed
#: with its own defaults.
_OPTION_BUILDERS: dict[type, Callable[[OutputSettings], Any]] = {
    ExcellonOptions: lambda s: ExcellonOptions(title=s.title),
    # No grid here: ``--grid`` goes to ``SnapPositions`` and nowhere else, and
    # the drawing reads the pitch back out of that stage's record. Passing it a
    # second time made the sheet's stamp agree with the flag rather than with
    # the holes, which is the same disagreement in miniature.
    DrawingOptions: lambda s: DrawingOptions(title=s.title, true_size=s.true_size),
    JsonOptions: lambda s: JsonOptions(),
}


def _options_for(emitter_cls: type, settings: OutputSettings) -> Any | None:
    """Build the options object ``emitter_cls`` declares, or ``None``."""
    # Narrow, and deliberately so: these three are what an unresolvable
    # annotation actually raises. A bare ``except Exception`` here would also
    # swallow a genuine fault inside a third-party emitter and hand it its
    # defaults, so the emitter would write a file with the wrong options rather
    # than the run failing.
    try:
        hints = get_type_hints(emitter_cls.__init__)
    except (NameError, TypeError, AttributeError):  # pragma: no cover - unresolvable hints
        return None
    for name, hint in hints.items():
        if name == "return":
            continue
        for candidate in get_args(hint) or (hint,):
            builder = _OPTION_BUILDERS.get(candidate)
            if builder is not None:
                return builder(settings)
    return None


def make_emitter(name: str, settings: OutputSettings) -> Emitter:
    """Resolve ``name`` through the registry and give it its options."""
    emitter_cls = get_emitter(name)  # raises EmitterError for an unknown format
    options = _options_for(emitter_cls, settings)
    return emitter_cls() if options is None else emitter_cls(options)


def settings_from(args: argparse.Namespace) -> OutputSettings:
    return OutputSettings(
        title=args.title,
        true_size=None if args.true_size is None else parse_true_size(args.true_size),
    )


def run_pipeline(
    pipeline: Pipeline,
    data: DrillData,
    trace: Callable[[Stage, DrillData, DrillData], None] | None = None,
) -> DrillData:
    """Fold the stages over ``data``, optionally reporting each step.

    Both paths fold through ``Pipeline.run`` — the traced one a stage at a time —
    so that whatever the fold does beyond calling ``apply`` happens under
    ``--verbose`` too. It did not: this function ran its own bare ``apply`` loop,
    and the day the fold started recording stage provenance the verbose run would
    have produced a drawing with an empty processing history, which is exactly
    the class of divergence provenance exists to stop.
    """
    if trace is None:
        return pipeline.run(data)
    for stage in pipeline:
        before, data = data, Pipeline([stage]).run(data)
        trace(stage, before, data)
    return data


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def format_source(data: DrillData) -> list[str]:
    info = data.source
    lines = [
        "SOURCE",
        f"  file             {info.path}",
        f"  drill layer      {info.drill_layer}",
        f"  reference layer  {info.reference_layer}",
    ]
    if info.layers_found:
        lines.append(f"  layers found     {', '.join(info.layers_found)}")
    if data.reference is not None:
        lines.append(
            f"  reference        {data.reference.width:.3f} x {data.reference.height:.3f} mm"
        )
    else:
        lines.append("  reference        (none)")
    return lines


def format_holes(data: DrillData) -> list[str]:
    """The hole table: nominal values, and the raw measurement behind each."""
    tools = data.tools()
    lines = [
        "",
        f"HOLES ({len(data.holes)})",
        "  No. Tool         X         Y      Dia  |      raw X      raw Y    raw Dia",
    ]
    for number, hole in enumerate(data.holes, start=1):
        lines.append(
            f"  {number:>3} T{tools[hole.diameter]:<3} "
            f"{hole.x:>9.3f} {hole.y:>9.3f} {hole.diameter:>8.3f}  | "
            f"{hole.raw.x:>10.4f} {hole.raw.y:>10.4f} {hole.raw.diameter:>10.4f}"
        )
    if not data.holes:
        lines.append("  (none)")
    return lines


#: The report's usual precision. Three decimals reads well and matches the
#: default the drill file and the drawing print at.
_REPORT_DECIMALS = 3
#: Widen no further than this: past nine decimals a float's digits are noise.
_MAX_REPORT_DECIMALS = 9


def _diameter_decimals(diameters: Iterable[float]) -> int:
    """The fewest decimals that keep every nominal diameter distinct in print.

    Derived from the values actually present, exactly as
    :attr:`ClusterDiameters.precision` is derived from its tolerance rather than
    fixed — and for the same reason. A fixed 3 dp is lossy, and what it loses is
    the one distinction this project exists to preserve: under
    ``--diameter-tolerance 0.0001`` a panel measuring 6.9998 and 7.0000 keeps two
    nominal diameters, and the tool summary printed both as ``7.000``. Two lines,
    the same diameter, different tool numbers — the founding defect of ADR-0001,
    rendered into the report a human reads and believes.

    Widening only when a collision exists keeps every ordinary panel reading as
    it always did.
    """
    values = list(diameters)
    decimals = _REPORT_DECIMALS
    while decimals < _MAX_REPORT_DECIMALS:
        if len({format_mm(value, decimals) for value in values}) == len(values):
            break
        decimals += 1
    return decimals


def format_tools(data: DrillData) -> list[str]:
    """The tool summary. Quantities come from the model, never from a re-count:
    this ``xN``, the machine-readable document's ``count`` field and the
    drawing's QTY column are one computation (:meth:`DrillData.tool_counts`), so
    no two of them can disagree about how many holes a bit drills.

    The precision is the block's own decision (see :func:`_diameter_decimals`)
    and belongs to no other renderer: what a drill file can print at three
    decimals is a property of that file's format, not of this report."""
    tools = data.tools()
    counts = data.tool_counts()
    decimals = _diameter_decimals(tools)
    lines = ["", f"TOOLS ({len(tools)})"]
    for diameter, number in tools.items():
        lines.append(
            f"  T{number:<3} dia {format_mm(diameter, decimals)} mm   x{counts[diameter]}"
        )
    return lines


def format_diagnostics(data: DrillData) -> list[str]:
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


def _diagnostic_lines(diagnostics: Iterable[Diagnostic]) -> list[str]:
    lines = []
    for diagnostic in diagnostics:
        where = (
            ""
            if diagnostic.location is None
            else f"  @ ({diagnostic.location[0]:.3f}, {diagnostic.location[1]:.3f})"
        )
        lines.append(f"[{diagnostic.code}] {diagnostic.message}{where}")
    return lines


def format_summary(data: DrillData) -> list[str]:
    counts = {severity: len(data.of_severity(severity)) for severity in _SEVERITY_ORDER}
    parts = [f"{len(data.holes)} holes", f"{len(data.tools())} tools"]
    parts += [
        f"{count} {severity.value}{'s' if count != 1 else ''}"
        for severity, count in counts.items()
        if count
    ]
    return ["", ", ".join(parts)]


def format_report(data: DrillData) -> str:
    lines = format_source(data) + format_holes(data) + format_tools(data)
    lines += format_diagnostics(data)
    return "\n".join(lines)


def format_stage(stage: Stage, before: DrillData, after: DrillData) -> str:
    """One line of ``--verbose`` per-stage detail."""
    added = len(after.diagnostics) - len(before.diagnostics)
    dropped = len(before.holes) - len(after.holes)
    notes = []
    if dropped:
        notes.append(f"-{dropped} holes")
    if added:
        codes = sorted({d.code for d in after.diagnostics[len(before.diagnostics):]})
        notes.append(f"+{added} diagnostics ({', '.join(codes)})")
    return f"  {stage.name:<20} {len(after.holes):>3} holes" + (
        "   " + "; ".join(notes) if notes else ""
    )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def _render(emitters: Iterable[tuple[Emitter, Path]], data: DrillData) -> list[tuple[Emitter, Path, str]]:
    """Ask every emitter for its bytes, before any of them reach the disk.

    All or nothing. An emitter may legitimately refuse — the drill-file emitter
    needs a reference outline for its default lower-left origin, and raises
    without one — and writing as we went left the first target on disk and not
    the second:
    a stale, inconsistent output set that looks like a successful run and gets
    handed to a machinist. Rendering first means a failure costs the whole run
    and is reported once, which is the honest answer.
    """
    return [(emitter, path, emitter.emit(data)) for emitter, path in emitters]


def _write(emitter: Emitter, path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return f"wrote {path}  ({emitter.name}, {len(text.encode('utf-8'))} bytes)"


def _run(args: argparse.Namespace, out: TextIO) -> int:
    targets = [parse_emit(spec) for spec in args.emit]
    settings = settings_from(args)
    # Resolve every format before touching the input file: an unknown format is
    # a usage error and should not wait on a PDF parse to be reported.
    emitters = [(make_emitter(name, settings), path) for name, path in targets]

    pipeline = build_pipeline(args)
    data = read_source(args)

    if args.verbose:
        print("PIPELINE", file=out)
        print(f"  {'(source)':<20} {len(data.holes):>3} holes", file=out)
        trace = lambda stage, before, after: print(format_stage(stage, before, after), file=out)
    else:
        trace = None
    data = run_pipeline(pipeline, data, trace)

    print(format_report(data), file=out)

    if emitters:
        rendered = _render(emitters, data)
        print("", file=out)
        for emitter, path, text in rendered:
            print(_write(emitter, path, text), file=out)

    print("\n".join(format_summary(data)), file=out)
    return _EXIT_FOR_SEVERITY[data.worst_severity]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for bad input."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help exits 0; argparse usage errors do not
        return EXIT_CLEAN if not exit_.code else EXIT_USAGE

    # One handler, because there was one behaviour: two byte-identical blocks
    # invited the day somebody edited only one of them. Anything not listed here
    # is a bug in aidrill rather than a fault in the input, and keeps its
    # traceback — the operator should never be told a crash was their typo.
    try:
        return _run(args, sys.stdout)
    except (UsageError, AidrillError, OSError) as failure:
        print(f"{parser.prog}: error: {failure}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
