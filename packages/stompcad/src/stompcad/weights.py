"""Leaf counts behind ``plan.DRILL_AND_DOCK``, and the command that found them.

Spec decision 5: a weight is the leaf count a step reports on the reference
fixture, a kernel leaf worth ``KERNEL_LEAF_WEIGHT`` plain ones. Seven steps
touch the kernel deterministically or never, so their class is read from the
library's own structure; ``seat`` and ``clash`` sample a search whose kernel
use is data-dependent, so those two are counted by running the fixture with
``interferes``/``common`` wrapped to mark the leaf open when either fires.
Regenerate with the command in ``plan.py``'s comment.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stompcollider import clash as _clash_module
from stompcollider import insert as _insert_module
from stompcollider.clash import Clashes
from stompcollider.compose import admit, board_geometry, derived_tolerance, docked, registration
from stompcollider.designators import parse_filter
from stompcollider.emitters.assembly import AssemblyEmitter, Solids
from stompcollider.insert import CaseCavity
from stompcollider.match import Match
from stompcollider.seat import Seat
from stompcollider.sources import BoardSource
from stompdrill.cad import load_case_model
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
from stompdrill.quantise import quantise
from stompdrill.sources import DEFAULT_FORM_DEPTH, AiPdfSource
from stompmodel.codec import to_document
from stompmodel.model import CaseFace
from stompmodel.units import nm_from_mm

__all__ = ["KERNEL_LEAF_WEIGHT", "LeafTally", "count_leaves"]

#: Spec decision 5's one stated judgement: a kernel leaf's multiplier.
KERNEL_LEAF_WEIGHT: int = 10


@dataclass(frozen=True, slots=True)
class LeafTally:
    """One step's measured leaves, split by class."""

    plain: int
    kernel: int

    @property
    def weight(self) -> float:
        """``plain`` leaves plus ``kernel`` ones at ``KERNEL_LEAF_WEIGHT`` each."""
        return self.plain + self.kernel * KERNEL_LEAF_WEIGHT


class _Counter:
    """Kernel-call count, and each step's leaves classed by it at close."""

    def __init__(self) -> None:
        self.kernel_calls: int = 0
        self.tallies: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    def touch(self) -> None:
        """Record one kernel call, attributed to whichever leaf is open."""
        self.kernel_calls += 1

    def divide(self, step: str, count: int) -> Iterator[_CountingScope]:
        """Yield ``count`` children, finalising each as the next is drawn."""
        previous: _CountingScope | None = None
        for _ in range(count):
            if previous is not None:
                self._finalize(previous)
            previous = _CountingScope(self, step)
            yield previous
        if previous is not None:
            self._finalize(previous)

    def _finalize(self, child: _CountingScope) -> None:
        if child.divided:
            return
        index = 1 if self.kernel_calls > child.start else 0
        self.tallies[child.step][index] += 1


class _CountingScope:
    """A ``Scope`` that reports nothing but which class each leaf falls in.

    Satisfies ``stompmodel.progress.Scope`` structurally. A child is a leaf
    unless ``steps``/``parts`` is called on it before the division that
    yielded it moves on; a leaf is a kernel one when the shared counter
    advanced between its own start and the next child being drawn.
    """

    __slots__ = ("_counter", "step", "divided", "start")

    def __init__(self, counter: _Counter, step: str) -> None:
        self._counter = counter
        self.step = step
        self.divided = False
        self.start = counter.kernel_calls

    def steps(self, count: int) -> Iterator[_CountingScope]:
        self.divided = True
        return self._counter.divide(self.step, count)

    def parts(self, *weights: float) -> Iterator[_CountingScope]:
        self.divided = True
        return self._counter.divide(self.step, len(weights))

    def label(self, name: str) -> None:
        return None


@contextmanager
def _counted_kernel(counter: _Counter) -> Iterator[None]:
    """Wrap the two search predicates so every call counts as one leaf's work."""
    targets = [(_insert_module, "interferes"), (_insert_module, "common")]
    targets += [(_clash_module, "interferes"), (_clash_module, "common")]
    originals: list[tuple[Any, str, Any]] = [
        (module, name, getattr(module, name)) for module, name in targets
    ]

    def _wrapped(fn: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            counter.touch()
            return fn(*args, **kwargs)

        return call

    for module, name, fn in originals:
        setattr(module, name, _wrapped(fn))
    try:
        yield
    finally:
        for module, name, fn in originals:
            setattr(module, name, fn)


def count_leaves(
    panel: Path,
    board: Path,
    case_model: Path,
    panel_reference: str,
    *,
    case_part: str = "1590B",
    grid_mm: float = 0.25,
    case_margin_mm: float = 1.0,
    seat_pitch_max_mm: float = 2.0,
    seat_pitch_min_mm: float = 0.05,
) -> dict[str, LeafTally]:
    """Run both tools' phases over one fixture and tally each step's leaves.

    ``read-panel`` through ``write-assembly`` are counted from the values
    each phase actually returns, classed by what the library's own code is
    known to do; only ``seat`` and ``clash`` run under ``_counted_kernel``,
    because only there does a sample's class depend on the geometry.
    """
    raw = AiPdfSource(
        panel, drill_layer="Drill", reference_layer="Background", form_depth=DEFAULT_FORM_DEPTH
    ).read()
    model = load_case_model(
        case_model, face=CaseFace.BOX, margin_nm=nm_from_mm(case_margin_mm), part=case_part
    )
    tallies: dict[str, LeafTally] = {
        "read-panel": LeafTally(plain=1, kernel=1),
    }

    standard = DRILL_STANDARDS[DEFAULT_STANDARD]
    data = quantise(
        raw,
        enclosure=IdentifyHammondFootprint(expected_part=case_part),
        diameters=SnapDiametersToDrillTable(standard),
        positions=SnapPositions(nm_from_mm(grid_mm), None),
    )
    tallies["quantise"] = LeafTally(plain=len(raw.holes), kernel=0)

    plain_drill = 0
    kernel_drill = 0
    for stage in (
        Deduplicate(),
        ReviewGridTies(),
        RouteHoles(),
        CheckOutlineContainment(),
        CheckCaseClearance(model),
    ):
        count = (
            len({hole.diameter_nm for hole in data.holes})
            if isinstance(stage, RouteHoles)
            else len(data.holes)
        )
        if isinstance(stage, CheckCaseClearance):
            kernel_drill += count
        else:
            plain_drill += count
        data = stage.apply(data)
    tallies["drill"] = LeafTally(plain=plain_drill, kernel=kernel_drill)

    settings = OutputSettings(title="", case_model=model)
    formats = sorted(available())
    tallies["write-case"] = LeafTally(
        plain=sum(1 for name in formats if name != "step"),
        kernel=sum(1 for name in formats if name == "step"),
    )
    for name in formats:
        make_emitter(name, settings).emit(data)

    with tempfile.TemporaryDirectory() as tmp:
        drill_path = Path(tmp) / "drill.json"
        drill_path.write_text(json.dumps(to_document(data)), encoding="utf-8")
        source = BoardSource(drill_path, [board], case_model)
        scan = source.scan()
        tallies["read-boards"] = LeafTally(plain=1, kernel=1 + len(source.boards))

        case = registration(scan, drill_path)
        dock_data = admit(docked(scan, case), parse_filter(panel_reference))
        geometry = board_geometry(scan, case)
        board_solids = {ordinal: geom.solids for ordinal, geom in geometry.items()}

        tallies["match"] = LeafTally(plain=len(dock_data.boards), kernel=0)
        tolerance_nm = derived_tolerance(scan.drill, drill_path)
        dock_data = Match(tolerance_nm).apply(dock_data)

        counter = _Counter()
        cavity = CaseCavity(
            scan.case.solids,
            board_solids,
            nm_from_mm(seat_pitch_max_mm),
            nm_from_mm(seat_pitch_min_mm),
        )
        clashes = Clashes(scan.case.solids, board_solids)
        with _counted_kernel(counter):
            dock_data = Seat(cavity).apply(dock_data, _CountingScope(counter, "seat"))
            dock_data = clashes.apply(dock_data, _CountingScope(counter, "clash"))
        tallies["seat"] = LeafTally(*counter.tallies["seat"])
        tallies["clash"] = LeafTally(*counter.tallies["clash"])

        assembly = AssemblyEmitter(
            case=Solids(scan.case.document, scan.case.solids),
            boards={
                ordinal: Solids(geom.document.document, geom.solids)
                for ordinal, geom in geometry.items()
            },
            timestamp=scan.case.timestamp,
        )
        assembly.emit(dock_data)
        tallies["write-assembly"] = LeafTally(plain=0, kernel=1)

    return tallies
