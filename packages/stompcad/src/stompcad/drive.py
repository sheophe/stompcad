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
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Protocol, TypeVar, cast

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
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.errors import StompError
from stompmodel.model import CaseFace, DrillData
from stompmodel.progress import Scope, Sink, track
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
from stompmodel.units import Nanometre, nm_from_mm

from . import cases
from .cancel import CancellingSink
from .manifest import DOCK_TARGET_NAMES, Half, Manifest, manifest_path, payload_for, read
from .plan import DRILL_AND_DOCK, RunPlan, Step
from .present import Choice, Presentation
from .resolve import RESOLVABLE, question_for, revision_for
from .settings import Origin, Provenance, Resolved, Settings
from .stale import PLACE_OF_FIELD, PLACE_ORDER, stale_steps

__all__ = [
    "DOCK_TARGET_NAMES", "RunOptions", "Driver", "Project", "compose",
    "plan_for", "invalidated", "steps_of_place", "readers_of",
]

#: Where the dock half's steps begin in the nine-step plan. One number,
#: because the two halves are drawn from one plan and one division of the
#: run's span -- see ``Driver._open``.
_DOCK_FROM = 4

#: What each step reads from ``RunOptions``. ``_RETRY_INPUTS`` narrows this to
#: what a step can honour from what it already holds; a step added to a plan
#: is a row added here, and a field named by no row is honoured by no step.
_STEP_INPUTS: dict[str, frozenset[str]] = {
    "read-panel": frozenset({
        "panel", "drill_layer", "reference_layer", "form_depth",
    }),
    "quantise": frozenset({
        "case", "case_model", "case_face", "case_margin_mm",
        "grid_mm", "grid_warn_mm", "drill_standard", "drill_sizes", "no_drill_sizes",
    }),
    "drill": frozenset(),
    "write-case": frozenset({"targets", "title"}),
    "read-boards": frozenset({
        "boards", "panel_reference", "title",
        "match_tolerance_mm", "seat_pitch_max_mm", "seat_pitch_min_mm",
    }),
    "match": frozenset(),
    "seat": frozenset(),
    "clash": frozenset(),
    "write-assembly": frozenset({"targets"}),
}

#: What each step can honour *without discarding what it holds*. Narrower than
#: ``_STEP_INPUTS`` only where a step's own intermediate would have to be
#: rebuilt: ``read boards`` re-runs its filter over boards already scanned, so
#: a revised board list needs the parse it no longer performs. Everything else
#: reads its inputs as it runs, so honouring and re-running are one call.
_RETRY_INPUTS: dict[str, frozenset[str]] = {
    "read-panel": frozenset(),
    "quantise": _STEP_INPUTS["quantise"],
    "drill": _STEP_INPUTS["drill"],
    "write-case": _STEP_INPUTS["write-case"],
    "read-boards": frozenset({"panel_reference"}),
    "write-assembly": _STEP_INPUTS["write-assembly"],
}

#: Steps that are never a retry target: they read no field, so no change makes
#: one of them the earliest stale step, and each is re-run by the step before
#: it. ``test_stale`` asserts the first half of that claim.
_STAGE_STEPS = frozenset({"match", "seat", "clash"})

#: The three stage steps in the order the dock pipeline holds them. A resume
#: can run one because ``_STEP_CONSUMES`` can make it stale; a retry cannot,
#: because a retry is driven by a revision and none of these reads a field.
_STAGE_ORDER: tuple[str, ...] = ("match", "seat", "clash")

#: The two steps whose findings a picker can answer. A resumed step must be
#: able to raise the same gap a first run does, so ``resume`` routes these
#: through ``_settled`` exactly as ``run`` and ``retry`` already do.
_RESOLVABLE_STEPS: frozenset[str] = frozenset(gap.step for gap in RESOLVABLE.values())

#: What each step leaves on the driver. The dock stages each rewrite
#: ``_dock_data``, so each declares it: a consumer is stale when an *earlier*
#: producer of what it reads is stale, and a stage that produced nothing by
#: this table could never make the stage after it stale.
_STEP_HOLDS: dict[str, tuple[str, ...]] = {
    "read-panel": ("_raw",),
    "quantise": ("_quantised", "_case_model"),
    "drill": ("_drilled",),
    "read-boards": ("_scan", "_geometry", "_docked", "_dock_pipeline", "_dock_data"),
    "match": ("_dock_data",),
    "seat": ("_dock_data",),
    "clash": ("_dock_data",),
}

#: What each step reads of what an earlier step left. With ``_STEP_HOLDS`` this
#: is the whole dependency: invalidation follows these edges rather than the
#: plan's order, because a write step produces nothing any later step reads and
#: must therefore invalidate nothing. See spec decision 10 for the cost of
#: getting this wrong.
_STEP_CONSUMES: dict[str, tuple[str, ...]] = {
    "read-panel": (),
    "quantise": ("_raw",),
    "drill": ("_quantised", "_case_model"),
    "write-case": ("_drilled", "_case_model"),
    "read-boards": ("_drilled", "_case_model"),
    "match": ("_dock_data", "_dock_pipeline"),
    "seat": ("_dock_data", "_dock_pipeline"),
    "clash": ("_dock_data", "_dock_pipeline"),
    "write-assembly": ("_dock_data", "_scan", "_geometry"),
}


def plan_for(boards: Sequence[Path], plan: RunPlan = DRILL_AND_DOCK) -> RunPlan:
    """The steps a run over these options would actually take. Decision 17.

    The one statement of where the two halves divide and of what decides
    it, so the roadmap plans the steps the driver will run rather than the
    nine a plan lists. ``_DOCK_FROM`` stays private: a caller outside has
    no business knowing where the division falls, only what it yields.
    """
    return plan if boards else RunPlan(plan.steps[:_DOCK_FROM])


def invalidated(changed: frozenset[str], plan: RunPlan = DRILL_AND_DOCK) -> frozenset[str]:
    """Every step a change to these fields invalidated, by data rather than position.

    The one public entry to this module's three tables. The workbench derives
    both its stale set and its roadmap from this call, so the sidebar cannot
    disagree with what a resume will actually run.
    """
    order = tuple(step.key for step in plan.steps)
    return stale_steps(order, changed, _STEP_INPUTS, _STEP_HOLDS, _STEP_CONSUMES)


def steps_of_place(place: str) -> frozenset[str]:
    """Every step reading a field this place owns.

    A step reading two places' fields belongs to both -- ``write case`` reads
    ``targets`` and ``title`` -- because the left marker asks whether this
    place's work has been done, not which place owns the step.
    """
    return frozenset(
        key
        for key, fields in _STEP_INPUTS.items()
        if any(PLACE_OF_FIELD.get(field) == place for field in fields)
    )


def readers_of(field: str) -> frozenset[str]:
    """Every step reading this field, which is the narrow half of ``invalidated``.

    Published beside it because the two answer different questions: what
    reads a value, and what a change to it invalidated. Only the second
    decides whether work already done still stands.
    """
    return frozenset(key for key, fields in _STEP_INPUTS.items() if field in fields)


class _Written(Processable, Diagnosable, Protocol):
    """What a write step folds over: a pipeline's value, and its findings.

    ``Emitter`` binds ``Processable`` and the withhold rule reads the worst
    severity, so a write step's value is both of the shared protocols at
    once. Declared here because a ``TypeVar`` takes one bound, and neither
    protocol is restated: both halves' values satisfy them already.
    """


_DataT = TypeVar("_DataT", bound=_Written)

#: Either half's data, so one resolution loop serves both.
_D = TypeVar("_D", DrillData, DockData)


@dataclass(frozen=True, slots=True)
class RunOptions:
    """One run's resolved inputs, flat because the driver's tables key on names.

    ``settings.Settings`` is the grouped, provenanced view a person reads;
    this is what a step consults. The derivation runs one way only: a
    nested record here would break ``_STEP_INPUTS``, ``_changed`` and
    ``resolve.revision_for`` at once.
    """

    panel: Path
    drill_layer: str
    reference_layer: str
    form_depth: int
    case: str | None
    case_model: Path | None
    case_face: CaseFace
    case_margin_mm: float
    grid_mm: float
    grid_warn_mm: float | None
    drill_standard: str
    drill_sizes: str | None
    no_drill_sizes: str | None
    title: str
    boards: tuple[Path, ...]
    panel_reference: str
    match_tolerance_mm: float | None
    seat_pitch_max_mm: float
    seat_pitch_min_mm: float
    targets: tuple[tuple[str, Path], ...]

    @staticmethod
    def of(settings: Settings) -> RunOptions:
        """Flatten the workbench's view into the driver's contract.

        A panel is optional there and required here, because ``readiness``
        refuses a run without one: representing "no panel" twice would let
        the two disagree.
        """
        panel = settings.artwork.panel.value
        if panel is None:
            raise ValueError("a run needs a panel; readiness() refuses one without")
        return RunOptions(
            panel=panel,
            drill_layer=settings.artwork.drill_layer.value,
            reference_layer=settings.artwork.reference_layer.value,
            form_depth=settings.artwork.form_depth.value,
            case=settings.enclosure.case.value,
            case_model=settings.enclosure.case_model.value,
            case_face=settings.enclosure.case_face.value,
            case_margin_mm=settings.enclosure.case_margin_mm.value,
            grid_mm=settings.drilling.grid_mm.value,
            grid_warn_mm=settings.drilling.grid_warn_mm.value,
            drill_standard=settings.drilling.drill_standard.value,
            drill_sizes=settings.drilling.drill_sizes.value,
            no_drill_sizes=settings.drilling.no_drill_sizes.value,
            title=settings.drilling.title.value,
            boards=settings.boards.boards.value,
            panel_reference=settings.boards.panel_reference.value,
            match_tolerance_mm=settings.boards.match_tolerance_mm.value,
            seat_pitch_max_mm=settings.boards.seat_pitch_max_mm.value,
            seat_pitch_min_mm=settings.boards.seat_pitch_min_mm.value,
            targets=settings.output.targets.value,
        )


@dataclass(frozen=True, slots=True)
class Project:
    """Where a half's declarations go, and what they say.

    ``held`` is what the file already declares, re-read after each commit so
    a second commit in one session leaves what the first recorded. Decision
    8: a value the manifest already holds is used and left untouched.
    """

    panel: Path
    settings: Settings
    held: Manifest


class Driver:
    """Runs one plan's steps over one set of options, one at a time.

    Each phase's result is kept on ``self`` rather than returned and
    discarded, so a later call can read what an earlier one produced
    without recomputing it -- which is what ``retry`` spends.
    """

    def __init__(
        self,
        plan: RunPlan,
        presentation: Presentation,
        options: RunOptions,
        project: Project | None = None,
        acquire: Callable[[str], Path] | None = None,
    ) -> None:
        self._plan = plan
        self._presentation = presentation
        self._options = options
        self._project = project
        # How a model is got hold of, so a test can hand one over without a
        # network and a run can fetch one without a builder.
        self._acquire: Callable[[str], Path] = (
            acquire if acquire is not None else cases.acquire
        )
        self._case_model: OcpCaseModel | None = None
        self._raw: RawDrillData | None = None
        self._quantised: DrillData | None = None
        self._drilled: DrillData | None = None
        self._scan: BoardScan | None = None
        self._geometry: dict[int, BoardGeometry] | None = None
        self._docked: DockData | None = None
        self._dock_pipeline: Pipeline[DockData] | None = None
        self._dock_data: DockData | None = None
        self._written: list[Path] = []

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
        steps = plan_for(self._options.boards, self._plan).steps
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

        Decision 4's own retry, generalised by decision 10's second half: a
        revision this step can honour from what it holds runs cheaply, and
        one it cannot discards that step's own holds and runs it as a first
        run would -- never refused and left accepted-but-ignored. ``match``,
        ``seat`` and ``clash`` read no field, so no revision ever names one
        of them; a step added to the plan is a row added to ``_rerun``.
        """
        retried, outcome, refreshed = self._rerun(key, options, scope)
        self._presentation.finish_step(self._step(key), outcome)
        for other_key, other_outcome in refreshed:
            self._presentation.finish_step(self._step(other_key), other_outcome)
        return retried

    def resume(self, stale: frozenset[str], options: RunOptions, scope: Scope) -> None:
        """Run every stale step, in the plan's own order, against what is held.

        Decision 10: changing a value marks steps stale and ``Ctrl+R`` runs
        that set. A resume takes only the steps a run would take: the dock
        half is dropped with no boards, and a dock step is never reached
        once the held drill data has an error, exactly where ``run`` itself
        stops. The span divides over what remains, so the position stays
        monotonic across a resume that takes less than the whole set.
        """
        self._adopt(options, stale)
        dock_keys = frozenset(step.key for step in self._plan.steps[_DOCK_FROM:])
        steps = tuple(
            step
            for step in plan_for(self._options.boards, self._plan).steps
            if step.key in stale
        )
        if not steps:
            return
        slots = self._open(steps, scope)
        for step in steps:
            if (
                step.key in dock_keys
                and self._drilled is not None
                and self._drilled.worst_severity is Severity.ERROR
            ):
                self._presentation.report(_undocked(self._targets_for(DOCK_TARGET_NAMES)))
                break
            slot = next(slots)
            slot.label(step.label)
            if step.key == "read-panel":
                # No cascade into ``quantise`` here: unlike a retry, a resume
                # already has ``quantise`` as its own stale step when one is
                # needed, so crediting it again from inside ``read-panel``
                # would double-credit it and could do so before a gap of its
                # own is resolved (ADR-0013's credit-only-once rule).
                self._read_panel(slot)
                self._presentation.finish_step(step, self._read_outcome())
                continue
            data, outcome, refreshed = self._run_step(step.key, slot)
            assert not refreshed, "read-panel's own cascade is bypassed above"
            if step.key in _RESOLVABLE_STEPS:
                # ``_run_step`` returns the union of both halves' data; ``key``
                # chose the branch, so the value is that resolvable step's own
                # type -- the same erasure ``_settled`` performs on its own
                # loop below, over ``_rerun``'s identical union return.
                if step.key == "quantise":
                    self._settled(step.key, cast(DrillData, data), outcome, slot)
                else:
                    self._settled(step.key, cast(DockData, data), outcome, slot)
            else:
                self._presentation.finish_step(step, outcome)

    def _rerun(
        self, key: str, options: RunOptions, scope: Scope
    ) -> tuple[DrillData | DockData, str, tuple[tuple[str, str], ...]]:
        """The work of a retry, with its outcome(s) returned rather than reported.

        A resolution loop runs again until nothing is left to ask, so the
        caller credits the step, not this call. The third element names
        every *other* step credited here too: only ``read-panel`` returns
        one, since it has nothing of ``DrillData``'s own shape to report, so
        it pays for ``quantise`` to run instead -- crediting the hold
        ``_STEP_HOLDS`` assigns there, since leaving it unpaid would make
        that claim silently false.
        """
        if key in _STAGE_STEPS:
            keys = [step.key for step in self._plan.steps]
            before = keys[keys.index(key) - 1]
            raise ValueError(
                f"{key!r} reads no field of its own -- retry {before!r} to run it again"
            )
        if key not in {step.key for step in self._plan.steps}:
            raise ValueError(f"{key!r} is not a step this driver can run again")
        self._precondition(key)
        self._accept(key, options)
        return self._run_step(key, scope)

    def _precondition(self, key: str) -> None:
        """Raise the one guard a step of this key must pass before it can run again.

        The only copy of each message: ``_rerun`` calls this ahead of
        ``_accept``, so a refused retry leaves no trace, and ``_run_step``
        calls it too, so a resume meets the same guard a first run would.
        Two copies once drifted -- a guard tightened in only one of them
        would let a retry's refusal arrive a call too late.
        """
        if key == "quantise" and self._raw is None:
            raise ValueError("quantise cannot run again before the panel is read")
        if key == "drill" and self._quantised is None:
            raise ValueError("drill cannot run again before quantisation")
        if key == "write-case" and self._drilled is None:
            raise ValueError("write case cannot run again before the panel is drilled")
        if key == "read-boards" and self._drilled is None:
            raise ValueError("read boards cannot run again before the panel is drilled")
        if key == "write-assembly" and (
            self._dock_data is None or self._scan is None or self._geometry is None
        ):
            raise ValueError("write assembly cannot run again before the boards are docked")

    def _run_step(
        self, key: str, scope: Scope
    ) -> tuple[DrillData | DockData, str, tuple[tuple[str, str], ...]]:
        """One step's work, under the options already in force.

        Split from ``_rerun`` because a retry and a resume disagree about
        what to discard and agree about everything else. Nothing here
        credits a step: the caller decides when a step has finished, which
        is what lets a resolution loop ask and run again in between.
        """
        if key == "read-panel":
            slots = scope.steps(2)
            self._read_panel(next(slots))
            outcome = self._read_outcome()
            self._quantised = self._quantise(next(slots))
            return self._quantised, outcome, (
                ("quantise", _quantise_outcome(self._quantised, self._case_model)),
            )
        if key in _STAGE_ORDER:
            if self._dock_data is None or self._dock_pipeline is None:
                raise ValueError(f"{key!r} cannot run before the boards are read")
            before = self._dock_data
            stage = self._dock_pipeline[_STAGE_ORDER.index(key)]
            self._dock_data = Pipeline([stage]).run(before, scope)
            return self._dock_data, _stage_outcome(before, self._dock_data), ()
        self._precondition(key)
        if key == "quantise":
            assert self._raw is not None
            self._quantised = self._quantise(scope)
            return self._quantised, _quantise_outcome(self._quantised, self._case_model), ()
        if key == "drill":
            assert self._quantised is not None
            self._drilled = self._drill(self._quantised, scope)
            return self._drilled, _drill_outcome(self._drilled), ()
        if key == "write-case":
            assert self._drilled is not None
            written = self._write_case(self._drilled, scope)
            return self._drilled, ", ".join(written) or "nothing written", ()
        if key == "read-boards":
            assert self._drilled is not None
            if self._docked is None:  # the scan was discarded: parse again
                self._read_boards(self._drilled, scope)
            self._dock_data = self._admit()
            assert self._scan is not None
            return self._dock_data, f"{len(self._scan.raw.boards)} board(s)", ()
        if key == "write-assembly":
            assert self._dock_data is not None
            assert self._scan is not None
            assert self._geometry is not None
            written = self._write_dock(self._dock_data, self._scan, self._geometry, scope)
            return self._dock_data, ", ".join(written) or "nothing written", ()
        raise ValueError(f"{key!r} is not a step this driver can run again")

    def _settled(self, key: str, data: _D, outcome: str, scope: Scope) -> _D:
        """Resolve what this step can be asked about, then credit it.

        Decision 4: a step that stops to ask has not completed, so nothing
        is reported until either there was nothing to ask or the answer
        has been applied. Repeated gaps are answered in turn and the step
        is credited once, with the outcome the successful run earned.
        """
        while (gap := self._gap_in(data)) is not None:
            question, diagnostic = gap
            answer = self._presentation.ask(question)
            revised = revision_for(diagnostic, self._options, answer)
            self._declare(revised)
            # ``_rerun`` returns the union of both halves' data; ``key`` chose
            # the branch, so the value is this step's own type.
            reran, outcome, refreshed = self._rerun(key, revised, scope)
            assert not refreshed, "a resolvable step must not refresh another step's hold"
            data = cast(_D, reran)
        self._presentation.finish_step(self._step(key), outcome)
        return data

    def _declare(self, options: RunOptions) -> None:
        """Record an answered gap where the manifest reads its declarations.

        Decision 8 records the values that produced the artefacts, and the
        payload is derived from ``Project.settings`` rather than from the
        options a revision changed. Recording the answer only in the options
        would leave the field declared as the gap it started as -- and, being
        held, never corrected: the question would return on every open.
        """
        project = self._project
        if project is None:
            return
        settings = project.settings
        for name in sorted(self._changed(options)):
            place = PLACE_OF_FIELD[name]
            record = getattr(settings, place)
            answered = Resolved(getattr(options, name), Provenance(Origin.USER))
            settings = replace(settings, **{place: replace(record, **{name: answered})})
        self._project = replace(project, settings=settings)

    def declare(self, settings: Settings) -> None:
        """The values a further commit records, keeping what a gap already answered.

        Decision 8: a half's declarations are the values that produced its
        artefacts, so a resume under revised values records the revised
        ones. An answered gap is such a value and is recorded nowhere else,
        so it survives here unless the user has since set that field
        themselves -- and ``held`` still protects everything already written.
        """
        project = self._project
        if project is None:
            return
        self._project = replace(project, settings=_kept(project.settings, settings))

    def _gap_in(self, data: Diagnosable) -> tuple[Choice, Diagnostic] | None:
        """The first gap in this data that a picker could resolve, if any."""
        for diagnostic in data.diagnostics:
            question = question_for(diagnostic, self._board_designators())
            if question is not None:
                return question, diagnostic
        return None

    def _board_designators(self) -> dict[int, tuple[str, ...]]:
        """Each board's own names, for a gap that carries only its board."""
        if self._docked is None:
            return {}
        return {board.ordinal: board.designators for board in self._docked.boards}

    def _changed(self, options: RunOptions) -> frozenset[str]:
        """Which fields this revision alters, against the options now in force."""
        return frozenset(
            field.name
            for field in fields(options)
            if getattr(options, field.name) != getattr(self._options, field.name)
        )

    def _accept(self, key: str, options: RunOptions) -> None:
        """Take revised options for one step, discarding what they supersede.

        A value computed under the options being replaced would otherwise be
        read by a later call as though it agreed with them. Where the revision
        is one this step cannot honour from what it holds, its own
        intermediates go too -- which is what makes the next call a first run
        rather than a retry.
        """
        self._discard_after(key)
        if not self._changed(options) <= _RETRY_INPUTS.get(key, frozenset()):
            for attribute in _STEP_HOLDS.get(key, ()):
                setattr(self, attribute, None)
        self._options = options

    def _adopt(self, options: RunOptions, stale: frozenset[str]) -> None:
        """Take revised options for a step set already known to be stale.

        Narrower than ``_accept``, which assumes everything after its one
        step is superseded: a resume gets the whole ``_STEP_CONSUMES`` set
        already computed, so nothing outside it is invalid. A step's holds
        clear where it cannot honour a changed field, or where an earlier
        step also in ``stale`` produces what it consumes -- read boards is
        stale by consumption alone when the panel is re-drilled, and its
        scan must not outlive that.
        """
        changed = self._changed(options)
        order = [step.key for step in self._plan.steps]
        for key in stale:
            relevant = changed & _STEP_INPUTS.get(key, frozenset())
            cannot_honour = bool(relevant) and not relevant <= _RETRY_INPUTS.get(key, frozenset())
            consumed = set(_STEP_CONSUMES.get(key, ()))
            superseded = any(
                earlier in stale and consumed.intersection(_STEP_HOLDS.get(earlier, ()))
                for earlier in order[: order.index(key)]
            )
            if cannot_honour or superseded:
                for attribute in _STEP_HOLDS.get(key, ()):
                    setattr(self, attribute, None)
        self._options = options

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
        quantised = self._quantise(quantise_slot)
        self._quantised = self._settled(
            "quantise", quantised, _quantise_outcome(quantised, self._case_model), quantise_slot
        )

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
        admitted = self._admit()
        assert self._scan is not None
        self._dock_data = self._settled(
            "read-boards", admitted, f"{len(self._scan.raw.boards)} board(s)", read_slot
        )

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
        options = self._options
        settings = OutputSettings(title=options.title, case_model=self._case_model)
        with tempfile.TemporaryDirectory(prefix="stompcad-dock-") as tmp:
            tmp_path = Path(tmp)
            drill_path = tmp_path / "drill.json"
            drill_payload = make_emitter("json", settings).emit(drill)
            drill_path.write_text(_as_text(drill_payload), encoding="utf-8")
            case_path = tmp_path / "case.stp"
            case_path.write_bytes(_as_bytes(make_emitter("step", settings).emit(drill)))

            source = BoardSource(drill_path, list(options.boards), case_path)
            scan = source.scan(scope)
            tolerance_nm = (
                derived_tolerance(scan.drill, drill_path)
                if options.match_tolerance_mm is None
                else nm_from_mm(options.match_tolerance_mm)
            )
            case = registration(scan, drill_path)
            self._scan = scan
            self._geometry = board_geometry(scan, case)
            self._docked = docked(scan, case)
            self._dock_pipeline = build_pipeline(
                tolerance_nm,
                scan.case.solids,
                {ordinal: board.solids for ordinal, board in self._geometry.items()},
                nm_from_mm(options.seat_pitch_max_mm),
                nm_from_mm(options.seat_pitch_min_mm),
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
        """Load the artwork -- the read step's one leaf.

        The model is not read here. Which enclosure this panel is may only be
        known once its outline has been matched, so the file that the part
        names is opened where the part is decided.
        """
        options = self._options
        read_leaves = scope.steps(1)
        artwork_slot = next(read_leaves)
        artwork_slot.label("artwork")
        source = AiPdfSource(
            options.panel,
            drill_layer=options.drill_layer,
            reference_layer=options.reference_layer,
            form_depth=options.form_depth,
        )
        self._raw = source.read()
        next(read_leaves, None)  # exhaust: this is what closes the artwork leaf

    def _read_outcome(self) -> str:
        return self._options.panel.name

    def _quantise(self, scope: Scope) -> DrillData:
        assert self._raw is not None  # _read_panel always runs first
        options = self._options
        standard = DRILL_STANDARDS[options.drill_standard]
        include = _selected_sizes(options.drill_sizes)
        exclude = _selected_sizes(options.no_drill_sizes)
        if include is not None or exclude is not None:
            standard = standard.select(include=include, exclude=exclude)
        warn_over_nm = None if options.grid_warn_mm is None else nm_from_mm(options.grid_warn_mm)
        # Every attempt opens its own model, so every attempt starts without
        # one. An attempt that identifies nothing returns below without
        # reaching ``_open_model``, and a retry honoured from what this step
        # holds keeps its holds -- so the attempt before it would otherwise
        # still be naming a file for a part this panel has just been declared
        # not to be, for the three steps that read it.
        self._case_model = None
        leaves = scope.steps(2)
        identify = next(leaves)
        identify.label("enclosure")
        data = quantise(
            self._raw,
            enclosure=IdentifyHammondFootprint(
                expected_part=options.case, case_model=options.case_model
            ),
            diameters=SnapDiametersToDrillTable(standard),
            positions=SnapPositions(nm_from_mm(options.grid_mm), warn_over_nm),
            scope=identify,
        )
        if data.worst_severity is Severity.ERROR:
            # Nothing is credited while a question is outstanding: drawing the
            # next leaf closes this one, and ADR-0013 forbids crediting a step
            # before its gap is answered. A tie is answered, this runs again,
            # and the chosen part's model is opened on that attempt.
            return data
        model_slot = next(leaves)  # closes the identification leaf
        model_slot.label("case model")
        opened = self._open_model(data, model_slot)
        next(leaves, None)  # exhaust: this is what closes the model leaf
        return opened

    def _open_model(self, data: DrillData, scope: Scope) -> DrillData:
        """Acquire and load the enclosure model this run needs, if any.

        The cache holds one file per designator, so the part identified here
        is what names the file, and a path the command line supplied is loaded
        whatever the run produces. A model that cannot be had is an ERROR on
        the data, which is what withholds every artefact: half a description
        of a panel is worse than none.
        """
        options = self._options
        part = _model_part(options.case, data)
        # A path the operator named costs no download and was asked for by
        # name, so needing a model does not gate it: ``stompdrill`` given that
        # flag checks clearance, and this must produce what that produces.
        if options.case_model is None and (part is None or not _needs_model(options)):
            return data
        leaves = scope.steps(2)
        acquiring = next(leaves)
        acquiring.label("acquiring" if part is None else f"acquiring {part}")
        path = options.case_model
        if path is None:
            assert part is not None  # the branch above returned without one
            try:
                path = self._acquire(part)
            except cases.ModelUnavailable as failure:
                return replace(
                    data, diagnostics=data.diagnostics + (_unavailable(part, failure),)
                )
        loading = next(leaves)  # closes the acquiring leaf
        loading.label(f"loading {path.name}")
        try:
            self._case_model = load_case_model(
                path,
                face=options.case_face,
                margin_nm=nm_from_mm(options.case_margin_mm),
                # The part that keyed the file, not the declaration that may be
                # absent: a model acquired for an identified part would
                # otherwise be identified again from its own STEP names.
                part=part if part is not None else options.case,
            )
        except (OSError, StompError) as failure:
            return replace(
                data,
                diagnostics=data.diagnostics + (_unavailable(part or path.stem, failure),),
            )
        next(leaves, None)  # exhaust: this is what closes the loading leaf
        return data

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

    def _declaration(self, half: Half) -> tuple[Path, Payload] | None:
        """This half's project file, or ``None`` where it adds nothing new."""
        if self._project is None:
            return None
        payload = payload_for(
            self._project.panel, self._project.settings, half, self._project.held
        )
        if payload is None:
            return None
        return manifest_path(self._project.panel), payload

    def _write_case(self, data: DrillData, scope: Scope) -> list[str]:
        """Render, stage and commit the drill half's own targets."""
        targets = self._targets_for(frozenset(available()))
        settings = OutputSettings(title=self._options.title, case_model=self._case_model)
        # Spec decision 17: with no boards, the dock half never runs, so this
        # is the only commit that can record the confirmed empty board list.
        half = Half.DRILL_ONLY if not self._options.boards else Half.DRILL
        return self._write(
            data,
            targets,
            lambda: [(make_emitter(name, settings), path) for name, path in targets],
            scope,
            half,
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
        return self._write(
            data, targets, lambda: _dock_emitters(targets, scan, geometry), scope, Half.DOCK
        )

    def _write(
        self,
        data: _DataT,
        targets: Sequence[tuple[str, Path]],
        emitters: Callable[[], Sequence[tuple[Emitter[_DataT], Path]]],
        scope: Scope,
        half: Half,
    ) -> list[str]:
        """Render this half's targets, then stage and commit them with its declaration.

        Withholds every target on an error severity, before ``emitters`` runs:
        CLAUDE.md's "any error prevents every requested output" holds, and an
        emitter may refuse data this broken, so nothing is rendered rather than
        rendered and discarded. Decision 8: the declaration joins the same
        transaction as the artefacts, so a committed file never sits beside a
        project file that fails to describe it. Staging and the commit stay
        ``stompmodel``'s (ADR-0001, ADR-0005); no second write path exists.
        """
        declaration = self._declaration(half)
        if not targets and declaration is None:
            return []
        if data.worst_severity is Severity.ERROR:
            if targets:
                self._presentation.report(_withheld(targets))
            return []
        rendered: list[tuple[Emitter[_DataT], Path, Payload]] = []
        built = emitters() if targets else []
        for (emitter, path), slot in zip(built, scope.steps(len(built)), strict=True):
            slot.label(emitter.name)
            rendered.append((emitter, path, emitter.emit(data)))
        entries: list[tuple[Path, Payload]] = [(path, payload) for _e, path, payload in rendered]
        if declaration is not None:
            entries.append(declaration)
        staged = stage_all(entries)
        sizes = commit_all(staged)
        if declaration is not None and self._project is not None:
            # Re-read rather than merge in memory: the file on disk is what
            # the next commit must leave untouched, and it is the only thing
            # that knows what this commit actually added.
            self._project = replace(self._project, held=read(self._project.panel))
        artefacts = staged[: len(rendered)]
        self._written.extend(written.path for written in artefacts)
        self._presentation.report([
            f"wrote {written.path}  ({emitter.name}, {size} bytes)"
            for (emitter, _path, _payload), written, size in zip(
                rendered, artefacts, sizes[: len(rendered)], strict=True
            )
        ])
        return [str(written.path) for written in artefacts]

    @property
    def written(self) -> tuple[Path, ...]:
        """Every artefact this driver committed, in the order it committed them.

        The `Output` place labels a file it made differently from one it
        merely found (decision 2), and nothing else in the process knows
        which is which.
        """
        return tuple(self._written)

    @property
    def findings(self) -> tuple[Diagnostic, ...]:
        """Both halves' diagnostics, as the run stands now.

        Read after a resume, which hands back no half's value: the
        `Findings` place must show what this run found rather than what the
        run before it did.
        """
        found: list[Diagnostic] = []
        if self._drilled is not None:
            found.extend(self._drilled.diagnostics)
        if self._dock_data is not None:
            found.extend(self._dock_data.diagnostics)
        return tuple(found)

    @property
    def designators(self) -> dict[int, tuple[str, ...]]:
        """Each board's own names, once the boards have been read.

        Empty before ``read boards``, which is why ``panel_reference`` is
        typed until a run has read a board and ticked afterwards.
        """
        return self._board_designators()


def compose(
    plan: RunPlan,
    presentation: Presentation,
    options: RunOptions,
    project: Project | None = None,
    stop: Callable[[], bool] | None = None,
    acquire: Callable[[str], Path] | None = None,
) -> tuple[Driver, DrillData, DockData | None]:
    """One composed run: the driver, and what each half produced.

    Both presentations reach a run through here. What differs between the
    workbench and the plain writer is what happens around a run -- one
    returns to an application and the other to a process -- never what a run
    is, and a second composition is how the two would drift apart.
    """
    driver = Driver(plan, presentation, options, project, acquire)
    sink: Sink = presentation if stop is None else CancellingSink(presentation, stop)
    with track(sink) as scope:
        drill, dock = driver.run(scope)
    return driver, drill, dock


def _kept(held: Settings, fresh: Settings) -> Settings:
    """``fresh``, less any field the answered-gap rank already holds.

    A user who has since set that field themselves said the more recent
    thing, and the run is about to read theirs, so theirs is what the
    manifest must record.
    """
    settings = fresh
    for place in PLACE_ORDER:
        before = getattr(held, place)
        after = getattr(fresh, place)
        answered = {
            row.name: getattr(before, row.name)
            for row in fields(before)
            if getattr(before, row.name).provenance.origin is Origin.USER
            and getattr(after, row.name).provenance.origin is not Origin.USER
        }
        if answered:
            settings = replace(settings, **{place: replace(after, **answered)})
    return settings


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


def _selected_sizes(text: str | None) -> tuple[Nanometre, ...] | None:
    """Comma-separated millimetre sizes as exact drill-table nanometres, or none named.

    Mirrors ``stompdrill.cli.build_drill_standard``'s own narrowing of
    ``--drill-sizes``/``--no-drill-sizes``, over a string a run's caller
    already resolved rather than an unread command-line flag.
    """
    if text is None:
        return None
    return tuple(nm_from_mm(float(size)) for size in text.split(",") if size.strip())


def _needs_model(options: RunOptions) -> bool:
    """Whether this run has anything to do with an enclosure model.

    Docking seats boards inside one, and a drilled enclosure is an artefact
    made from one. A run that asked for neither is a drill-only run, and
    acquiring a model it will not use would change what it produces in order
    to fetch something nobody asked for.
    """
    return bool(options.boards) or any(name == "step" for name, _path in options.targets)


def _model_part(declared: str | None, data: DrillData) -> str | None:
    """The part whose model this run needs, where exactly one is known.

    A declaration settles it. Otherwise the identification does, and only
    where it names one part: a footprint several parts share names no file,
    and choosing the first would pick an enclosure nobody asked for.
    """
    if declared is not None:
        return declared
    match = data.enclosure
    if match is None:
        return None
    if match.selected_part is not None:
        return match.selected_part
    return match.candidates[0] if len(match.candidates) == 1 else None


def _unavailable(part: str, failure: Exception) -> Diagnostic:
    """Report a model that could not be had, naming the part and the reason."""
    return Diagnostic.error(
        "case-model-unavailable",
        f"the enclosure model for {part} could not be obtained: {failure}; "
        f"choose a different case, or put the model in the cache by hand",
        data=(("part", part),),
    )


def _quantise_outcome(data: DrillData, model: OcpCaseModel | None = None) -> str:
    """What quantisation produced: the holes accepted, their tools, and the model opened."""
    stated = f"{len(data.holes)} holes, {len(data.tools())} tools"
    return stated if model is None else f"{stated}, {model.model_name}"


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
