"""The driver: executes a run's steps, holding each intermediate between them.

Spec decision 7: `stompcad` calls each phase separately, the same calls and
order `stompdrill.cli._run` and `stompcollider.cli._run` make. Holding
intermediates as attributes lets plan C run one step again once an answer
arrives (decision 4), never retreating a reported position (decision 8).
Importing this module loads `stompgeom`, and through it OCP, by way of
`stompdrill`'s own emitters. That is not a leak: the constraint binds what
`stompcad` reaches for, and it imports neither. Only `plan.py` promises to
stay kernel-free, because plan B renders it.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

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
from stompmodel.protocols import Emitter, Payload, Pipeline, Stage, stage_all
from stompmodel.units import nm_from_mm

from .plan import RunPlan
from .present import Presentation

__all__ = ["RunOptions", "Driver"]

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
_DOCK_TARGET_NAMES = frozenset({"report", "assembly"})


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
    without recomputing it.
    """

    def __init__(self, plan: RunPlan, presentation: Presentation, options: RunOptions) -> None:
        self._plan = plan
        self._presentation = presentation
        self._options = options
        self._case_model: OcpCaseModel | None = None
        self._raw: RawDrillData | None = None
        self._quantised: DrillData | None = None
        self._drilled: DrillData | None = None

    def run_drill(self, scope: Scope) -> DrillData:
        """Read, quantise and drill the panel, then write its case artefacts.

        Draws the plan's slots lazily, one ``next()`` immediately before the
        step it belongs to -- a slot closes when the next is drawn, so
        drawing them all at once would close every one with no work done.
        """
        self._presentation.begin(self._plan)
        slots = scope.parts(*self._plan.weights())

        read_step = self._plan.steps[0]
        read_slot = next(slots)
        read_slot.label(read_step.label)
        self._read_panel(read_slot)
        self._presentation.finish_step(read_step, self._read_outcome())

        quantise_step = self._plan.steps[1]
        quantise_slot = next(slots)
        quantise_slot.label(quantise_step.label)
        self._quantised = self._quantise(quantise_slot)
        self._presentation.finish_step(
            quantise_step,
            f"{len(self._quantised.holes)} holes, {len(self._quantised.tools())} tools",
        )

        drill_step = self._plan.steps[2]
        drill_slot = next(slots)
        drill_slot.label(drill_step.label)
        self._drilled = self._drill(self._quantised, drill_slot)
        self._presentation.finish_step(drill_step, f"{len(self._drilled.holes)} holes")

        write_step = self._plan.steps[3]
        write_slot = next(slots)
        write_slot.label(write_step.label)
        written = self._write_case(self._drilled, write_slot)
        self._presentation.finish_step(write_step, ", ".join(written) or "nothing written")

        return self._drilled

    def run(self, scope: Scope) -> tuple[DrillData, DockData | None]:
        """Drill the panel, then dock its boards against it when any were asked for.

        The drill document ``run_dock`` reads is the one ``run_drill`` just
        held in memory, never written for this handoff alone -- see the
        task report for the one case that forces a temporary file anyway.
        Docking is skipped entirely, not merely skipped in its steps, when
        no board was named.
        """
        drilled = self.run_drill(scope)
        if not self._options.boards:
            return drilled, None
        return drilled, self.run_dock(drilled, scope)

    def run_dock(self, drill: DrillData, scope: Scope) -> DockData:
        """Read the boards, match, seat and report clashes against the drilled case.

        Draws the same nine-weight division ``run_drill`` does, skipping
        the four slots that belong to it before drawing its own five, so
        the two halves share one bar rather than each claiming the whole
        of it.
        """
        self._presentation.begin(self._plan)
        slots = scope.parts(*self._plan.weights())
        for _ in self._plan.steps[:4]:
            next(slots)

        read_step = self._plan.steps[4]
        read_slot = next(slots)
        read_slot.label(read_step.label)
        scan, geometry, data, pipeline = self._read_boards(drill, read_slot)
        self._presentation.finish_step(read_step, f"{len(scan.raw.boards)} board(s)")

        for step, stage in zip(self._plan.steps[5:8], pipeline, strict=True):
            slot = next(slots)
            slot.label(step.label)
            before, data = data, Pipeline([stage]).run(data, slot)
            self._presentation.finish_step(step, _stage_outcome(before, data))

        write_step = self._plan.steps[8]
        write_slot = next(slots)
        write_slot.label(write_step.label)
        written = self._write_dock(data, scan, geometry, write_slot)
        self._presentation.finish_step(write_step, ", ".join(written) or "nothing written")

        return data

    def _read_boards(
        self, drill: DrillData, scope: Scope
    ) -> tuple[BoardScan, dict[int, BoardGeometry], DockData, Pipeline[DockData]]:
        """Stage the drill document and the drilled case, then scan and compose.

        ``BoardSource`` reads both from real files, and neither is one
        this run already wrote: the drill document lives only in memory
        until a target asks for it, and the case is drilled only by the
        ``step`` emitter's own render. Both go to a private temporary
        directory, gone before this method returns -- see the task report.
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
            panel_reference = parse_filter(self._options.panel_reference)
            tolerance_nm = derived_tolerance(scan.drill, drill_path)
            case = registration(scan, drill_path)
            data = admit(docked(scan, case), panel_reference)
            geometry = board_geometry(scan, case)
            pipeline = build_pipeline(
                tolerance_nm,
                scan.case.solids,
                {ordinal: board.solids for ordinal, board in geometry.items()},
                nm_from_mm(_SEAT_PITCH_MAX_MM),
                nm_from_mm(_SEAT_PITCH_MIN_MM),
            )
            return scan, geometry, data, pipeline

    def _write_dock(
        self,
        data: DockData,
        scan: BoardScan,
        geometry: dict[int, BoardGeometry],
        scope: Scope,
    ) -> list[str]:
        """Render the report and assembly, then stage and commit through ``stage_all``.

        Renders only the targets named for this half -- ``RunOptions.targets``
        may also carry drill-format names meant for ``_write_case``. Withholds
        every target on an error severity, the same rule ``_write_case``
        applies to the drill half: CLAUDE.md's "any error prevents every
        requested output" binds both halves of one run.
        """
        targets = [(name, path) for name, path in self._options.targets if name in _DOCK_TARGET_NAMES]
        if not targets:
            return []
        if data.worst_severity is Severity.ERROR:
            self._presentation.report(_withheld(targets))
            return []
        case = Solids(scan.case.document, scan.case.solids)
        boards = {
            ordinal: Solids(board.document.document, board.solids)
            for ordinal, board in geometry.items()
        }
        emitters: list[tuple[Emitter[DockData], Path]] = []
        for name, path in targets:
            if name == "report":
                emitters.append((ReportEmitter(), path))
            else:
                emitters.append((AssemblyEmitter(case, boards, timestamp=scan.case.timestamp), path))
        rendered: list[tuple[Path, Payload]] = []
        for (emitter, path), slot in zip(emitters, scope.steps(len(emitters)), strict=True):
            slot.label(emitter.name)
            rendered.append((path, emitter.emit(data)))
        staged = stage_all(rendered)
        for written in staged:
            written.commit()
        self._presentation.report([f"wrote {written.path}" for written in staged])
        return [str(written.path) for written in staged]

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

    def _write_case(self, data: DrillData, scope: Scope) -> list[str]:
        """Render every target, then stage and commit through ``stage_all``.

        Renders only the targets named for this half -- ``RunOptions.targets``
        may also carry dock-format names meant for ``_write_dock``. Withholds
        every target on an error severity: CLAUDE.md states "any error
        prevents every requested output," and an emitter may legitimately
        refuse data this broken, so nothing is rendered at all rather than
        rendered and discarded. The one write mechanism this workspace
        owns (ADR-0001, ADR-0005); no second one is added.
        """
        drill_formats = available()
        targets = [(name, path) for name, path in self._options.targets if name in drill_formats]
        if not targets:
            return []
        if data.worst_severity is Severity.ERROR:
            self._presentation.report(_withheld(targets))
            return []
        settings = OutputSettings(title=_DEFAULT_TITLE, case_model=self._case_model)
        emitters = [(make_emitter(name, settings), path) for name, path in targets]
        rendered: list[tuple[Path, Payload]] = []
        for (emitter, path), slot in zip(emitters, scope.steps(len(emitters)), strict=True):
            slot.label(emitter.name)
            rendered.append((path, emitter.emit(data)))
        staged = stage_all(rendered)
        for written in staged:
            written.commit()
        self._presentation.report([f"wrote {written.path}" for written in staged])
        return [str(written.path) for written in staged]


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
