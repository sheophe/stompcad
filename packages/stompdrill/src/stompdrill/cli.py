"""Command-line composition and reporting.

Quantiser order belongs to :func:`stompdrill.quantise`; post-quantisation stages
run deduplicate → review-grid-ties → route → check-outline-containment, with
clearance appended when a case model is supplied. Emitters are registry-resolved.
Exit codes are 0 clean, 1 warnings, 2 errors and 3 usage or I/O failure.
"""

from __future__ import annotations

import argparse
import inspect
import math
import sys
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, get_args, get_type_hints

from stompmodel.diagnostics import (
    EXIT_CLEAN,
    EXIT_USAGE,
    Diagnostic,
    Severity,
    exit_for_severity,
)
from stompmodel.errors import StompError
from stompmodel.model import CaseFace, DrillData
from stompmodel.protocols import (
    Emitter,
    Payload,
    Pipeline,
    Stage,
    StagedWrite,
    stage_payload,
)
from stompmodel.units import Nanometre, format_nm, nm_from_mm

from .cad import OcpCaseModel
from .emitters import (
    DrawingOptions,
    ExcellonOptions,
    JsonOptions,
    PdfDrawingOptions,
    StepOptions,
    available,
    get_emitter,
)
from .emitters.drawing.build import SheetText
from .enclosures import HAMMOND_1590
from .formatting import format_mm
from .pipeline import (
    CATALOGUE,
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    CheckCaseClearance,
    CheckOutlineContainment,
    Deduplicate,
    DrillStandard,
    IdentifyHammondFootprint,
    ReviewGridTies,
    RouteHoles,
    SnapDiametersToDrillTable,
    SnapPositions,
    normalize_part_name,
)
from .quantise import RawDrillData, quantise
from .sources import DEFAULT_FORM_DEPTH, AiPdfSource

__all__ = [
    "main",
    "build_parser",
    "build_pipeline",
    "build_quantisers",
    "Quantisers",
    "build_drill_standard",
    "build_case_model",
    "parse_case",
    "parse_face",
    "parse_sizes",
    "parse_length",
]

#: Severities in the order the report groups them: worst first.
_SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)


class UsageError(Exception):
    """A bad argument, or an input we cannot even begin to process. Exit 3."""


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="stompdrill",
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
        help="snap grid, in millimetres; the pitch must be a whole number of microns "
        "(default: 0.25, that is 250 microns)",
    )
    parser.add_argument(
        "--grid-warn",
        metavar="MM",
        type=float,
        default=None,
        help="warn when a hole moves further than this, in millimetres "
        "(default: a quarter of the grid)",
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
        "--case-model",
        metavar="PATH",
        default=None,
        help="a STEP model of the enclosure; enables clearance checking "
        "(see tools/fetch_case_model.py)",
    )
    parser.add_argument(
        "--case-face",
        metavar="SIDE",
        default="box",
        help="which side the panel is drilled into: box or lid (default: box)",
    )
    parser.add_argument(
        "--case-margin",
        metavar="MM",
        type=float,
        default=1.0,
        help="clearance between the bit and the nearest non-flat feature, in "
        "millimetres (default: 1.0)",
    )
    parser.add_argument(
        "--form-depth",
        metavar="N",
        type=int,
        default=DEFAULT_FORM_DEPTH,
        help="how many levels of nested Form XObject to follow in the artwork; "
        f"stopping with more below reports nesting-truncated (default: {DEFAULT_FORM_DEPTH})",
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
    """Parse comma-separated, finite positive millimetre sizes for ``flag``."""
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


def parse_length(value: float, flag: str) -> Nanometre:
    """Convert a finite command-line millimetre value to whole nanometres."""
    if not math.isfinite(value):
        raise UsageError(f"{flag} must be a finite number of millimetres, got {value!r}")
    return nm_from_mm(value)


#: Every base designator the catalogue holds. Derived from the catalogue rather
#: than listed, because a list is a second copy of a generated file.
CATALOGUE_PARTS = frozenset(enclosure.part for enclosure in HAMMOND_1590)


def _base_designator_of(part: str) -> str | None:
    """Return the longest catalogue prefix as a suggestion, never a resolution."""
    beginnings = [part_number for part_number in CATALOGUE_PARTS if part.startswith(part_number)]
    return max(beginnings, key=len) if beginnings else None


def parse_case(text: str) -> str:
    """Normalise a catalogue part, rejecting unknown names as usage errors."""
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


def parse_face(text: str) -> CaseFace:
    """Normalise the drilled side, rejecting anything else as a usage error."""
    try:
        return CaseFace(text.strip().lower())
    except ValueError:
        raise UsageError(
            f"--case-face {text!r} must be one of: "
            f"{', '.join(face.value for face in CaseFace)}"
        ) from None


def parse_emit(spec: str) -> tuple[str, Path]:
    """``"fmt=path"`` → ``("fmt", Path("path"))``. The format is not checked here."""
    name, separator, path = spec.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise UsageError(
            f"--emit expects FORMAT=PATH, got {spec!r}; formats: {', '.join(available())}"
        )
    return (name.strip(), Path(path.strip()))


def _target_key(path: Path) -> str:
    """Reduce a target path to the identity two ``--emit`` specs collide on.

    UAX #15 D145's canonical caseless match of the resolved path, applied
    unconditionally: whether this host folds letter case or normalisation
    form is not knowable before a target exists, and ``samefile`` needs
    both targets to exist already. Folding refuses a pair a preserving
    volume would have kept apart; not folding lets one requested artefact
    overwrite another while both are reported written. A comparison key
    only — the bytes still go to the path the caller named.
    """
    resolved = str(path.resolve())
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", resolved).casefold())


def _preflight_targets(targets: Sequence[tuple[str, Path]]) -> None:
    """Validate the target set itself before anything is rendered.

    Two ``--emit`` specs may not name one target under :func:`_target_key`,
    and an existing target must be a regular file: this command line reads a
    target's prior bytes before replacing it, and a pipe or character device
    would never return from that read. The write mechanism's own
    preconditions are not restated here — ``stage_payload`` enforces them
    (ADR-0005) before any target is replaced, so an out-of-domain target
    still withholds the whole set, just after a render. See ADR-0001.
    """
    seen: dict[str, tuple[str, Path]] = {}
    for name, path in targets:
        key = _target_key(path)
        earlier = seen.get(key)
        if earlier is not None:
            earlier_name, earlier_path = earlier
            raise UsageError(
                f"--emit {name}={path}: names the same target as "
                f"--emit {earlier_name}={earlier_path}; two artefacts cannot "
                "share one path. Targets are compared ignoring letter case "
                "and Unicode normalisation form, because a filesystem may "
                "hold two such spellings as one file"
            )
        seen[key] = (name, path)
        if path.exists() and not path.is_file():
            raise UsageError(
                f"--emit {name}={path}: exists and is not a regular file; this "
                "command line reads a target's prior bytes before replacing it"
            )


# ---------------------------------------------------------------------------
# building the run
# ---------------------------------------------------------------------------


def build_drill_standard(args: argparse.Namespace) -> DrillStandard:
    """Resolve and narrow the declared drill standard before reading input."""
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


def _selected_sizes(text: str | None, flag: str) -> tuple[Nanometre, ...] | None:
    """Parse selected millimetre sizes into exact drill-table nanometres."""
    if text is None:
        return None
    return tuple(nm_from_mm(size) for size in parse_sizes(text, flag))


def build_case_model(args: argparse.Namespace) -> OcpCaseModel | None:
    """Load the supplied case model, or ``None`` when none was given.

    ``--case-face`` and ``--case-margin`` are validated whether or not a
    model was supplied: they are flags the user typed either way, and a bad
    value must not wait on ``--case-model`` being added to be caught.
    """
    face = parse_face(args.case_face)
    margin_nm = parse_length(args.case_margin, "--case-margin")
    if margin_nm <= 0:
        raise UsageError("--case-margin must be a positive number of millimetres")
    if args.case_model is None:
        return None
    from .cad import load_case_model

    try:
        return load_case_model(
            Path(args.case_model),
            face=face,
            margin_nm=margin_nm,
            part=None if args.case is None else parse_case(args.case),
        )
    except StompError as failure:
        raise UsageError(f"--case-model: {failure}") from failure


@dataclass(frozen=True, slots=True)
class Quantisers:
    """The run's named quantisers; :func:`quantise` owns their ordering."""

    enclosure: IdentifyHammondFootprint
    diameters: SnapDiametersToDrillTable
    positions: SnapPositions


def build_quantisers(args: argparse.Namespace) -> Quantisers:
    """Build named quantisers, resolving all effective inputs before file access."""
    return Quantisers(
        enclosure=IdentifyHammondFootprint(
            expected_part=None if args.case is None else parse_case(args.case)
        ),
        diameters=SnapDiametersToDrillTable(build_drill_standard(args)),
        positions=_snap_positions(args),
    )


def _snap_positions(args: argparse.Namespace) -> SnapPositions:
    """Build position snapping, translating invalid grid values to usage errors."""
    grid_nm = parse_length(args.grid, "--grid")
    warn_over_nm = (
        None if args.grid_warn is None else parse_length(args.grid_warn, "--grid-warn")
    )
    try:
        return SnapPositions(grid_nm, warn_over_nm)
    except ValueError as failure:
        raise UsageError(f"--grid/--grid-warn: {failure}") from failure


def build_pipeline(args: argparse.Namespace) -> Pipeline[DrillData]:
    """Build deduplicate → review-grid-ties → route → containment, then clearance.

    Review follows deduplication so it describes surviving holes; ordering is
    last among the geometry stages. The two checks only diagnose, so they run
    after numbering and every stage remains independently valid. Containment
    precedes clearance: the outline is the weaker boundary and the model's face
    is the stronger one.
    """
    stages: list[Stage[DrillData]] = [
        Deduplicate(),
        ReviewGridTies(),
        RouteHoles(),
        CheckOutlineContainment(),
    ]
    model: OcpCaseModel | None = getattr(args, "case_model_object", None)
    if model is not None:
        stages.append(CheckCaseClearance(model))
    return Pipeline(stages)


def read_source(args: argparse.Namespace) -> RawDrillData:
    try:
        source = AiPdfSource(
            args.panel,
            drill_layer=args.drill_layer,
            reference_layer=args.reference_layer,
            form_depth=args.form_depth,
        )
    except ValueError as failure:
        raise UsageError(f"--form-depth: {failure}") from failure
    return source.read()


@dataclass(frozen=True, slots=True)
class OutputSettings:
    """Command-line values from which emitter-specific options are built."""

    title: str = ""
    case_model: OcpCaseModel | None = None


#: Keyed by options **class**, never by format name. An emitter whose options
#: type is not listed — including one this file has never seen — is constructed
#: with its own defaults.
_OPTION_BUILDERS: dict[type, Callable[[OutputSettings], Any]] = {
    ExcellonOptions: lambda s: ExcellonOptions(title=s.title),
    # Drawing options contain presentation values only; grid pitch and panel
    # dimensions come from canonical processing results. Both sheets' other
    # ISO 7200 fields have no command-line source yet; a caller using the
    # library supplies them directly, through ``SheetText``.
    DrawingOptions: lambda s: DrawingOptions(text=SheetText(title=s.title)),
    PdfDrawingOptions: lambda s: PdfDrawingOptions(text=SheetText(title=s.title)),
    JsonOptions: lambda s: JsonOptions(),
    # The model is resolved before the input file is opened; the emitter only
    # cuts what quantisation and the pipeline already agreed on.
    StepOptions: lambda s: StepOptions(model=s.case_model, title=s.title),
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


def make_emitter(name: str, settings: OutputSettings) -> Emitter[DrillData]:
    """Resolve ``name`` through the registry and give it its options.

    A registered emitter is a conforming extension by definition; one whose
    constructor needs more than this CLI can supply is a usage failure, not an
    unexpected fault, so only the construction call itself is guarded — an
    emitter's later ``emit`` step keeps its own tracebacks.
    """
    emitter_cls = get_emitter(name)  # raises EmitterError for an unknown format
    options = _options_for(emitter_cls, settings)
    try:
        return emitter_cls() if options is None else emitter_cls(options)
    except TypeError as failure:
        raise UsageError(f"--emit {name}=...: cannot construct this emitter: {failure}") from failure


def settings_from(args: argparse.Namespace) -> OutputSettings:
    model: OcpCaseModel | None = getattr(args, "case_model_object", None)
    return OutputSettings(title=args.title, case_model=model)


def run_pipeline(
    pipeline: Pipeline[DrillData],
    data: DrillData,
    trace: Callable[[Stage[DrillData], DrillData, DrillData], None] | None = None,
) -> DrillData:
    """Run every stage through :meth:`Pipeline.run`, optionally tracing each."""
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
    """Report source metadata and both nominal and measured outline sizes."""
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
    """Report footprint, rotation and the selected part or ordered candidates."""
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


#: The keys ``CheckCaseClearance.describe`` records the plate and play area
#: under -- read back here the same way ``_tool_label`` reads ``standard``.
_PLATE_PARAMETER = "plate_nm"
_PLAY_AREA_PARAMETER = "play_area_nm"


def format_case(data: DrillData) -> list[str]:
    """Report the supplied model's identity, plate, and play area.

    Identity comes from ``data.case``, the typed registration a case check
    attaches. Plate and play area come from the clearance stage's own
    provenance, read through ``StageRun.get`` behind the same ``isinstance``
    idiom ``_tool_label`` uses for the drill standard: absent or malformed
    provenance degrades to fewer lines, never an exception -- this is the
    workspace's only human-facing reader of these facts, so it must not
    require a live, kernel-backed model to state them.
    """
    case = data.case
    if case is None:
        return []
    lines = ["", "CASE MODEL", _field("part", f"{case.part}  ({case.face.value})")]
    run = data.last_run(CheckCaseClearance.name)
    plate_nm = None if run is None else run.get(_PLATE_PARAMETER)
    if isinstance(plate_nm, int):
        lines.append(_field("plate", f"{format_nm(Nanometre(plate_nm))} mm"))
    play_area = None if run is None else run.get(_PLAY_AREA_PARAMETER)
    # Only the length is this guard's own to check: ``StageRun.__post_init__``
    # already runs ``check_nanometres`` over every element of any ``_nm``-suffixed
    # tuple (ADR-0004), so a stored ``play_area_nm`` can never carry a non-``int``
    # element -- only the wrong length, which nothing upstream constrains.
    if isinstance(play_area, tuple) and len(play_area) == 4:
        x0, y0, x1, y1 = (Nanometre(int(v)) for v in play_area)
        lines.append(
            _field(
                "play area",
                f"{format_nm(Nanometre(x1 - x0))} x {format_nm(Nanometre(y1 - y0))} mm"
                f"  |  x {format_nm(x0)}…{format_nm(x1)}"
                f"  y {format_nm(y0)}…{format_nm(y1)}",
            )
        )
    return lines


def format_holes(data: DrillData) -> list[str]:
    """Report nominal and measured holes, numbered through ``DrillData.numbered()``."""
    tools = data.tools()
    lines = [
        "",
        f"HOLES ({len(data.holes)})",
        "  No. Tool         X         Y      Dia  |      raw X      raw Y    raw Dia",
    ]
    for number, hole in data.numbered():
        lines.append(
            f"  {number:>3} T{tools[hole.diameter_nm]:<3} "
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


def _diameter_decimals(diameters: Iterable[Nanometre]) -> int:
    """Return the least 3–6 decimal places that distinguish all diameters."""
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


def _tool_label(data: DrillData) -> Callable[[Nanometre], str]:
    """Use the recorded standard's unique labels, or distinct millimetres."""
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
    """Report model tool counts using labels from recorded processing."""
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
    lines = format_source(data) + format_enclosure(data) + format_case(data) + format_holes(data)
    lines += format_tools(data)
    lines += format_diagnostics(data)
    return "\n".join(lines)


def format_stage(stage: Stage[DrillData], before: DrillData, after: DrillData) -> str:
    """One line of ``--verbose`` per-stage detail."""
    return _format_trace(stage.name, len(before.holes), before.diagnostics, after)


def format_phase(before: RawDrillData, after: DrillData) -> str:
    """Format quantisation using the same trace line as pipeline stages."""
    return _format_trace("quantise", len(before.holes), before.diagnostics, after)


def _format_trace(
    name: str, holes_before: int, diagnostics_before: tuple[Diagnostic, ...], after: DrillData
) -> str:
    """Format hole drops and diagnostic additions for one pipeline phase."""
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


def _render(
    emitters: Iterable[tuple[Emitter[DrillData], Path]], data: DrillData
) -> list[tuple[Emitter[DrillData], Path, Payload]]:
    """Render every artefact before any output path is written."""
    return [(emitter, path, emitter.emit(data)) for emitter, path in emitters]


#: One rendered artefact staged for commit: its emitter (for the report
#: line) beside the value ``stage_payload`` already wrote in full.
_Staged = tuple[Emitter[DrillData], StagedWrite]


def _stage(rendered: Iterable[tuple[Emitter[DrillData], Path, Payload]]) -> list[_Staged]:
    """Stage every payload through :func:`stompmodel.protocols.stage_payload`.

    No target path is touched here. A failure partway through discards
    every staged write this call already produced and re-raises, so a write
    failure on any one artefact leaves every target of the invocation
    exactly as it was — see ADR-0001. This is the set-level loop composed
    on top of `stompmodel`'s per-path mechanism; `stompdrill` states no
    temporary-file mechanism of its own.
    """
    staged: list[_Staged] = []
    try:
        for emitter, path, payload in rendered:
            staged.append((emitter, stage_payload(path, payload)))
    except BaseException:
        for _, written in staged:
            written.discard()
        raise
    return staged


@dataclass(frozen=True, slots=True)
class _Committed:
    """One target already swapped to this run's bytes during this loop.

    ``previous`` is the bytes this target held before this run, read
    before its own commit; ``None`` when the target did not exist before.
    :func:`_rollback` restores the two cases differently: rewrite one,
    delete the other.
    """

    path: Path
    previous: bytes | None


def _rollback(committed: list[_Committed]) -> None:
    """Undo every target already replaced earlier in this commit loop.

    Restores each target through the same published mechanism every other
    write in this loop uses — never a filesystem write of its own; see
    ADR-0005. Never raises: a target this cannot restore is the one
    residual ADR-0001 names as excluded from the guarantee, and
    swallowing it here keeps the failure that triggered the rollback the
    one that propagates.
    """
    for done in reversed(committed):
        try:
            if done.previous is None:
                done.path.unlink(missing_ok=True)
            else:
                stage_payload(done.path, done.previous).commit()
        except OSError:
            pass


def _commit(staged: list[_Staged]) -> list[str]:
    """Replace every target from its already-staged write, in order.

    ``pending`` holds exactly the staged writes not yet committed,
    including the one currently being attempted; a write leaves it only
    once its own :meth:`~stompmodel.protocols.StagedWrite.commit` returns. An
    existing target's prior bytes are read first, so they can be
    restored. On failure, :func:`_rollback` restores what this loop
    already replaced, and everything still in ``pending`` is discarded —
    this is what makes the whole set one transaction, not only each path.
    """
    lines: list[str] = []
    committed: list[_Committed] = []
    pending = list(staged)
    try:
        while pending:
            emitter, written = pending[0]
            previous = written.path.read_bytes() if written.path.exists() else None
            size = written.commit()
            pending.pop(0)
            committed.append(_Committed(written.path, previous))
            lines.append(f"wrote {written.path}  ({emitter.name}, {size} bytes)")
    except BaseException:
        _rollback(committed)
        for _, written in pending:
            written.discard()
        raise
    return lines


def _withheld(targets: Iterable[tuple[Emitter[DrillData], Path]]) -> list[str]:
    """Name every target withheld because ERROR diagnostics make output unsafe."""
    return ["wrote nothing: this run has errors, so these were not written:"] + [
        f"  {path}  ({emitter.name})" for emitter, path in targets
    ]


def _run(args: argparse.Namespace, out: TextIO) -> int:
    targets = [parse_emit(spec) for spec in args.emit]
    _preflight_targets(targets)

    # Everything the command line can get wrong is resolved before the input is
    # opened: a bad standard, an unstocked size, a grid that is not a number, a
    # part number in no catalogue, an unloadable case model and a form depth
    # below one level are all usage errors, not diagnostics. The last of these
    # is validated inside read_source, which builds the source before reading it.
    args.case_model_object = build_case_model(args)
    settings = settings_from(args)
    # Resolve every format before touching the input file: an unknown format is
    # a usage error and should not wait on a PDF parse to be reported.
    emitters = [(make_emitter(name, settings), path) for name, path in targets]

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

    trace: Callable[[Stage[DrillData], DrillData, DrillData], None] | None = None
    if args.verbose:
        print(format_phase(raw, data), file=out)

        def trace(stage: Stage[DrillData], before: DrillData, after: DrillData) -> None:
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
            for line in _commit(_stage(_render(emitters, data))):
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

    # Expected user-facing failures share one handler. Unexpected faults retain
    # their tracebacks rather than being classified as invalid input.
    try:
        return _run(args, sys.stdout)
    except (UsageError, StompError, OSError) as failure:
        print(f"{parser.prog}: error: {failure}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
