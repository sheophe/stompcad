"""The driver: executes a run's steps, holding each intermediate between them.

Spec decision 7 and ADR-0013: `stompcad` calls each phase separately, the same
calls and order `stompdrill.cli._run` and `stompcollider.cli._run` make.
Holding intermediates is what lets `retry` run one step again once an answer
arrives (decision 4), never retreating a reported position (decision 8).
Importing this module loads `stompgeom`, and through it OCP, by way of
`stompdrill`'s own emitters -- not a leak: the constraint binds what `stompcad`
reaches for, and it imports neither. Only `plan.py` stays tool-free.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Protocol, TypeVar

from stompcollider import (
    AssemblyEmitter,
    BoardSource,
    ReportEmitter,
    admit,
    board_geometry,
    build_pipeline,
    derived_tolerance,
    docked,
    parse_filter,
    registration,
)
from stompcollider.emitters.assembly import Solids
from stompcollider.model import DockData
from stompcollider.sources import BoardGeometry, BoardScan
from stompdrill.cad import OcpCaseModel, load_case_model
from stompdrill.emitters import available
from stompdrill.emitters.build import OutputSettings, make_emitter
from stompdrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    CheckCaseClearance,
    CheckOutlineContainment,
    Deduplicate,
    IdentifyHammondFootprint,
    ReviewGridTies,
    RouteHoles,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from stompdrill.quantise import RawDrillData, quantise
from stompdrill.sources import AiPdfSource
from stompmodel.diagnostics import Severity
from stompmodel.model import CaseFace, DrillData
from stompmodel.progress import Scope
from stompmodel.protocols import (
    Diagnosable,
    Emitter,
    Payload,
    Pipeline,
    Processable,
    Stage,
    commit_all,
    stage_all,
)
from stompmodel.units import nm_from_mm

from .plan import RunPlan, Step
from .present import Presentation

__all__ = ["DOCK_TARGET_NAMES", "RunOptions", "Driver"]

#: Every stompdrill CLI default this driver stands in for, since RunOptions
#: carries only what a run's caller resolves and stompdrill resolves the
#: rest from its own flags. Matching them is what makes byte identity hold.
_DEFAULT_GRID_MM = 0.25
_DEFAULT_CASE_FACE = CaseFace.BOX
_DEFAULT_CASE_MARGIN_MM = 1.0
_DEFAULT_TITLE = ""

#: stompcollider's own CLI defaults for the two flags RunOptions exposes no
#: override for; matching them is what makes the dock half's byte identity
#: hold the same way the drill half's does.
_SEAT_PITCH_MAX_MM = 2.0
_SEAT_PITCH_MIN_MM = 0.05

#: ``RunOptions.targets`` is one set naming both halves' outputs; a write
#: step renders only the names its own tool would recognise, so a caller
#: can ask for a drill format and a dock format in the one run without
#: either half choking on the other's name. Matches
#: ``stompcollider.cli``'s own fixed ``_REPORT``/``_ASSEMBLY`` pair.
#: Published rather than private: ``cli`` validates every requested target
#: against the union of both halves' names, and a name another module needs
#: is part of this one's surface.
DOCK_TARGET_NAMES = frozenset({"report", "assembly"})

#: Where the dock half's steps begin in the nine-step plan. One number,
#: because the two halves are drawn from one plan and one division of the
#: run's span -- see ``Driver._open``.
_DOCK_FROM = 4

#: What each step reads from ``RunOptions``. ``retry`` consults it to refuse
#: a revision the named step would never consult, and to name the step that
#: would have to run again for it to take effect. A step added to a plan is
#: a row added here; a field named by no row is honoured by no step.
_STEP_INPUTS: dict[str, frozenset[str]] = {
    "read-panel": frozenset({"panel", "case", "case_model"}),
    "quantise": frozenset({"case"}),
    "drill": frozenset(),
    "write-case": frozenset({"targets"}),
    "read-boards": frozenset({"boards", "panel_reference"}),
    "match": frozenset(),
    "seat": frozenset(),
    "clash": frozenset(),
    "write-assembly": frozenset({"targets"}),
}

#: What each step can honour when it runs *again*, which may be narrower
#: than what it reads the first time: a retry spends the intermediates the
#: driver holds rather than the inputs it re-read. ``read-boards`` re-runs
#: its filter over boards already scanned -- decision 8's own words -- so a
#: revised board list would need a parse this step no longer performs.
_RETRY_INPUTS: dict[str, frozenset[str]] = {
    "quantise": frozenset({"case"}),
    "drill": frozenset(),
    "read-boards": frozenset({"panel_reference"}),
}

#: What each step leaves on the driver. ``retry`` clears every attribute a
#: step later than the retried one left, reading the order from the plan
#: itself. The dock half holds the boards as read separately from the
#: boards as filtered, because a revised filter re-runs over the first
#: without needing the files the second was read from.
_STEP_HOLDS: dict[str, tuple[str, ...]] = {
    "read-panel": ("_case_model", "_raw"),
    "quantise": ("_quantised",),
    "drill": ("_drilled",),
    "read-boards": ("_scan", "_geometry", "_docked", "_dock_pipeline", "_dock_data"),
}


class _Written(Processable, Diagnosable, Protocol):
    """What a write step folds over: a pipeline's value, and its findings.

    ``Emitter`` binds ``Processable`` and the withhold rule reads the worst
    severity, so a write step's value is both of the shared protocols at
    once. Declared here because a ``TypeVar`` takes one bound, and neither
    protocol is restated: both halves' values satisfy them already.
    """


_DataT = TypeVar("_DataT", bound=_Written)


@dataclass(frozen=True, slots=True)
class RunOptions:
    """One run's resolved inputs, after arguments and before any file opens."""

    panel: Path
    boards: tuple[Path, ...]
    case: str | None
    case_model: Path | None
    panel_reference: str
    targets: tuple[tuple[str, Path], ...]


class Driver:
    """Runs one plan's steps over one set of options, one at a time.

    Each phase's result is kept on ``self`` rather than returned and
    discarded, so a later call can read what an earlier one produced
    without recomputing it -- which is what ``retry`` spends.
    """

    def __init__(self, plan: RunPlan, presentation: Presentation, options: RunOptions) -> None:
        self._plan = plan
        self._presentation = presentation
        self._options = options
        self._case_model: OcpCaseModel | None = None
        self._raw: RawDrillData | None = None
        self._quantised: DrillData | None = None
        self._drilled: DrillData | None = None
        self._scan: BoardScan | None = None
        self._geometry: dict[int, BoardGeometry] | None = None
        self._docked: DockData | None = None
        self._dock_pipeline: Pipeline[DockData] | None = None
        self._dock_data: DockData | None = None

    def run(self, scope: Scope) -> tuple[DrillData, DockData | None]:
        """Drill the panel, then dock its boards against it when any were asked for.

        ``run_dock`` reads the drill document the drill steps just held in
        memory, never written for this handoff alone. The one case that
        forces a temporary file is that ``BoardSource`` reads from a path,
        so the drill document and drilled case go to a temporary directory
        for it. An errored drill half stops the run there: CLAUDE.md's "any
        error prevents every requested output" binds the run between the
        two write steps as well as each of them.
        """
        docking = bool(self._options.boards)
        steps = self._plan.steps if docking else self._plan.steps[:_DOCK_FROM]
        slots = self._open(steps, scope)
        drilled = self._drill_steps(slots)
        if not docking:
            return drilled, None
        if drilled.worst_severity is Severity.ERROR:
            self._presentation.report(_undocked(self._targets_for(DOCK_TARGET_NAMES)))
            return drilled, None
        return drilled, self._dock_steps(drilled, slots)

    def run_drill(self, scope: Scope) -> DrillData:
        """Read, quantise and drill the panel, then write its case artefacts."""
        return self._drill_steps(self._open(self._plan.steps[:_DOCK_FROM], scope))

    def run_dock(self, drill: DrillData, scope: Scope) -> DockData:
        """Read the boards, match, seat and report clashes against the drilled case."""
        return self._dock_steps(drill, self._open(self._plan.steps[_DOCK_FROM:], scope))

    def retry(self, key: str, options: RunOptions, scope: Scope) -> DrillData | DockData:
        """Run one step again under revised options, and report it when it succeeds.

        Decision 4: the step that stopped to ask runs again when the answer
        arrives, reading neither the artwork nor the case model a second
        time. Only a step whose input this driver holds is retryable, only
        a revision that step can honour is accepted, and an accepted one
        discards every intermediate a later step produced.
        """
        retried, outcome = self._rerun(key, options, scope)
        self._presentation.finish_step(self._step(key), outcome)
        return retried

    def _rerun(self, key: str, options: RunOptions, scope: Scope) -> tuple[DrillData | DockData, str]:
        """The work of a retry, with its outcome returned rather than reported.

        A resolution loop asks and runs again until there is nothing left
        to ask, and must not credit the step in between -- so the caller
        decides when the step has finished, not this.
        """
        if key == "quantise":
            if self._raw is None:
                raise ValueError("quantise cannot run again before the panel is read")
            self._accept(key, options)
            self._quantised = self._quantise(scope)
            return self._quantised, _quantise_outcome(self._quantised)
        if key == "drill":
            if self._quantised is None:
                raise ValueError("drill cannot run again before quantisation")
            self._accept(key, options)
            self._drilled = self._drill(self._quantised, scope)
            return self._drilled, _drill_outcome(self._drilled)
        if key == "read-boards":
            if self._docked is None or self._scan is None:
                raise ValueError("read boards cannot run again before the boards are read")
            self._accept(key, options)
            self._dock_data = self._admit()
            return self._dock_data, f"{len(self._scan.raw.boards)} board(s)"
        raise ValueError(f"{key!r} is not a step this driver can run again")

    def _accept(self, key: str, options: RunOptions) -> None:
        """Take revised options for one step, once it is settled they can take effect."""
        self._refuse_unhonoured(key, options)
        self._discard_after(key)
        self._options = options

    def _refuse_unhonoured(self, key: str, options: RunOptions) -> None:
        """Refuse a revised field the named step does not read.

        ``retry`` takes a whole ``RunOptions``; a step reads part of it, so a
        field it never consults would be accepted and then ignored. Refused
        the way ``stompcollider`` refuses ``--place``: parsed, judged and
        rejected with the reason, naming the step that would have to run again
        for the revision to take effect. Every unhonourable field is named at
        once, as the target check names every bad format at once.
        """
        read = _RETRY_INPUTS.get(key, frozenset())
        unhonoured = [
            f"{field.name} ({self._reader(field.name)})"
            for field in fields(options)
            if field.name not in read
            and getattr(options, field.name) != getattr(self._options, field.name)
        ]
        if unhonoured:
            raise ValueError(
                f"{key!r} does not read {', '.join(unhonoured)}: a revision this step "
                "cannot honour is refused rather than accepted and ignored"
            )

    def _reader(self, name: str) -> str:
        """Which step of this run reads one option field, for a refusal to name."""
        for step in self._plan.steps:
            if name in _STEP_INPUTS.get(step.key, frozenset()):
                return f"read by {step.key!r}"
        return "read by no step in this run"

    def _discard_after(self, key: str) -> None:
        """Drop every intermediate a step later than this one left behind.

        Re-running a step supersedes what followed it: a value computed under
        the options being replaced would otherwise be read by a later call as
        though it agreed with them. The order is the plan's own step sequence,
        so a step inserted into ``RunPlan`` falls under the rule rather than
        quietly escaping a list written out here.
        """
        keys = [step.key for step in self._plan.steps]
        for later in keys[keys.index(key) + 1 :]:
            for attribute in _STEP_HOLDS.get(later, ()):
                setattr(self, attribute, None)

    def _open(self, steps: tuple[Step, ...], scope: Scope) -> Iterator[Scope]:
        """Announce the steps about to run, and divide the span among them once.

        One division and one ``begin`` per run, whichever halves it runs:
        dividing the same scope twice would leave the bar relying on the
        running maximum ``track()``'s scope keeps to stay monotonic, and
        would weigh a drill-only run against five steps it never intends
        to take.
        """
        plan = RunPlan(steps)
        self._presentation.begin(plan)
        return scope.parts(*plan.weights())

    def _step(self, key: str) -> Step:
        """The plan's step with this key. Raises ``KeyError`` for an unknown one."""
        for step in self._plan.steps:
            if step.key == key:
                return step
        raise KeyError(key)

    def _drill_steps(self, slots: Iterator[Scope]) -> DrillData:
        """The drill half's four steps, each drawing its slot as it starts.

        Slots are drawn lazily, one ``next()`` immediately before the step
        it belongs to -- a slot closes when the next is drawn, so drawing
        them all at once would close every one with no work done.
        """
        read_step = self._plan.steps[0]
        read_slot = next(slots)
        read_slot.label(read_step.label)
        self._read_panel(read_slot)
        self._presentation.finish_step(read_step, self._read_outcome())

        quantise_step = self._plan.steps[1]
        quantise_slot = next(slots)
        quantise_slot.label(quantise_step.label)
        self._quantised = self._quantise(quantise_slot)
        self._presentation.finish_step(quantise_step, _quantise_outcome(self._quantised))

        drill_step = self._plan.steps[2]
        drill_slot = next(slots)
        drill_slot.label(drill_step.label)
        self._drilled = self._drill(self._quantised, drill_slot)
        self._presentation.finish_step(drill_step, _drill_outcome(self._drilled))

        write_step = self._plan.steps[3]
        write_slot = next(slots)
        write_slot.label(write_step.label)
        written = self._write_case(self._drilled, write_slot)
        self._presentation.finish_step(write_step, ", ".join(written) or "nothing written")

        return self._drilled

    def _dock_steps(self, drill: DrillData, slots: Iterator[Scope]) -> DockData:
        """The dock half's five steps, drawn from the same division the drill half was."""
        read_step = self._plan.steps[4]
        read_slot = next(slots)
        read_slot.label(read_step.label)
        self._read_boards(drill, read_slot)
        self._dock_data = self._admit()
        assert self._scan is not None
        self._presentation.finish_step(read_step, f"{len(self._scan.raw.boards)} board(s)")

        assert self._dock_pipeline is not None
        for step, stage in zip(self._plan.steps[5:8], self._dock_pipeline, strict=True):
            slot = next(slots)
            slot.label(step.label)
            before = self._dock_data
            self._dock_data = Pipeline([stage]).run(before, slot)
            self._presentation.finish_step(step, _stage_outcome(before, self._dock_data))

        write_step = self._plan.steps[8]
        write_slot = next(slots)
        write_slot.label(write_step.label)
        assert self._geometry is not None
        written = self._write_dock(self._dock_data, self._scan, self._geometry, write_slot)
        self._presentation.finish_step(write_step, ", ".join(written) or "nothing written")

        return self._dock_data

    def _read_boards(self, drill: DrillData, scope: Scope) -> None:
        """Stage the drill document and the drilled case, then scan and compose.

        ``BoardSource`` reads both from real files, and neither is one
        this run already wrote: the drill document lives only in memory
        until a target asks for it, and the case is drilled only by the
        ``step`` emitter's own render. Both go to a private temporary
        directory, gone before this method returns, which is why the
        filter that needs no file is held separately in ``_admit``.
        """
        settings = OutputSettings(title=_DEFAULT_TITLE, case_model=self._case_model)
        with tempfile.TemporaryDirectory(prefix="stompcad-dock-") as tmp:
            tmp_path = Path(tmp)
            drill_path = tmp_path / "drill.json"
            drill_payload = make_emitter("json", settings).emit(drill)
            drill_path.write_text(_as_text(drill_payload), encoding="utf-8")
            case_path = tmp_path / "case.stp"
            case_path.write_bytes(_as_bytes(make_emitter("step", settings).emit(drill)))

            source = BoardSource(drill_path, list(self._options.boards), case_path)
            scan = source.scan(scope)
            tolerance_nm = derived_tolerance(scan.drill, drill_path)
            case = registration(scan, drill_path)
            self._scan = scan
            self._geometry = board_geometry(scan, case)
            self._docked = docked(scan, case)
            self._dock_pipeline = build_pipeline(
                tolerance_nm,
                scan.case.solids,
                {ordinal: board.solids for ordinal, board in self._geometry.items()},
                nm_from_mm(_SEAT_PITCH_MAX_MM),
                nm_from_mm(_SEAT_PITCH_MIN_MM),
            )

    def _admit(self) -> DockData:
        """Filter the boards already scanned, which needs no file to repeat.

        Decision 8: the gap this raises is found by a filter over boards
        already read, so running it again re-runs the filter and not the
        parse -- which is why the temporary the parse needed may be gone.
        """
        if self._docked is None:
            raise ValueError("the boards must be read before the filter runs")
        return admit(self._docked, parse_filter(self._options.panel_reference))

    def _read_panel(self, scope: Scope) -> None:
        """Load the artwork and, when named, the case model -- the read step's leaves."""
        read_leaves = scope.steps(2 if self._options.case_model is not None else 1)
        if self._options.case_model is not None:
            case_slot = next(read_leaves)
            case_slot.label("case model")
            self._case_model = load_case_model(
                self._options.case_model,
                face=_DEFAULT_CASE_FACE,
                margin_nm=nm_from_mm(_DEFAULT_CASE_MARGIN_MM),
                part=self._options.case,
            )
        artwork_slot = next(read_leaves)
        artwork_slot.label("artwork")
        source = AiPdfSource(self._options.panel)
        self._raw = source.read()
        next(read_leaves, None)  # exhaust: this is what closes the artwork leaf

    def _read_outcome(self) -> str:
        model = self._case_model
        return self._options.panel.name if model is None else (
            f"{self._options.panel.name}, {model.model_name}"
        )

    def _quantise(self, scope: Scope) -> DrillData:
        assert self._raw is not None  # _read_panel always runs first
        return quantise(
            self._raw,
            enclosure=IdentifyHammondFootprint(expected_part=self._options.case),
            diameters=SnapDiametersToDrillTable(DRILL_STANDARDS[DEFAULT_STANDARD]),
            positions=SnapPositions(nm_from_mm(_DEFAULT_GRID_MM)),
            scope=scope,
        )

    def _drill(self, data: DrillData, scope: Scope) -> DrillData:
        stages: list[Stage[DrillData]] = [
            Deduplicate(), ReviewGridTies(), RouteHoles(), CheckOutlineContainment()
        ]
        if self._case_model is not None:
            stages.append(CheckCaseClearance(self._case_model))
        return Pipeline(stages).run(data, scope)

    def _targets_for(self, names: frozenset[str]) -> list[tuple[str, Path]]:
        """This run's targets whose format one half owns, in the order requested."""
        return [(name, path) for name, path in self._options.targets if name in names]

    def _write_case(self, data: DrillData, scope: Scope) -> list[str]:
        """Render, stage and commit the drill half's own targets."""
        targets = self._targets_for(frozenset(available()))
        settings = OutputSettings(title=_DEFAULT_TITLE, case_model=self._case_model)
        return self._write(
            data,
            targets,
            lambda: [(make_emitter(name, settings), path) for name, path in targets],
            scope,
        )

    def _write_dock(
        self,
        data: DockData,
        scan: BoardScan,
        geometry: dict[int, BoardGeometry],
        scope: Scope,
    ) -> list[str]:
        """Render, stage and commit the dock half's own targets."""
        targets = self._targets_for(DOCK_TARGET_NAMES)
        return self._write(data, targets, lambda: _dock_emitters(targets, scan, geometry), scope)

    def _write(
        self,
        data: _DataT,
        targets: Sequence[tuple[str, Path]],
        emitters: Callable[[], Sequence[tuple[Emitter[_DataT], Path]]],
        scope: Scope,
    ) -> list[str]:
        """Render every target of one half, then stage and commit the whole set.

        Withholds every target on an error severity, before ``emitters`` is
        even called: CLAUDE.md states "any error prevents every requested
        output", and an emitter may legitimately refuse data this broken, so
        nothing is rendered rather than rendered and discarded. Staging and
        the whole-set transaction are ``stompmodel``'s (ADR-0001, ADR-0005);
        both halves reach them here, so no second write mechanism exists to
        lose the rollback ``commit_all`` provides.
        """
        if not targets:
            return []
        if data.worst_severity is Severity.ERROR:
            self._presentation.report(_withheld(targets))
            return []
        rendered: list[tuple[Emitter[_DataT], Path, Payload]] = []
        built = emitters()
        for (emitter, path), slot in zip(built, scope.steps(len(built)), strict=True):
            slot.label(emitter.name)
            rendered.append((emitter, path, emitter.emit(data)))
        staged = stage_all([(path, payload) for _emitter, path, payload in rendered])
        sizes = commit_all(staged)
        self._presentation.report([
            f"wrote {written.path}  ({emitter.name}, {size} bytes)"
            for (emitter, _path, _payload), written, size in zip(
                rendered, staged, sizes, strict=True
            )
        ])
        return [str(written.path) for written in staged]


def _dock_emitters(
    targets: Sequence[tuple[str, Path]], scan: BoardScan, geometry: dict[int, BoardGeometry]
) -> list[tuple[Emitter[DockData], Path]]:
    """One emitter per dock target, each given the geometry it writes.

    Mirrors ``stompcollider.cli._emitters``, including the assembly's
    timestamp: the case model's own, never a clock reading, because two
    runs over one input must agree byte for byte (ADR-0006).
    """
    case = Solids(scan.case.document, scan.case.solids)
    boards = {
        ordinal: Solids(board.document.document, board.solids)
        for ordinal, board in geometry.items()
    }
    built: list[tuple[Emitter[DockData], Path]] = []
    for name, path in targets:
        if name == "report":
            built.append((ReportEmitter(), path))
        else:
            built.append((AssemblyEmitter(case, boards, timestamp=scan.case.timestamp), path))
    return built


def _withheld(targets: Sequence[tuple[str, Path]]) -> list[str]:
    """Name every requested target withheld because an error makes its bytes unsafe.

    The one message both wrapped tools print for this case
    (``stompdrill.cli._withheld``, ``stompcollider.cli._withheld``),
    restated here so the driver refuses the same way rather than writing
    what either tool would not.
    """
    return ["wrote nothing: this run has errors, so these were not written:"] + [
        f"  {path}  ({name})" for name, path in targets
    ]


def _undocked(targets: Sequence[tuple[str, Path]]) -> list[str]:
    """Say why no board was read: the drill half's errors bind the whole run.

    Each write step already withholds its own targets, but a dock run over
    refused drill data would still read every board and seat it -- work
    whose only product is output this run may not write.
    """
    return ["docked nothing: this run's drill half has errors, so no board was read:"] + [
        f"  {path}  ({name})" for name, path in targets
    ]


def _quantise_outcome(data: DrillData) -> str:
    """What quantisation produced: the holes it accepted and the tools they need."""
    return f"{len(data.holes)} holes, {len(data.tools())} tools"


def _drill_outcome(data: DrillData) -> str:
    """What the drill pipeline left: the holes that survived every stage."""
    return f"{len(data.holes)} holes"


def _stage_outcome(before: DockData, after: DockData) -> str:
    """What one dock stage did: boards, placements, and any diagnostics it added."""
    added = len(after.diagnostics) - len(before.diagnostics)
    placements = sum(len(found) for found in after.placements.values())
    outcome = f"{len(after.boards)} board(s), {placements} placement(s)"
    return outcome if not added else f"{outcome}, +{added} diagnostic(s)"


def _as_text(payload: Payload) -> str:
    """A payload as text, for a format an emitter never renders to bytes."""
    return payload if isinstance(payload, str) else payload.decode("utf-8")


def _as_bytes(payload: Payload) -> bytes:
    """A payload as bytes, for a format an emitter never renders to text."""
    return payload if isinstance(payload, bytes) else payload.encode("utf-8")
