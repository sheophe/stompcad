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

from stompdrill.cli import parse_case, parse_sizes
from stompdrill.emitters import available
from stompdrill.errors import UsageError as DrillUsageError
from stompdrill.pipeline import DRILL_STANDARDS
from stompdrill.sources import AiPdfSource
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
from stompmodel.units import Nanometre, nm_from_mm

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


def _validate_output(targets: Resolved[tuple[tuple[str, Path], ...]]) -> None:
    """Both target checks, over the set this run will actually write.

    ``validate_targets`` rejects a format neither half owns, and
    ``check_target_set`` two artefacts naming one file -- which ADR-0001's
    rollback assumes never happens, and which would otherwise leave one file
    on disk beside two claims of having written it.
    """
    where = "output.targets" if targets.provenance.origin is Origin.PROJECT else "--emit"
    validate_targets(targets.value, where)
    try:
        check_target_set([path for _name, path in targets.value])
    except ValueError as failure:
        raise UsageError(str(failure)) from failure


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


def resolve(args: argparse.Namespace, directory: Path) -> Resolution:
    """The four ranks, assembled once, with every disagreement carried.

    Three orderings are load-bearing. The panel comes first, because every
    other rank is read relative to it. Every value a user can type is then
    resolved and validated, before the first discovery opens the artwork:
    CLAUDE.md's "validate options before opening the artwork" has nowhere
    else to happen for a value carried only by a hand-edited project file.
    Discovery follows, needing the panel to read its layers and the case
    model to exclude it from the board candidates; and the targets are
    checked once resolved, because a project may supply them as readily as
    a flag may.
    """
    notes: list[str] = []
    panel, panel_resolved = _resolve_panel(args, directory)

    project = manifest.read(panel)
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

    targets_arg = tuple(parse_emit(spec, panel) for spec in args.emit) if args.emit else None
    targets_project_raw = _project(project, "output", "targets")
    targets_project = None if targets_project_raw is None else tuple(targets_project_raw)
    output = OutputSettings(
        targets=pick(targets_arg, targets_project, None, DEFAULTS.output.targets.value),
    )
    # Checked after resolution, not on ``--emit`` alone: the set that reaches
    # the write steps is the resolved one, whichever rank supplied it, and a
    # target set checked at a rank the run may not even use is no check at all.
    _validate_output(output.targets)

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
