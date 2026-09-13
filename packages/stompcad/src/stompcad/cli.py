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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, TypeVar

from stompdrill.cli import parse_sizes
from stompdrill.emitters import available
from stompdrill.errors import UsageError as DrillUsageError
from stompmodel.diagnostics import (
    EXIT_CLEAN,
    EXIT_ERRORS,
    EXIT_USAGE,
    Severity,
    exit_for_severity,
)
from stompmodel.errors import StompError
from stompmodel.model import CaseFace
from stompmodel.progress import Sink, track
from stompmodel.protocols import check_target_set

from . import discover, manifest
from .cancel import EXIT_CANCELLED, Cancelled, CancellingSink
from .drive import DOCK_TARGET_NAMES, Driver, RunOptions
from .inline import InlineApp, TerminalPresentation
from .plan import DRILL_AND_DOCK
from .present import NoTerminal, PlainWriter, Presentation
from .readiness import Readiness, readiness
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

__all__ = [
    "UsageError",
    "Resolution",
    "build_parser",
    "parse_emit",
    "validate_targets",
    "resolve",
    "worst_severity",
    "choose_presentation",
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
    parser.add_argument(
        "--progress",
        choices=("bar", "steps", "tree"),
        default="bar",
        help="how much of the run to draw; 'v' cycles it while a run works; "
        "ignored without a terminal",
    )
    parser.add_argument(
        "--promote-warnings",
        action="store_true",
        help="raise every warning to an error when looking for a gap to ask about; "
        "the exit code, the withheld artefacts and the drill document are unchanged",
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

    def require_ready(self) -> None:
        """Raise a usage failure naming every blocker and the place that answers it."""
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

    Untyped by nature: a project file is JSON that ``manifest.read`` has
    checked structurally, not against each field's own type, so the caller
    still owns turning a raw declaration into the type ``Settings`` wants.
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


def _resolve_panel(args: argparse.Namespace, directory: Path) -> tuple[Path, Resolved[Path | None]]:
    """The panel: the argument if given, else the directory's one artwork file.

    None and several candidates are both usage failures naming what was
    found, because a headless run has nobody to ask; the workbench opens
    blocked on the same two states instead of pre-empting them here.
    """
    if args.panel is not None:
        panel = Path(args.panel)
        return panel, Resolved[Path | None](panel, Provenance(Origin.ARGUMENT))
    found = discover.panels(directory)
    if len(found) == 1:
        panel = found[0]
        return panel, Resolved[Path | None](panel, Provenance(Origin.DISCOVERED, "the artwork"))
    if not found:
        raise UsageError(f"no artwork (.ai) file found in {directory}; name one")
    names = ", ".join(path.name for path in found)
    raise UsageError(f"several artwork files found in {directory} ({names}); name one")


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

    ``manifest.read`` checks the key exists, not that its value means
    anything; a name outside the two the model knows is a usage error
    naming the project key, not a bare ``ValueError`` from deep inside a run.
    """
    if raw is None:
        return None
    try:
        return CaseFace(raw)
    except ValueError:
        raise UsageError(
            f"enclosure.case_face {raw!r} is not a drilled face; use one of: "
            + ", ".join(face.value for face in CaseFace)
        ) from None


def _validate_sizes(drilling: Drilling) -> None:
    """A malformed stocked-size list is a usage error, not a mid-run crash.

    Neither field is a flag on this parser, so the project file is the only
    rank that can carry user-typed text into them; ``drive.py``'s own
    narrowing mirrors ``stompdrill``'s parser but has no usage-error
    convention to raise through, which is why this boundary -- the one that
    has one, ahead of opening the artwork -- validates them instead.
    """
    for label, resolved in (
        ("drilling.drill_sizes", drilling.drill_sizes),
        ("drilling.no_drill_sizes", drilling.no_drill_sizes),
    ):
        if resolved.value is None:
            continue
        try:
            parse_sizes(resolved.value, label)
        except DrillUsageError as failure:
            raise UsageError(str(failure)) from failure


def resolve(args: argparse.Namespace, directory: Path) -> Resolution:
    """The four ranks, assembled once, with every disagreement carried.

    Order matters only in that discovery needs the panel before it can read
    the artwork's layers, and needs the case model before it can exclude it
    from the board candidates. Everything else is independent.
    """
    notes: list[str] = []
    panel, panel_resolved = _resolve_panel(args, directory)

    project = manifest.read(panel)
    notes.extend(project.notes)

    case_model_arg = None if args.case_model is None else Path(args.case_model)
    case_model_project = _project(project, "enclosure", "case_model")
    supplied_model = case_model_arg if case_model_arg is not None else case_model_project

    case_discovery: Discovery[str] | None = None
    if supplied_model is not None:
        inferred = discover.part_from_model(supplied_model)
        if inferred is not None:
            case_discovery = Discovery(inferred, f"inferred from {supplied_model.name}")

    case_resolved = _pick_noting(
        args.case, _project(project, "enclosure", "case"), case_discovery,
        DEFAULTS.enclosure.case.value, panel=panel, label="case", notes=notes,
    )
    # Locating the enclosure cache is separate work this run does not take
    # on (CLAUDE.md); a supplied model is the only rank that can be found
    # without it, so no discovery narrows a model left unnamed.
    case_model_resolved = _pick_noting(
        case_model_arg, case_model_project, None, DEFAULTS.enclosure.case_model.value,
        panel=panel, label="case model", notes=notes,
    )
    case_face_resolved = pick(
        None, _case_face(_project(project, "enclosure", "case_face")), None,
        DEFAULTS.enclosure.case_face.value,
    )
    case_margin_resolved = pick(
        None, _project(project, "enclosure", "case_margin_mm"), None,
        DEFAULTS.enclosure.case_margin_mm.value,
    )
    enclosure = Enclosure(
        case=case_resolved, case_model=case_model_resolved,
        case_face=case_face_resolved, case_margin_mm=case_margin_resolved,
    )

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
    form_depth_resolved = pick(
        None, _project(project, "artwork", "form_depth"), None, DEFAULTS.artwork.form_depth.value,
    )
    artwork = Artwork(
        panel=panel_resolved, drill_layer=drill_layer_resolved,
        reference_layer=reference_layer_resolved, form_depth=form_depth_resolved,
    )

    boards_arg = tuple(Path(board) for board in args.boards) if args.boards else None
    boards_project_raw = _project(project, "boards", "boards")
    boards_project = None if boards_project_raw is None else tuple(boards_project_raw)
    boards_discovery = Discovery(
        discover.board_candidates(panel.parent, panel, case_model_resolved.value), "found beside it",
    )
    boards_resolved = _pick_noting(
        boards_arg, boards_project, boards_discovery, DEFAULTS.boards.boards.value,
        panel=panel, label="boards", notes=notes,
    )
    boards_settings = BoardSettings(
        boards=boards_resolved,
        panel_reference=pick(
            args.panel_reference, _project(project, "boards", "panel_reference"), None,
            DEFAULTS.boards.panel_reference.value,
        ),
        match_tolerance_mm=pick(
            None, _project(project, "boards", "match_tolerance_mm"), None,
            DEFAULTS.boards.match_tolerance_mm.value,
        ),
        seat_pitch_max_mm=pick(
            None, _project(project, "boards", "seat_pitch_max_mm"), None,
            DEFAULTS.boards.seat_pitch_max_mm.value,
        ),
        seat_pitch_min_mm=pick(
            None, _project(project, "boards", "seat_pitch_min_mm"), None,
            DEFAULTS.boards.seat_pitch_min_mm.value,
        ),
    )

    targets_arg: tuple[tuple[str, Path], ...] | None = None
    if args.emit:
        parsed = [parse_emit(spec, panel) for spec in args.emit]
        validate_targets(parsed)
        try:
            check_target_set([path for _name, path in parsed])
        except ValueError as failure:
            raise UsageError(str(failure)) from failure
        targets_arg = tuple(parsed)
    targets_project_raw = _project(project, "output", "targets")
    targets_project = None if targets_project_raw is None else tuple(targets_project_raw)
    output = OutputSettings(
        targets=pick(targets_arg, targets_project, None, DEFAULTS.output.targets.value),
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
    _validate_sizes(drilling)

    settings = Settings(
        artwork=artwork, enclosure=enclosure, drilling=drilling,
        boards=boards_settings, output=output,
    )
    return Resolution(settings=settings, notes=tuple(notes), blockers=readiness(settings))


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
    resolved = resolve(args, Path.cwd())
    resolved.require_ready()
    options = RunOptions.of(resolved.settings)
    if not choose_presentation(out):
        return _compose(options, PlainWriter(out), promote_warnings=args.promote_warnings)
    app = InlineApp(level=args.progress)
    app.drive(
        lambda: _compose(
            options,
            TerminalPresentation(app),
            stop=lambda: app.stopping,
            promote_warnings=args.promote_warnings,
        )
    )
    code = app.run(inline=True, inline_no_clear=True)
    if app.failure is not None:
        # A fault carried out from the worker: raised here, unconditionally,
        # regardless of what ``code`` holds.
        raise app.failure
    if code is None:
        # The app exited without the run's own exit code. A stop the user
        # asked for earns 130; the app failing under the run is a processing
        # error, because decision 9 reserves 130 for the stop alone.
        return EXIT_CANCELLED if app.stopping else EXIT_ERRORS
    # A code the run itself earned.
    return code


def _compose(
    options: RunOptions,
    presentation: Presentation,
    stop: Callable[[], bool] | None = None,
    promote_warnings: bool = False,
) -> int:
    """One run, against whichever presentation is drawing it.

    ``promote_warnings`` travels beside the options rather than within
    them: decision 6 makes it a rule about which findings reach a picker,
    not an input any step reads, so no revision could ever honour it.
    """
    driver = Driver(DRILL_AND_DOCK, presentation, options, promote_warnings)
    sink: Sink = presentation if stop is None else CancellingSink(presentation, stop)
    with track(sink) as scope:
        drill, dock = driver.run(scope)
    return exit_for_severity(
        worst_severity([drill.worst_severity, None if dock is None else dock.worst_severity])
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
