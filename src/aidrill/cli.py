"""Command-line entry point (SPEC §8).

This module is the only place allowed to name concrete classes (DIP): it picks a
source, builds the stages **in order**, resolves output formats through the
registry, and renders a report. It contains no drill-data logic of its own —
every number it prints was computed by a stage and every byte it writes was
produced by an emitter.

Three constraints are worth stating, because each one is a rule that could
plausibly have been broken here:

* **The stage order lives here, not in the stages.** dedupe → sort. No stage may
  assert its own position (LSP), so somebody has to choose, and that somebody is
  the caller. The *quantisers* are the deliberate exception and are not chosen
  here at all: they run inside ``aidrill.quantise``, whose docstring says why
  their order is not a caller's to get wrong.
* **Formats are never named.** ``--emit FORMAT=PATH`` is resolved purely through
  :func:`get_emitter`, and :func:`available` supplies both the help text and the
  error messages. Adding an output format must not require an edit to this file;
  ``tests/test_cli.py`` proves it by dispatching to an emitter registered only
  inside the test. Emitter *options* classes are named — they are this module's
  job to populate from the arguments — but the option builders below are keyed
  by options class, so an unknown emitter simply gets its own defaults.
* **Defaults are not restated.** ``--grid-warn`` defaults to ``grid / 4`` and
  the diameter matching tolerance is whatever ``SnapDiametersToDrillTable`` says
  it is. Those rules live in the stages; passing ``None`` here, or not passing
  the argument at all, means "whatever you already say it is".

Exit codes: 0 clean, 1 warnings, 2 errors, 3 usage or I/O failure.
"""

from __future__ import annotations

import argparse
import inspect
import math
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, get_args, get_type_hints

from .emitters import DrawingOptions, ExcellonOptions, JsonOptions, available, get_emitter
from .enclosures import HAMMOND_1590
from .errors import AidrillError
from .formatting import format_mm
from .model import Diagnostic, DrillData, RawDrillData, Severity
from .pipeline import (
    CATALOGUE,
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    Deduplicate,
    DrillStandard,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
    SortHoles,
    normalize_part_name,
)
from .protocols import Emitter, Pipeline, Stage
from .quantise import quantise
from .sources import AiPdfSource
from .units import format_nm, nm_from_mm

__all__ = [
    "main",
    "build_parser",
    "build_pipeline",
    "build_quantisers",
    "Quantisers",
    "build_drill_standard",
    "parse_case",
    "parse_sizes",
    "parse_length",
]

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
        "--grid",
        metavar="MM",
        type=float,
        default=0.25,
        help="snap grid, in whole microns (default: 0.25)",
    )
    parser.add_argument(
        "--grid-warn",
        metavar="MM",
        type=float,
        default=None,
        help="warn when a hole moves further than this (default: grid/4)",
    )
    parser.add_argument(
        "--drill-standard",
        metavar="NAME",
        default=DEFAULT_STANDARD,
        help="the bit series the panel is drilled with, one of: "
        + ", ".join(DRILL_STANDARDS)
        + f" (default: {DEFAULT_STANDARD})",
    )
    parser.add_argument(
        "--drill-sizes",
        metavar="CSV",
        default=None,
        help="narrow the standard: only these of its sizes are in the drawer "
        "(every value must be a size the standard has)",
    )
    parser.add_argument(
        "--no-drill-sizes",
        metavar="CSV",
        default=None,
        help="narrow the standard: these of its sizes are not in the drawer",
    )
    parser.add_argument(
        "--case",
        metavar="PART",
        default=None,
        help=f"the {CATALOGUE} base designator the panel is drawn for, e.g. 1590B",
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


def parse_sizes(text: str, flag: str) -> tuple[float, ...]:
    """``"3.2,5,7"`` → ``(3.2, 5.0, 7.0)``. One parser, both size flags.

    ``flag`` is passed in rather than hardcoded because the whitelist and the
    blacklist are one decision about what a list of millimetres is, and two
    copies of it would be two decisions — the mistake ``tolerance.py`` and
    ``formatting.py`` exist to record.

    Finiteness is checked separately from positivity, and not as belt and
    braces. ``float`` happily returns ``nan`` for ``"nan"``, and ``size <= 0``
    rejects it no better than it rejects ``inf`` — every comparison against
    ``nan`` is False. Such a value would then be looked for in the drill table,
    found nowhere in it, and reported as a bit the standard does not stock —
    which is a true sentence about a size the operator never meant to type.
    """
    fields = [field.strip() for field in text.split(",") if field.strip()]
    if not fields:
        raise UsageError(f"{flag} needs at least one size in millimetres")
    try:
        sizes = tuple(float(field) for field in fields)
    except ValueError:
        raise UsageError(f"{flag} expects comma-separated millimetres, got {text!r}") from None
    if not all(math.isfinite(size) for size in sizes):
        raise UsageError(f"{flag} must all be finite millimetres, got {text!r}")
    if any(size <= 0 for size in sizes):
        raise UsageError(f"{flag} must all be positive, got {text!r}")
    return sizes


def parse_length(value: float, flag: str) -> int:
    """A millimetre figure off the command line, as whole nanometres.

    The command line's one crossing of the unit boundary. It has to happen here
    rather than inside the quantiser it feeds, because a quantiser's argument is
    a length the model already holds: ``SnapPositions`` takes nanometres and
    refuses anything that is not a plain ``int``, so a millimetre float handed
    straight over is a pitch a million times too fine with nothing to say so.

    What this adds beyond ``nm_from_mm`` is the finiteness check, and it is not
    belt and braces. ``float("nan")`` is a perfectly good float that
    ``nm_from_mm`` turns into ``decimal.InvalidOperation`` — an exception
    :func:`main` does not catch, so the process would exit **1**, the code this
    CLI reserves for "warnings present" and a wrapper reads as a run worth
    trusting. ``--grid=inf`` was worse and raised nothing at all: every hole
    snapped to ``nan`` and a drill file of ``XnanYnan`` lines was written, which
    parses, loads, and is the obvious one to hand to the machine.

    What the pitch then has to *be* is not decided here. That a grid is a whole
    number of microns, and that one below a micron is clamped rather than
    refused, are ``SnapPositions``' rules and stay there, so that a library
    consumer building the quantiser directly gets both of them too.
    """
    if not math.isfinite(value):
        raise UsageError(f"{flag} must be a finite number of millimetres, got {value!r}")
    return nm_from_mm(value)


#: Every base designator the catalogue holds. Derived from the catalogue rather
#: than listed, because a list is a second copy of a generated file.
CATALOGUE_PARTS = frozenset(enclosure.part for enclosure in HAMMOND_1590)


def _base_designator_of(part: str) -> str | None:
    """The longest catalogue designator ``part`` begins with, if any.

    A *suggestion*, never a decision, and that distinction is the whole design.
    Collapsing an order code such as ``1590BBBK`` onto ``1590BB`` for real needs
    the datasheet's suffix grammar — colour, flange, watertight — which has
    produced one wrong answer in this project already, and a collapse that lands
    on the wrong base part is silent and drills the wrong panel. Getting *this*
    wrong costs nothing: the run has already been refused and the operator
    retypes the part number either way.
    """
    beginnings = [part_number for part_number in CATALOGUE_PARTS if part.startswith(part_number)]
    return max(beginnings, key=len) if beginnings else None


def parse_case(text: str) -> str:
    """The declared part number, in catalogue form, or a usage error.

    **Why an unknown part number is a usage error and not a diagnostic.**
    ``--case 1590BBBK`` is a real order code — BB body, BK black finish — and
    the single most likely thing an operator types. Checked against footprints
    it would report ``wrong-enclosure`` on a *correct* 1590BB panel: an ERROR,
    exit 2, telling the operator they drew the wrong case when they drew the
    right one. Those are two different findings and they get two different
    exits.

    ``wrong-enclosure`` is a fact about the artwork: it took a parse, a
    measurement and a catalogue lookup to reach, and it belongs in the report,
    the drawing's notes and the machine-readable document, where both part
    numbers can be read side by side. A part number that is in no catalogue is a
    fact about the command line — nothing was measured, no file need even be
    opened — so it is refused here, before the input is read, with the base
    designator the order code is built on where the operator can see it.
    """
    part = normalize_part_name(text)
    if not part:
        raise UsageError("--case needs a part number, e.g. 1590B")
    if part in CATALOGUE_PARTS:
        return part
    base = _base_designator_of(part)
    hint = "" if base is None else f"; did you mean {base}?"
    raise UsageError(
        f"--case {text!r}: {part} is not a base designator in the {CATALOGUE} "
        f"catalogue{hint}"
    )


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


def build_drill_standard(args: argparse.Namespace) -> DrillStandard:
    """The declared bit series, narrowed to what is actually in the drawer.

    Resolved here rather than in the stage so that a typed standard, a typed
    size and an unstocked size are all refused before the input file is opened —
    and all as usage errors, which is what they are.
    """
    standard = DRILL_STANDARDS.get(args.drill_standard)
    if standard is None:
        raise UsageError(
            f"--drill-standard {args.drill_standard!r} is not a drill standard; "
            f"available: {', '.join(DRILL_STANDARDS)}"
        )

    include = _selected_sizes(args.drill_sizes, "--drill-sizes")
    exclude = _selected_sizes(args.no_drill_sizes, "--no-drill-sizes")
    if include is None and exclude is None:
        return standard
    try:
        return standard.select(include=include, exclude=exclude)
    except ValueError as failure:
        # The standard already knows which sizes it has and what it is called;
        # restating that here would be a second answer to the same question.
        raise UsageError(str(failure)) from failure


def _selected_sizes(text: str | None, flag: str) -> tuple[int, ...] | None:
    """The sizes the operator listed, in the unit the drill table is held in.

    ``parse_sizes`` answers in millimetres because millimetres are what the
    operator typed, and ``DrillStandard.select`` matches on whole nanometres,
    exactly, with no slack anywhere in it. Converting between them is therefore
    not a tidying step: ``--drill-sizes 3.2`` handed over unconverted is a
    request for a *three-nanometre* bit, which the standard correctly reports as
    a size it does not have — so a flag the operator spelled perfectly is
    refused, and the message sends them to check the series.
    """
    if text is None:
        return None
    return tuple(nm_from_mm(size) for size in parse_sizes(text, flag))


@dataclass(frozen=True, slots=True)
class Quantisers:
    """The three quantisers of one run, named rather than ordered.

    A record and not a list, because a list would put them in an order and the
    order is not this module's to state: ``quantise`` decides it, for reasons
    that are about what each quantiser can do to the run rather than about
    configuration. Three fields spelled with the keywords ``quantise`` takes
    means the call site reads as the composition it is.
    """

    enclosure: IdentifyHammondFootprint
    diameters: SnapDiametersToDrillTable
    positions: SnapPositions


def build_quantisers(args: argparse.Namespace) -> Quantisers:
    """The three quantisers ``aidrill.quantise`` composes, ready to be handed it.

    Built here and never ordered here. Which of them runs first is
    ``quantise``'s decision and cannot be made from outside it, which is the
    whole reason they are not stages — see that module's docstring.

    Every argument they take is resolved before the input file is opened, so a
    grid that is not a number, a standard nobody stocks, a size the drawer does
    not hold and a part number in no catalogue are all reported as the typos
    they are rather than after a PDF parse.
    """
    return Quantisers(
        enclosure=IdentifyHammondFootprint(
            expected_part=None if args.case is None else parse_case(args.case)
        ),
        diameters=SnapDiametersToDrillTable(build_drill_standard(args)),
        positions=_snap_positions(args),
    )


def _snap_positions(args: argparse.Namespace) -> SnapPositions:
    """The position quantiser, or a usage error if its numbers are not numbers.

    The rules are the quantiser's and stay there — a grid that is not a whole
    number of microns is refused whoever builds it, library consumer included,
    and one below a micron is clamped with a warning rather than refused at all.
    What belongs here is the *exit code*: left to escape, that ``ValueError``
    reached no handler and Python exited 1, which this CLI has promised means
    "warnings present". Naming the flags is this layer's job too, because flags
    are the CLI's vocabulary and not the quantiser's: ``--grid-warn`` arrives
    there as ``warn_over_nm``.
    """
    grid_nm = parse_length(args.grid, "--grid")
    warn_over_nm = (
        None if args.grid_warn is None else parse_length(args.grid_warn, "--grid-warn")
    )
    try:
        return SnapPositions(grid_nm, warn_over_nm)
    except ValueError as failure:
        raise UsageError(f"--grid/--grid-warn: {failure}") from failure


def build_pipeline(args: argparse.Namespace) -> Pipeline:
    """dedupe → sort, after the quantisation phase and never before it.

    The order is a property of *this* call, not of the stages: no stage knows or
    may ask what ran before it.

    Both positions are worth the sentence, and the first is the reason this
    pipeline is as short as it is. ``Deduplicate`` compares position and
    diameter exactly and decides neither for itself, so it can only run once
    something else has: that 6.9998 and 7.0002 are one size is
    ``SnapDiametersToDrillTable``'s answer and that −39.9906 and −40.0 are one
    place is ``SnapPositions``', made once in the phase above or made twice and
    differently. And sorting comes last of all because it orders what survived,
    which is not known until the duplicates have gone.

    ``args`` is unused and stays in the signature: this is the documented
    integration point for a new stage, and every stage worth adding here is
    configured from the command line.
    """
    stages: list[Stage] = [Deduplicate(), SortHoles()]
    return Pipeline(stages)


def read_source(args: argparse.Namespace) -> RawDrillData:
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

    One field, and a class rather than the bare string it currently holds,
    because the shape is what keeps ``--grid`` out of an emitter's options: the
    sheet was handed the flag alongside the stage that did the snapping, so data
    snapped at 0.5 could be stamped 0.25 for a machinist to read.
    """

    title: str = ""


#: Keyed by options **class**, never by format name. An emitter whose options
#: type is not listed — including one this file has never seen — is constructed
#: with its own defaults.
_OPTION_BUILDERS: dict[type, Callable[[OutputSettings], Any]] = {
    ExcellonOptions: lambda s: ExcellonOptions(title=s.title),
    # No grid here: ``--grid`` goes to ``SnapPositions`` and nowhere else, and
    # the drawing reads the pitch back out of that stage's record. Passing it a
    # second time made the sheet's stamp agree with the flag rather than with
    # the holes, which is the same disagreement in miniature.
    # No true_size either: the drawing takes the panel's real size from the
    # enclosure the pipeline identified, not from a second declaration here.
    DrawingOptions: lambda s: DrawingOptions(title=s.title),
    JsonOptions: lambda s: JsonOptions(),
}


def _options_for(emitter_cls: type, settings: OutputSettings) -> Any | None:
    """Build the options object ``emitter_cls`` declares, or ``None``."""
    # Narrow, and deliberately so: these three are what an unresolvable
    # annotation actually raises. A bare ``except Exception`` here would also
    # swallow a genuine fault inside a third-party emitter and hand it its
    # defaults, so the emitter would write a file with the wrong options rather
    # than the run failing.
    # ``getattr_static`` rather than ``emitter_cls.__init__``: the attribute is
    # wanted as the function this class declares, not as whatever the descriptor
    # protocol would bind, and a type checker cannot know the plain access is
    # safe on an arbitrary ``type``.
    try:
        hints = get_type_hints(inspect.getattr_static(emitter_cls, "__init__"))
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
    return OutputSettings(title=args.title)


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


#: Width of the report's label column, so that every ``  label   value`` block
#: lines its values up with every other one.
_LABEL = 17


def _field(label: str, value: str) -> str:
    return f"  {label:<{_LABEL}}{value}"


def format_source(data: DrillData) -> list[str]:
    """Where the bytes came from, and the outline that set the frame.

    The outline is printed twice, nominal beside measured, in the idiom the hole
    table uses four lines below for exactly the same reason.
    ``IdentifyHammondFootprint`` rewrites the measurement — the fixture panel
    comes to 113.000 × 60.000 and leaves as the catalogue's 112.400 × 60.500 — so a
    report quoting only the nominal states a datasheet number as though it were
    what the artwork said, which is the failure ``ReferenceOutline.raw`` was
    added to make impossible everywhere else.
    """
    info = data.source
    lines = [
        "SOURCE",
        _field("file", info.path),
        _field("drill layer", info.drill_layer),
        _field("reference layer", info.reference_layer),
    ]
    if info.layers_found:
        lines.append(_field("layers found", ", ".join(info.layers_found)))
    if data.reference is None:
        lines.append(_field("reference", "(none)"))
    else:
        reference = data.reference
        lines.append(
            _field(
                "reference",
                f"{format_nm(reference.width_nm)} x {format_nm(reference.height_nm)} mm"
                f"  |  raw {format_mm(reference.raw.width, 4)} x "
                f"{format_mm(reference.raw.height, 4)} mm",
            )
        )
    return lines


def format_enclosure(data: DrillData) -> list[str]:
    """Which catalogue enclosure the panel was identified as being drawn for.

    The conclusion reached the sheet and the machine-readable document and
    stopped short of the report a human reads, so a clean run said nothing at
    all about the case. A *mismatch* arrives as a diagnostic, which put the
    silence exactly on the success path — where the operator is looking for
    confirmation that the artwork is the box they think it is.

    The footprint is printed to the same three decimals every other length in
    this report gets, because the catalogue carries Hammond's 0.05 mm figures: a
    1590B is 112.400 × 60.500, and rounding it to ``112 × 61`` on the way out
    would throw away the digits that make 1590B and 1590BS two enclosures rather
    than one. The enclosure module's ``_footprint_list`` prints the same figures
    the same way, so the report and the diagnostics beneath it cannot drift.

    Two things are stated the way the drawing's title block states them, so that
    the two renderings cannot drift: the catalogue's own footprint rather than
    the measured outline, and ``candidates`` rather than a part, because a 2-D
    outline identifies a footprint and several parts share each one. A part is
    named only when the operator declared it, and it replaces the list rather
    than joining it — the question the list asks has been answered. The
    candidates are printed in the order the match handed them over and in full,
    the one place this differs from the sheet: nothing here is competing for
    room in a title block, and a part number is what the operator orders by.

    No match is said out loud rather than left blank, for the reason "(none)"
    is: a footprint this catalogue does not stock is a real outcome and reads
    nothing like a line somebody forgot to print.
    """
    lines = ["", "ENCLOSURE"]
    match = data.enclosure
    if match is None:
        lines.append("  (not identified)")
        return lines
    size = f"{format_nm(match.length_nm)} x {format_nm(match.width_nm)} mm"
    if match.rotated:
        # The match keeps the catalogue's orientation while every dimension
        # printed elsewhere is the artwork's, so a turned panel needs saying.
        size += " (rotated)"
    lines.append(_field("footprint", f"{match.family}  {size}"))
    if match.selected_part is not None:
        lines.append(_field("part", match.selected_part))
    else:
        lines.append(_field("candidates", ", ".join(match.candidates)))
    return lines


def format_holes(data: DrillData) -> list[str]:
    """The hole table: nominal values, and the raw measurement behind each.

    Holes are named by ``Hole.index``, the identity every diagnostic and the
    drawing's balloons use, never by position in the table. The two coincide
    only until something changes the population: dedupe drops a hole and the
    positions renumber while the identities do not, so a report keyed on
    position names a different hole than the ``duplicate-hole`` finding printed
    six lines above it. The numbers are therefore not contiguous, which is the
    honest rendering of a list that has had holes removed from it.
    """
    tools = data.tools()
    lines = [
        "",
        f"HOLES ({len(data.holes)})",
        "  No. Tool         X         Y      Dia  |      raw X      raw Y    raw Dia",
    ]
    for hole in data.holes:
        lines.append(
            f"  {hole.index:>3} T{tools[hole.diameter_nm]:<3} "
            f"{format_nm(hole.x_nm):>9} {format_nm(hole.y_nm):>9} "
            f"{format_nm(hole.diameter_nm):>8}  | "
            f"{format_mm(hole.raw.x, 4):>10} {format_mm(hole.raw.y, 4):>10} "
            f"{format_mm(hole.raw.diameter, 4):>10}"
        )
    if not data.holes:
        lines.append("  (none)")
    return lines


#: The report's usual precision. Three decimals reads well and matches the
#: default the drill file and the drawing print at.
_REPORT_DECIMALS = 3
#: Six decimals of a millimetre *is* a nanometre, and the model holds nothing
#: finer, so this bound is reached only by two lengths that are genuinely equal —
#: at which point widening further would print zeros and still not tell them
#: apart, because there is nothing to tell apart.
_MAX_REPORT_DECIMALS = 6


def _diameter_decimals(diameters: Iterable[int]) -> int:
    """The fewest decimals that keep every nominal diameter distinct in print.

    Derived from the values actually present rather than fixed. A fixed 3 dp is
    lossy, and what it loses is the one distinction this project exists to
    preserve: a panel carrying two nominal diameters that agree to three
    decimals printed both as ``7.000``. Two lines, the same diameter, different
    tool numbers — the founding defect of ADR-0001, rendered into the report a
    human reads and believes.

    No flag reaches this any more: every nominal now comes from a drill table
    whose sizes are further apart than three decimals, so the CLI cannot produce
    the collision. It stays because the *library* still can — a caller may hand
    the report any ``DrillData`` it likes — and because a renderer that is only
    correct for the inputs one entry point happens to produce is not correct.

    Widening only when a collision exists keeps every ordinary panel reading as
    it always did.
    """
    values = list(diameters)
    decimals = _REPORT_DECIMALS
    while decimals < _MAX_REPORT_DECIMALS:
        if len({format_nm(value, decimals) for value in values}) == len(values):
            break
        decimals += 1
    return decimals


#: The parameter ``SnapDiametersToDrillTable.describe`` records the drawer under.
#: The stage's *name* is read off the class, which this module already holds; the
#: key inside its payload is a string wherever it is read from.
_STANDARD_PARAMETER = "standard"


def _tool_label(data: DrillData) -> Callable[[int], str]:
    """How this report spells a diameter, read from the standard that ran.

    Read out of ``processing``, never re-derived from the arguments this run was
    given: the drawing's schedule takes the spelling from the same record, and a
    renderer that works its own out is the disagreement ADR-0001 exists to
    prevent — printed, this time, in the block the operator reads before walking
    to the drawer.

    The spelling is the drill table's own because no single one serves both
    drawers. ``dia 5.159 mm`` for a 13/64" bit is unique and truthful at no
    precision at all: the nearest thing to it that can be bought is a 5.2 mm
    metric bit, which is a different hole.

    Millimetres are the fallback, on two occasions that are not the same
    occasion. A run that recorded no standard — a library consumer's document,
    or a pipeline built without the stage — has no spelling to borrow, and
    guessing one would put a bit designation in the report that no drawer holds.
    And a *recorded* standard whose own spelling would print two distinct
    nominals identically is refused the last word: the metric drawer states
    2 dp, so a document carrying 6.9998 beside 7.0 would read ``⌀7.00 mm`` twice
    under two tool numbers, which is the founding defect rendered into the
    report a human believes. No CLI run can build that document — every nominal
    it produces comes from a table whose sizes are further apart — but the
    library can, and a renderer correct only for one entry point's output is not
    correct.
    """
    tools = data.tools()
    run = data.last_run(SnapDiametersToDrillTable.name)
    name = None if run is None else run.get(_STANDARD_PARAMETER)
    if isinstance(name, str):
        standard = DRILL_STANDARDS.get(name)
        if standard is not None and len({standard.label(d) for d in tools}) == len(tools):
            return standard.label
    decimals = _diameter_decimals(tools)
    return lambda diameter_nm: f"⌀{format_nm(diameter_nm, decimals)} mm"


def format_tools(data: DrillData) -> list[str]:
    """The tool summary. Quantities come from the model, never from a re-count:
    this ``xN``, the machine-readable document's ``count`` field and the
    drawing's QTY column are one computation (:meth:`DrillData.tool_counts`), so
    no two of them can disagree about how many holes a bit drills.

    How a diameter is *spelled* is likewise not this block's decision — see
    :func:`_tool_label`, which reads it back out of the run's provenance."""
    tools = data.tools()
    counts = data.tool_counts()
    label = _tool_label(data)
    # Padded to the widest spelling present rather than to a constant: a
    # fraction and a decimal millimetre are not the same length, and neither is
    # the same length in every drawer.
    column = max((len(label(diameter)) for diameter in tools), default=0)
    lines = ["", f"TOOLS ({len(tools)})"]
    for diameter, number in tools.items():
        lines.append(f"  T{number:<3} {label(diameter):<{column}}   x{counts[diameter]}")
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
            if diagnostic.location_nm is None
            else f"  @ ({format_nm(diagnostic.location_nm[0])}, "
            f"{format_nm(diagnostic.location_nm[1])})"
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
    lines = format_source(data) + format_enclosure(data) + format_holes(data)
    lines += format_tools(data)
    lines += format_diagnostics(data)
    return "\n".join(lines)


def format_stage(stage: Stage, before: DrillData, after: DrillData) -> str:
    """One line of ``--verbose`` per-stage detail."""
    return _format_step(stage.name, len(before.holes), before.diagnostics, after)


def format_phase(before: RawDrillData, after: DrillData) -> str:
    """The same line for the quantisation phase, which is not a stage.

    It earns a line of its own because it is where most of a run's findings are
    made and where holes are dropped — a ``--verbose`` listing that jumped
    straight from the source's hole count to dedupe's would leave the operator
    with nothing to look at for the step that refused their 30 mm cut-out.
    """
    return _format_step("quantise", len(before.holes), before.diagnostics, after)


def _format_step(
    name: str, holes_before: int, diagnostics_before: tuple[Diagnostic, ...], after: DrillData
) -> str:
    """``  name   N holes   -1 holes; +2 diagnostics (off-grid)``.

    Written against counts rather than against a ``Stage`` so that the phase and
    the stages are rendered by one function: two spellings of this line would
    eventually disagree about what "dropped" means, on the one step that
    actually drops holes.
    """
    added = len(after.diagnostics) - len(diagnostics_before)
    dropped = holes_before - len(after.holes)
    notes = []
    if dropped:
        notes.append(f"-{dropped} holes")
    if added:
        codes = sorted({d.code for d in after.diagnostics[len(diagnostics_before):]})
        notes.append(f"+{added} diagnostics ({', '.join(codes)})")
    return f"  {name:<20} {len(after.holes):>3} holes" + (
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


def _withheld(targets: Iterable[tuple[Emitter, Path]]) -> list[str]:
    """Say what was not written, and name every path, so nothing looks stale.

    An ERROR means the data does not describe a panel that can be drilled, and
    an artifact made from it is a document that states something false. The
    exit code already says so, but the exit code is the part of a run that gets
    read least: the failure this prevents is a drill file **missing a hole**,
    since a hole whose diameter matches no bit is dropped by ``snap-diameters``
    and the Excellon format renders no diagnostics at all. The drawing's NOTES
    and the machine-readable document would both carry the finding; the file
    that actually goes to the machine would carry a shorter panel and look
    perfectly well-formed.

    Only ERROR withholds. A warning is something to look at, not a reason to
    leave the operator with nothing — an enclosure this tool does not stock is a
    warning, and it must still produce a drill file.
    """
    return ["wrote nothing: this run has errors, so these were not written:"] + [
        f"  {path}  ({emitter.name})" for emitter, path in targets
    ]


def _run(args: argparse.Namespace, out: TextIO) -> int:
    targets = [parse_emit(spec) for spec in args.emit]
    settings = settings_from(args)
    # Resolve every format before touching the input file: an unknown format is
    # a usage error and should not wait on a PDF parse to be reported.
    emitters = [(make_emitter(name, settings), path) for name, path in targets]

    # Everything the command line can get wrong is resolved before the input is
    # opened: a bad standard, an unstocked size, a grid that is not a number and
    # a part number in no catalogue are all usage errors, not diagnostics.
    quantisers = build_quantisers(args)
    pipeline = build_pipeline(args)
    raw = read_source(args)

    if args.verbose:
        print("PIPELINE", file=out)
        print(f"  {'(source)':<20} {len(raw.holes):>3} holes", file=out)

    data = quantise(
        raw,
        enclosure=quantisers.enclosure,
        diameters=quantisers.diameters,
        positions=quantisers.positions,
    )

    trace: Callable[[Stage, DrillData, DrillData], None] | None = None
    if args.verbose:
        print(format_phase(raw, data), file=out)

        def trace(stage: Stage, before: DrillData, after: DrillData) -> None:
            print(format_stage(stage, before, after), file=out)

    data = run_pipeline(pipeline, data, trace)

    print(format_report(data), file=out)

    if emitters:
        print(file=out)
        if data.worst_severity is Severity.ERROR:
            # Not rendered either: an emitter's bytes are of no use to anybody
            # here, and one of them may legitimately refuse data this broken.
            print("\n".join(_withheld(emitters)), file=out)
        else:
            for emitter, path, text in _render(emitters, data):
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
