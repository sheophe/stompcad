"""``stompcad``'s command line: what identifies the work, and nothing else.

Resolves the four ranks a run needs and validates every requested target
together, then opens the workbench on a terminal or drives the run through
the plain writer where there is none. Workbench decision 15: that second
path is the only one without an application, so the flags here are exactly
the facts that identify one piece of work. The exit convention is the four
codes both tools share, reduced from the worse of the two halves' findings,
plus the fifth, 130, for a run the user stopped.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO, TypeVar

from stompcollider.cli import parse_length as parse_dock_length
from stompcollider.cli import parse_pitches
from stompcollider.designators import parse_filter
from stompcollider.errors import UsageError as DockUsageError
from stompdrill.cli import build_case_model, parse_case, parse_face, parse_sizes
from stompdrill.cli import parse_length as parse_drill_length
from stompdrill.emitters import available
from stompdrill.errors import UsageError as DrillUsageError
from stompdrill.pipeline import DRILL_STANDARDS, SnapPositions
from stompdrill.sources import AiPdfSource
from stompmodel.diagnostics import EXIT_CLEAN, EXIT_USAGE, Severity, exit_for_severity
from stompmodel.errors import StompError
from stompmodel.model import CaseFace
from stompmodel.protocols import check_target_set, target_key
from stompmodel.units import Nanometre, nm_from_mm

from . import discover, manifest
from .cancel import EXIT_CANCELLED, Cancelled
from .drive import DOCK_TARGET_NAMES, Project, RunOptions, compose
from .plan import DRILL_AND_DOCK
from .present import NoTerminal, PlainWriter, Presentation
from .readiness import Blocker, Readiness, readiness
from .settings import (
    DEFAULTS,
    Artwork,
    BoardSettings,
    Discovery,
    Drilling,
    Enclosure,
    Origin,
    OutputSettings,
    Provenance,
    Resolved,
    Settings,
    pick,
)
from .stale import PLACE_OF_FIELD
from .workbench.app import Workbench
from .workbench.run import Launch
from .workbench.session import Session

__all__ = [
    "UsageError",
    "Resolution",
    "build_parser",
    "parse_emit",
    "validate_targets",
    "validate_place",
    "resolve",
    "blocked",
    "started_by_argument",
    "worst_severity",
    "has_terminal",
    "main",
]

_T = TypeVar("_T")


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
    parser.add_argument(
        "panel",
        metavar="PANEL.ai",
        nargs="?",
        default=None,
        help="Illustrator file to read; with none given, the sole .ai file "
        "in the working directory is used",
    )
    parser.add_argument(
        "boards",
        metavar="BOARD.stp",
        nargs="*",
        help="board models to seat in the drilled case; a drill-only run must say so "
        "explicitly, with an empty list declared in the project file",
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


def parse_emit(spec: str, panel: Path) -> tuple[str, Path]:
    """``"fmt"`` or ``"fmt=path"`` -> ``(fmt, path)``. The format is not checked here.

    A bare format takes its file from ``discover.output_path``'s naming
    scheme, beside ``panel``. A format that scheme does not know has no such
    answer; it keeps ``panel`` itself as a placeholder, because
    ``validate_targets`` rejects the name outright regardless of what path
    travels beside it.
    """
    name, separator, path = spec.partition("=")
    name = name.strip()
    if not name:
        raise UsageError(f"--emit expects FORMAT or FORMAT=PATH, got {spec!r}")
    if not separator:
        try:
            return (name, discover.output_path(name, panel))
        except KeyError:
            return (name, panel)
    if not path.strip():
        raise UsageError(f"--emit expects FORMAT=PATH, got {spec!r}")
    return (name, Path(path.strip()))


def _known_targets() -> frozenset[str]:
    """Every format either half can render -- the union the two write steps split."""
    return frozenset(available()) | DOCK_TARGET_NAMES


def validate_targets(targets: Sequence[tuple[str, Path]], where: str = "--emit") -> None:
    """Reject every unknown target format together, before any file opens.

    CLAUDE.md: "Validate all requested targets together before rendering."
    ``_write_case`` and ``_write_dock`` each filter to the names their own
    half owns; those two sets are disjoint, so a name outside their union
    would otherwise be silently dropped rather than reported. Collecting
    every bad name here, rather than raising on the first, is what makes one
    round trip enough for a caller who mistyped more than one. ``where``
    names the rank that asked, because a flag and a project key are edited
    in different places.
    """
    known = _known_targets()
    bad = sorted({name for name, _path in targets if name not in known})
    if bad:
        raise UsageError(
            f"{where}: unknown format(s) {', '.join(bad)}; available: {', '.join(sorted(known))}"
        )


def _validate_output(targets: Resolved[tuple[tuple[str, Path], ...]], panel: Path) -> None:
    """Every target check, over the set this run will actually write.

    ``validate_targets`` rejects a format neither half owns, and
    ``check_target_set`` two artefacts naming one file. The project file
    joins that set, compared by ``target_key`` rather than ``==`` because a
    ``..`` segment or a case variant still names it: a half commits it in
    the same transaction as its artefacts, so a second writer for that one
    path is exactly what ADR-0001's rollback assumes never happens.
    """
    where = "output.targets" if targets.provenance.origin is Origin.PROJECT else "--emit"
    validate_targets(targets.value, where)
    project = manifest.manifest_path(panel)
    project_key = target_key(project)
    if any(target_key(path) == project_key for _name, path in targets.value):
        raise UsageError(f"{where}: {project.name} is this panel's project file, not an artefact")
    try:
        check_target_set([path for _name, path in targets.value])
    except ValueError as failure:
        # Labelled on the way past, because the sentence is ``stompmodel``'s
        # and names paths rather than any flag or key of ours. Unlabelled,
        # ``_refused_place`` can only file it under the project -- a place
        # holding no values, so nothing a builder edits could discharge it.
        raise UsageError(f"{where}: {failure}") from failure


@dataclass(frozen=True, slots=True)
class Resolution:
    """What one invocation resolved, what it wants to say, and what blocks it.

    Resolving and refusing are separate because they answer different
    questions: the workbench opens on a resolution that is not ready and
    shows why, while a headless run turns the same blockers into exit 3.
    A ``resolve`` that raised could serve only the second.
    """

    settings: Settings
    notes: tuple[str, ...]
    blockers: Readiness
    project: manifest.Manifest = field(default_factory=manifest.Manifest)
    obstacle: str | None = None
    panel_candidates: tuple[Path, ...] = ()

    def require_ready(self) -> None:
        """Raise a usage failure naming every blocker and the place that answers it.

        The obstacle comes first because it is the one blocker that stops
        the rest from meaning anything: with no panel or no readable
        project, every other place is reporting on a project that does not
        exist yet.
        """
        if self.obstacle is not None:
            raise UsageError(self.obstacle)
        if self.blockers.ready:
            return
        raise UsageError(
            "this run is not ready:\n"
            + "\n".join(
                f"  {place}: {sentence}" for _blocker, place, sentence in self.blockers.blockers
            )
        )


def _project(project: manifest.Manifest, place: str, key: str) -> Any:
    """One declared value, or ``None`` where the project says nothing about it.

    Untyped by nature: ``manifest.read`` has checked each declaration's
    JSON shape, not what it means, so the caller still owns turning a
    string of the right shape into the face, part number or size list
    ``Settings`` carries.
    """
    return project.values.get(place, {}).get(key)


def _pick_noting(
    argument: _T | None,
    project: _T | None,
    discovered: Discovery[_T] | None,
    default: _T,
    *,
    panel: Path,
    label: str,
    notes: list[str],
) -> Resolved[_T]:
    """``pick``, plus the one note a declaration's own rank cannot raise itself.

    Spec decision 6: a declaration stands even where discovery found
    something else, so the disagreement becomes a note naming the file --
    never a silent re-pick, and never a note when nothing above the project
    overrode it, since that would just restate what discovery already
    considered and lost to a stronger rank.
    """
    resolved = pick(argument, project, discovered, default)
    if (
        resolved.provenance.origin is Origin.PROJECT
        and discovered is not None
        and discovered.value != resolved.value
    ):
        notes.append(
            f"{panel.name}: the project declares {label} {resolved.value!r}, "
            f"but {discovered.detail} is {discovered.value!r}"
        )
    return resolved


def _resolve_panel(
    args: argparse.Namespace, directory: Path
) -> tuple[Path | None, Resolved[Path | None], str | None, tuple[Path, ...]]:
    """The panel, how it was found, why there is none, and what else there was.

    Decision 6: none and several are states rather than failures. The
    workbench opens on `Artwork` stating what it found, and a path typed
    there starts the project; without a terminal the same two states become
    the usage code they always were, named by ``require_ready``.
    """
    if args.panel is not None:
        panel = Path(args.panel)
        return panel, Resolved[Path | None](panel, Provenance(Origin.ARGUMENT)), None, ()
    found = discover.panels(directory)
    if len(found) == 1:
        panel = found[0]
        return (
            panel,
            Resolved[Path | None](panel, Provenance(Origin.DISCOVERED, "the artwork")),
            None,
            (),
        )
    if not found:
        return (
            None,
            DEFAULTS.artwork.panel,
            f"no artwork (.ai) file in {directory}; choose one in Artwork",
            (),
        )
    names = ", ".join(path.name for path in found)
    return (
        None,
        DEFAULTS.artwork.panel,
        f"several artwork files here ({names}); choose one in Artwork",
        found,
    )


def _layer_discovery(panel: Path, conventional: str) -> Discovery[str] | None:
    """The conventional layer name, when the artwork carries it.

    A file that cannot yet be read -- a placeholder ahead of a real panel,
    or one the run will fail on regardless once it opens it for real --
    offers no opinion here rather than raising ahead of that step.
    """
    try:
        names = discover.layers(panel)
    except StompError:
        return None
    return Discovery(conventional, "found in the artwork") if conventional in names else None


def _case_face(raw: Any) -> CaseFace | None:
    """A project's drilled-face string as the enum ``Settings`` carries.

    ``stompdrill``'s own parser owns how the word is read -- which spellings
    it strips and lowers as well as which two names exist -- so a second
    reading here would accept what its flag refuses, or refuse what it
    accepts. Its sentence names that flag, which this command line has not
    got, so the prefix becomes the key the value was typed into.
    """
    if raw is None:
        return None
    try:
        return parse_face(str(raw))
    except DrillUsageError as failure:
        raise UsageError(
            str(failure).replace("--case-face", "enclosure.case_face", 1)
        ) from failure


def _validate_drilling(drilling: Drilling) -> None:
    """Build the drill table this run would use, and refuse it here if it cannot.

    The same three questions ``stompdrill``'s ``build_drill_standard``
    asks -- does the standard exist, do the sizes parse, does the narrowed
    table survive -- asked where a usage-error convention exists to answer
    them. ``drive.py`` narrows the table again under the real run, but by
    then the artwork is open and a bad value is a traceback rather than a
    usage failure naming the project key that carried it.
    """
    standard = DRILL_STANDARDS.get(drilling.drill_standard.value)
    if standard is None:
        raise UsageError(
            f"drilling.drill_standard {drilling.drill_standard.value!r} is not a drill "
            f"standard; available: {', '.join(DRILL_STANDARDS)}"
        )
    include = _selected_sizes(drilling.drill_sizes, "drilling.drill_sizes")
    exclude = _selected_sizes(drilling.no_drill_sizes, "drilling.no_drill_sizes")
    if include is None and exclude is None:
        return
    try:
        standard.select(include=include, exclude=exclude)
    except ValueError as failure:
        # The standard names itself and the sizes it holds; restating either
        # here would be a second answer to the same question.
        raise UsageError(str(failure)) from failure


def _selected_sizes(sizes: Resolved[str | None], label: str) -> tuple[Nanometre, ...] | None:
    """One declared size list in the exact nanometres a drill table is keyed by."""
    if sizes.value is None:
        return None
    try:
        return tuple(nm_from_mm(size) for size in parse_sizes(sizes.value, label))
    except DrillUsageError as failure:
        raise UsageError(str(failure)) from failure


def _validate_form_depth(panel: Path, form_depth: Resolved[int]) -> None:
    """A nesting depth the reader would reject, caught before it opens anything.

    Constructing the source is the check: ``AiPdfSource`` states the rule
    and applies it without touching the file, so the depth this run would
    read at is tested by the object that would read it.
    """
    try:
        AiPdfSource(panel, form_depth=form_depth.value)
    except ValueError as failure:
        raise UsageError(f"artwork.form_depth: {failure}") from failure


def _declared_case(raw: Any, label: str) -> str | None:
    """One rank's part number, as the catalogue spells it, or a usage failure.

    ``stompdrill`` owns which designators exist and what each normalises
    to, and its own command line hands the normalised form to the stage;
    a second spelling reaching the same stage from here would be a second
    answer. Its sentence names its own flag, so the project rank restates
    the prefix as the key the value was actually typed into.
    """
    if raw is None:
        return None
    try:
        return parse_case(str(raw))
    except DrillUsageError as failure:
        raise UsageError(str(failure).replace("--case", label, 1)) from failure


def _validate_panel_reference(panel_reference: Resolved[str]) -> None:
    """The dock half's own filter parser, asked of whichever rank answered.

    ``stompcollider`` states what a term may be, and states it for a caller
    that has opened nothing; left to the run it would first be asked over
    boards already read, on the far side of the drill half's commit. An
    unanswered filter is passed over rather than parsed: the empty default
    is the state ``readiness`` reports as a blocker, not a bad expression.
    """
    if not panel_reference.value:
        return
    where = (
        "--panel-reference"
        if panel_reference.provenance.origin is Origin.ARGUMENT
        else "boards.panel_reference"
    )
    try:
        parse_filter(panel_reference.value)
    except DockUsageError as failure:
        raise UsageError(f"{where}: {failure}") from failure


# The four checks below name every value as the project spells it. No flag of
# this command line carries any of these six numbers, so the project file is
# the only rank that can state one and the only place a refusal can send
# anybody; a flag added later brings its own name with it.


def _declared_length(millimetres: float, label: str) -> Nanometre:
    """One rank's millimetre value in the exact nanometres its tool works in.

    ``stompdrill``'s own conversion, which is where a value JSON can hold
    and no arithmetic can use -- an infinity -- stops being a length.
    """
    try:
        return parse_drill_length(millimetres, label)
    except DrillUsageError as failure:
        raise UsageError(str(failure)) from failure


def _validate_grid(drilling: Drilling) -> None:
    """Build the position snapping this run would use, and refuse it here if it cannot.

    ``stompdrill``'s command line resolves the same two values into a
    ``SnapPositions`` before it opens the artwork, so a pitch no grid can be
    spelled in, or a warning distance no hole can have moved less than, is a
    usage failure there. The threshold is checked against the pitch it was
    declared beside, because that is the pair the stage holds; building the
    pitch on its own first is what tells the two declarations apart.
    """
    grid_nm = _declared_length(drilling.grid_mm.value, "drilling.grid_mm")
    try:
        SnapPositions(grid_nm)
    except ValueError as failure:
        raise UsageError(f"drilling.grid_mm: {failure}") from failure
    warn_mm = drilling.grid_warn_mm.value
    if warn_mm is None:
        return
    warn_nm = _declared_length(warn_mm, "drilling.grid_warn_mm")
    try:
        SnapPositions(grid_nm, warn_nm)
    except ValueError as failure:
        raise UsageError(f"drilling.grid_warn_mm: {failure}") from failure


def _validate_case_margin(margin_mm: Resolved[float], face: CaseFace) -> None:
    """``stompdrill``'s own clearance check, asked with the model withheld.

    CLAUDE.md: the margin is refused whether or not a model was supplied,
    and naming no model is what leaves this call the check alone -- nothing
    is loaded and no geometry is touched. The face is the one this run
    resolved, already checked above, so the call states the run's own values.
    """
    try:
        build_case_model(
            argparse.Namespace(
                case_face=face.value,
                case_margin=margin_mm.value,
                case_model=None,
                case=None,
            )
        )
    except DrillUsageError as failure:
        raise UsageError(
            str(failure).replace("--case-margin", "enclosure.case_margin_mm", 1)
        ) from failure


def _validate_dock_lengths(
    tolerance_mm: Resolved[float | None],
    pitch_max_mm: Resolved[float],
    pitch_min_mm: Resolved[float],
) -> None:
    """The dock half's three lengths, checked by ``stompcollider``'s own parsers.

    Each is handed back as the text that command line would have carried,
    because those parsers are the single statement of the rules they hold: a
    recognition tolerance of nothing pairs no component with any hole, a scan
    step of nothing describes no scan, and a coarse step finer than the fine
    one describes no search. Their sentences name their own flags, so each
    prefix is restated as the key the value was actually typed into.
    """
    if tolerance_mm.value is not None:
        try:
            parse_dock_length(str(tolerance_mm.value), "boards.match_tolerance_mm")
        except DockUsageError as failure:
            raise UsageError(str(failure)) from failure
    try:
        parse_pitches(
            argparse.Namespace(
                seat_pitch_max=str(pitch_max_mm.value),
                seat_pitch_min=str(pitch_min_mm.value),
            )
        )
    except DockUsageError as failure:
        raise UsageError(
            str(failure)
            .replace("--seat-pitch-max", "boards.seat_pitch_max_mm")
            .replace("--seat-pitch-min", "boards.seat_pitch_min_mm")
        ) from failure


def validate_place(settings: Settings, place: str, panel: Path) -> None:
    """Every check the values of one place must pass, asked after an edit.

    The same helpers ``resolve`` runs before a headless run, dispatched by
    the place that owns the values. An edit is a new rank, and a rank
    reaching a step unchecked is what plan 1's validation block exists to
    prevent -- so nothing here states a rule; it asks the tool that owns one.
    """
    if place == "artwork":
        _validate_form_depth(panel, settings.artwork.form_depth)
    elif place == "enclosure":
        _declared_case(settings.enclosure.case.value, "enclosure.case")
        _validate_case_margin(settings.enclosure.case_margin_mm, settings.enclosure.case_face.value)
    elif place == "drilling":
        _validate_drilling(settings.drilling)
        _validate_grid(settings.drilling)
    elif place == "boards":
        _validate_panel_reference(settings.boards.panel_reference)
        _validate_dock_lengths(
            settings.boards.match_tolerance_mm,
            settings.boards.seat_pitch_max_mm,
            settings.boards.seat_pitch_min_mm,
        )
    elif place == "output":
        _validate_output(settings.output.targets, panel)


def resolve(args: argparse.Namespace, directory: Path) -> Resolution:
    """The four ranks, assembled once, with every disagreement carried.

    Three orderings are load-bearing. The panel comes first, because every
    other rank is read relative to it. Every value a user can type is
    resolved and validated before the first discovery opens the artwork,
    because CLAUDE.md's "validate options before opening the artwork" has
    nowhere else to happen for a hand-edited project file -- which is why
    the dock half's lengths and its designator filter resolve up there.
    The targets are checked last, once resolution has supplied them.
    """
    notes: list[str] = []
    panel, panel_resolved, missing, candidates = _resolve_panel(args, directory)
    if panel is None:
        assert missing is not None  # the only two branches with no panel both say why
        return Resolution(
            settings=DEFAULTS,
            notes=(),
            blockers=Readiness(((Blocker.NO_PANEL, "artwork", missing),)),
            obstacle=missing,
            panel_candidates=candidates,
        )

    try:
        project = manifest.read(panel)
    except manifest.ManifestError as failure:
        # Decision 9: a project whose declarations cannot be read is never
        # run under values that look like the user's own. Rank four for this
        # panel is not those values -- it is what every place states while
        # the file is unreadable, so the workbench stays readable throughout.
        return Resolution(
            settings=Settings.of_defaults(panel),
            notes=(),
            blockers=Readiness(((Blocker.UNREADABLE_PROJECT, "project", str(failure)),)),
            obstacle=str(failure),
        )
    notes.extend(project.notes)

    # Everything from here to the layer discovery below is typed text that
    # needs checking and no file to check it against -- most of it carried
    # by the project file alone, which is the only rank several of these
    # fields have. Nothing in this block may read the artwork.
    case_face_resolved = pick(
        None, _case_face(_project(project, "enclosure", "case_face")), None,
        DEFAULTS.enclosure.case_face.value,
    )
    drilling = Drilling(
        grid_mm=pick(None, _project(project, "drilling", "grid_mm"), None, DEFAULTS.drilling.grid_mm.value),
        grid_warn_mm=pick(
            None, _project(project, "drilling", "grid_warn_mm"), None,
            DEFAULTS.drilling.grid_warn_mm.value,
        ),
        drill_standard=pick(
            None, _project(project, "drilling", "drill_standard"), None,
            DEFAULTS.drilling.drill_standard.value,
        ),
        drill_sizes=pick(
            None, _project(project, "drilling", "drill_sizes"), None, DEFAULTS.drilling.drill_sizes.value,
        ),
        no_drill_sizes=pick(
            None, _project(project, "drilling", "no_drill_sizes"), None,
            DEFAULTS.drilling.no_drill_sizes.value,
        ),
        title=pick(None, _project(project, "drilling", "title"), None, DEFAULTS.drilling.title.value),
    )
    _validate_drilling(drilling)
    _validate_grid(drilling)
    form_depth_resolved = pick(
        None, _project(project, "artwork", "form_depth"), None, DEFAULTS.artwork.form_depth.value,
    )
    _validate_form_depth(panel, form_depth_resolved)

    # ``case`` is a declaration and has no discovered rank. A supplied
    # model's filename is a guess the drill stage tries against the
    # measurement, and only where a tie is otherwise undeclared; promoting
    # it here would hand that guess in as something the operator said, which
    # is an error where it disagrees rather than an ambiguity a picker can
    # still settle.
    case_resolved = pick(
        _declared_case(args.case, "--case"),
        _declared_case(_project(project, "enclosure", "case"), "enclosure.case"),
        None,
        DEFAULTS.enclosure.case.value,
    )
    case_model_arg = None if args.case_model is None else Path(args.case_model)
    case_model_project = _project(project, "enclosure", "case_model")
    # Locating the enclosure cache is separate work this run does not take
    # on (CLAUDE.md); a supplied model is the only rank that can be found
    # without it, so no discovery narrows a model left unnamed.
    case_model_resolved = _pick_noting(
        case_model_arg, case_model_project, None, DEFAULTS.enclosure.case_model.value,
        panel=panel, label="case model", notes=notes,
    )
    case_margin_resolved = pick(
        None, _project(project, "enclosure", "case_margin_mm"), None,
        DEFAULTS.enclosure.case_margin_mm.value,
    )
    _validate_case_margin(case_margin_resolved, case_face_resolved.value)
    enclosure = Enclosure(
        case=case_resolved, case_model=case_model_resolved,
        case_face=case_face_resolved, case_margin_mm=case_margin_resolved,
    )

    match_tolerance_resolved = pick(
        None, _project(project, "boards", "match_tolerance_mm"), None,
        DEFAULTS.boards.match_tolerance_mm.value,
    )
    seat_pitch_max_resolved = pick(
        None, _project(project, "boards", "seat_pitch_max_mm"), None,
        DEFAULTS.boards.seat_pitch_max_mm.value,
    )
    seat_pitch_min_resolved = pick(
        None, _project(project, "boards", "seat_pitch_min_mm"), None,
        DEFAULTS.boards.seat_pitch_min_mm.value,
    )
    _validate_dock_lengths(
        match_tolerance_resolved, seat_pitch_max_resolved, seat_pitch_min_resolved
    )
    panel_reference_resolved = pick(
        args.panel_reference, _project(project, "boards", "panel_reference"), None,
        DEFAULTS.boards.panel_reference.value,
    )
    _validate_panel_reference(panel_reference_resolved)

    drill_layer_resolved = _pick_noting(
        None, _project(project, "artwork", "drill_layer"),
        _layer_discovery(panel, DEFAULTS.artwork.drill_layer.value),
        DEFAULTS.artwork.drill_layer.value, panel=panel, label="drill layer", notes=notes,
    )
    reference_layer_resolved = _pick_noting(
        None, _project(project, "artwork", "reference_layer"),
        _layer_discovery(panel, DEFAULTS.artwork.reference_layer.value),
        DEFAULTS.artwork.reference_layer.value, panel=panel, label="reference layer", notes=notes,
    )
    artwork = Artwork(
        panel=panel_resolved, drill_layer=drill_layer_resolved,
        reference_layer=reference_layer_resolved, form_depth=form_depth_resolved,
    )

    boards_arg = tuple(Path(board) for board in args.boards) if args.boards else None
    boards_project_raw = _project(project, "boards", "boards")
    boards_project = None if boards_project_raw is None else tuple(boards_project_raw)
    # The boards have no discovered rank. A filename says nothing about what
    # a model holds -- a board, the enclosure, or an assembly exported under
    # a name of its own -- so a directory scan would dock whatever was in it.
    # ``discover.board_candidates`` still offers them to the picker, where
    # the builder is the one who says which are boards, and an unresolved
    # list is what ``readiness`` asks about.
    boards_resolved = _pick_noting(
        boards_arg, boards_project, None, DEFAULTS.boards.boards.value,
        panel=panel, label="boards", notes=notes,
    )
    boards_settings = BoardSettings(
        boards=boards_resolved,
        panel_reference=panel_reference_resolved,
        match_tolerance_mm=match_tolerance_resolved,
        seat_pitch_max_mm=seat_pitch_max_resolved,
        seat_pitch_min_mm=seat_pitch_min_resolved,
    )

    targets_arg = tuple(parse_emit(spec, panel) for spec in args.emit) if args.emit else None
    targets_project_raw = _project(project, "output", "targets")
    targets_project = None if targets_project_raw is None else tuple(targets_project_raw)
    output = OutputSettings(
        targets=pick(targets_arg, targets_project, None, DEFAULTS.output.targets.value),
    )
    # Checked after resolution, not on ``--emit`` alone: the set that reaches
    # the write steps is the resolved one, whichever rank supplied it, and a
    # target set checked at a rank the run may not even use is no check at all.
    _validate_output(output.targets, panel)

    settings = Settings(
        artwork=artwork, enclosure=enclosure, drilling=drilling,
        boards=boards_settings, output=output,
    )
    return Resolution(
        settings=settings, notes=tuple(notes), blockers=readiness(settings), project=project
    )


#: The one flag whose own name and the field it carries disagree: ``--emit``
#: writes ``output.targets``. Every other flag's ``dest`` is already the
#: field's name, which is what lets the table below be built rather than kept.
_FLAG_FIELDS: dict[str, str] = {"emit": "targets"}


def _refusal_labels() -> dict[str, str]:
    """Every label a refusal can name, and the place that owns that value.

    Built from the field table and the parser itself, so a key renamed or a
    flag added brings its own row. A copy written out here would send a
    builder to the wrong place exactly when it fell behind one of them.
    """
    labels = {f"{place}.{field}": place for field, place in PLACE_OF_FIELD.items()}
    for action in build_parser()._actions:
        place = PLACE_OF_FIELD.get(_FLAG_FIELDS.get(action.dest, action.dest))
        if place is not None:
            labels.update({flag: place for flag in action.option_strings})
    return labels


def _refused_place(sentence: str) -> str:
    """Which place owns the value a refusal names. Decision 6.

    Every validator prefixes its sentence with the label the value was typed
    into -- a project key, or the flag that carries it -- so the place is
    read from the refusal rather than guessed at. A sentence naming no label
    is the project's own, which is where a reader with nothing else to go on
    should start.
    """
    labels = _refusal_labels()
    for word in sentence.replace(",", " ").split():
        place = labels.get(word.strip(":;'\"()"))
        if place is not None:
            return place
    return "project"


def blocked(args: argparse.Namespace, directory: Path) -> Resolution:
    """``resolve``, with a refusal turned into something the workbench can show.

    Inside the application there is nowhere to exit to, so a refused value
    becomes an obstacle on the place that owns it rather than a message on a
    terminal about to be redrawn -- and the sidebar's marker is derived from
    that place, so naming the wrong one sends a builder somewhere with
    nothing to change. An unreadable project is decision 9's own case and
    keeps its own blocker, raised by ``resolve`` before this sees it.
    """
    try:
        return resolve(args, directory)
    except (UsageError, StompError, OSError) as failure:
        panel = None if args.panel is None else Path(args.panel)
        settings = DEFAULTS if panel is None else Settings.of_defaults(panel)
        return Resolution(
            settings=settings,
            notes=(),
            blockers=Readiness(
                ((Blocker.REFUSED_VALUE, _refused_place(str(failure)), str(failure)),)
            ),
            obstacle=str(failure),
        )


def started_by_argument(args: argparse.Namespace) -> bool:
    """Whether this invocation said "do not ask me". Decision 1.

    An argument is an act of intent in this invocation; a manifest value is
    a standing declaration. Bare ``stompcad tar.ai`` against a complete
    project therefore opens resolved and ready and starts nothing, so that
    opening last week's project to look at its artefacts costs no kernel
    work.
    """
    return bool(args.boards or args.emit or args.case or args.case_model or args.panel_reference)


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
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except (UsageError, NoTerminal, StompError, OSError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return EXIT_USAGE


def has_terminal(out: TextIO) -> bool:
    """Whether this stream can carry a workbench rather than streamed lines.

    Decision 15: a pipe, a dumb terminal or a CI runner gets the plain
    writer. ``CI`` present in the environment counts as no terminal **even
    with a tty attached**, because a runner that allocates a pty would
    otherwise be given a full-screen application and hang until it timed
    out -- and no flag should be required to avoid that. Presence rather
    than truth: a runner declaring ``CI=false`` is still a runner, and the
    variable's existence is the signal every runner agrees on.
    """
    if "CI" in os.environ:
        return False
    return out.isatty() and os.environ.get("TERM", "") not in ("", "dumb")


def _workbench_for(args: argparse.Namespace, directory: Path) -> Workbench:
    """The application this invocation opens, over whatever it resolved.

    The session reaches back here for both rules it cannot hold itself: a
    panel typed into `Artwork` resolves exactly as one named on the command
    line does, and an edit is refused by the tool that will consume it.
    """
    resolved = blocked(args, directory)
    session = Session(
        resolved,
        resolver=lambda path: blocked(
            argparse.Namespace(**{**vars(args), "panel": str(path)}), directory
        ),
        validator=lambda settings, place: validate_place(
            settings, place, settings.artwork.panel.value or Path()
        ),
    )
    panel = resolved.settings.artwork.panel.value
    return Workbench(
        session,
        launch=None if panel is None else Launch(panel=panel),
        autostart=started_by_argument(args),
    )


def _run(args: argparse.Namespace, out: TextIO) -> int:
    """Drive one project, in the workbench or through the plain writer.

    With a terminal the app owns the main thread for as long as the user
    wants it, and a run is an event inside it; the exit code is the last
    run's. Without one the run happens right here, and decision 15's step
    lines are the whole record -- which the workbench writes as it exits,
    so a run leaves its record behind either way.
    """
    directory = Path.cwd()
    if not has_terminal(out):
        resolved = resolve(args, directory)
        resolved.require_ready()
        panel = resolved.settings.artwork.panel.value
        assert panel is not None  # ``require_ready`` raises on a project with none
        return _compose(
            RunOptions.of(resolved.settings),
            PlainWriter(out),
            project=Project(panel, resolved.settings, resolved.project),
        )
    app = _workbench_for(args, directory)
    app.run()
    if app.failure is not None:
        # A fault carried into the app from the worker: raised here, where
        # ``main`` can map it, once the application has finished with it.
        raise app.failure
    for line in app.settled:
        out.write(f"{line}\n")
    return app.session.exit_code


def _compose(
    options: RunOptions,
    presentation: Presentation,
    stop: Callable[[], bool] | None = None,
    project: Project | None = None,
) -> int:
    """One run, against whichever presentation is drawing it, reduced to a code.

    Composing the run is ``drive.compose``'s, because the workbench reaches
    a run through the same call; what is left here is what a process does
    with one.
    """
    _driver, drill, dock = compose(DRILL_AND_DOCK, presentation, options, project, stop=stop)
    return exit_for_severity(
        worst_severity([drill.worst_severity, None if dock is None else dock.worst_severity])
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
