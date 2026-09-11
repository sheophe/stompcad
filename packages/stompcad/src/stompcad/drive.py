"""The driver: executes a run's steps, holding each intermediate between them.

Spec decision 7: `stompcad` calls each phase separately -- the same calls,
same order, same arguments `stompdrill.cli._run` and `stompcollider.cli._run`
make -- rather than one entry point per tool. Holding intermediates as
attributes, not locals, is what lets plan C run a single step again once an
answer arrives (decision 4), and decision 8 is why that rerun never retreats
a position already reported. This module is the drill half; a later task
extends the same class with the dock half.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stompdrill.cad import OcpCaseModel, load_case_model
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
from stompmodel.model import CaseFace, DrillData
from stompmodel.progress import Scope
from stompmodel.protocols import Payload, Pipeline, Stage, stage_all
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

        The one write mechanism this workspace owns (ADR-0001, ADR-0005);
        no second one is added here.
        """
        settings = OutputSettings(title=_DEFAULT_TITLE, case_model=self._case_model)
        emitters = [(make_emitter(name, settings), path) for name, path in self._options.targets]
        rendered: list[tuple[Path, Payload]] = []
        for (emitter, path), slot in zip(emitters, scope.steps(len(emitters)), strict=True):
            slot.label(emitter.name)
            rendered.append((path, emitter.emit(data)))
        staged = stage_all(rendered)
        for written in staged:
            written.commit()
        return [str(written.path) for written in staged]
