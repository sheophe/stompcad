"""Derive ``stompcad.plan.DRILL_AND_DOCK``'s weights from measured leaves.

Spec decision 5: a step's weight is the leaf count it *reports* on the
reference fixture, each leaf classed as kernel (an insertion query, a
boolean between solids) or plain (arithmetic), a kernel leaf worth
``stompcad.plan.KERNEL_LEAF_WEIGHT`` plain ones. Every phase that accepts a
``Scope`` is given one here and its leaves are counted as it reports them --
none of this file reimplements a phase's own division. ``read-panel``,
``write-case`` and ``write-assembly`` are the exception: ``Source.read``
(``packages/stompdrill/src/stompdrill/protocols.py``) and ``Emitter.emit``
(``packages/stompmodel/src/stompmodel/protocols.py``) take no scope at all,
so those three are declared, not measured -- see ``count_leaves``'s
docstring for exactly what and why.

Run with:

    .venv/bin/python tools/count_leaves.py \\
        packages/stompdrill/tests/fixtures/tar.ai \\
        packages/stompcollider/tests/fixtures/tar-pcb.stp \\
        ~/.cache/stompcad/cases/1590B.stp \\
        'RV*,SW*,D(3..4),!RV5'
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import stompcollider.clash as clash_module
import stompcollider.insert as insert_module
import stompcollider.sources.step as board_source_module
import stompdrill.cad.region as region_module
import stompgeom.step as step_module
from stompcad.plan import KERNEL_LEAF_WEIGHT
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
from stompmodel.model import CaseFace, DrillData
from stompmodel.protocols import Pipeline
from stompmodel.units import nm_from_mm

__all__ = ["LeafTally", "count_leaves", "main"]


@dataclass(frozen=True, slots=True)
class LeafTally:
    """One step's measured (or declared) leaves, split by class."""

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
    yielded it moves on -- mirroring ``stompmodel.progress``'s own "advancing
    the iterator closes the previous slot" rule. A leaf is a kernel one when
    the shared counter advanced between its own start and the next sibling
    being drawn, which is why every real kernel entry point this fixture can
    reach is wrapped by ``_counted_kernel`` before any phase runs.
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
    """Wrap every kernel entry point a measured step can reach.

    ``interferes``/``common`` cover ``seat``/``clash``'s search and clash
    checks; ``read_step`` covers ``read-boards``' case-model and board-file
    reads (patched on both the defining module and ``stompcollider``'s own
    bound name, since a module-level ``from ... import`` copies the
    reference rather than following it); ``contains`` covers ``drill``'s
    per-hole clearance query. ``quantise`` and ``match`` reach none of
    these, so their leaves classify as plain without needing a patch.
    """
    targets = [
        (insert_module, "interferes"),
        (insert_module, "common"),
        (clash_module, "interferes"),
        (clash_module, "common"),
        (step_module, "read_step"),
        (board_source_module, "read_step"),
        (region_module, "contains"),
    ]
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

    Six steps -- ``quantise``, ``drill``, ``read-boards``, ``match``,
    ``seat``, ``clash`` -- pass a ``_CountingScope`` into the real call
    (``quantise()``, each pipeline stage's ``apply``, ``BoardSource.scan``,
    ``Match.apply``, ``Seat.apply``, ``Clashes.apply``) and read back what
    that call itself divided into and touched. The other three take no
    scope at all and are declared just below, each citing the signature
    that makes it unmeasurable.
    """
    counter = _Counter()
    with _counted_kernel(counter):
        raw = AiPdfSource(
            panel,
            drill_layer="Drill",
            reference_layer="Background",
            form_depth=DEFAULT_FORM_DEPTH,
        ).read()
        model = load_case_model(
            case_model, face=CaseFace.BOX, margin_nm=nm_from_mm(case_margin_mm), part=case_part
        )
        # Declared: Source.read(self) -> RawDrillData takes no scope
        # (packages/stompdrill/src/stompdrill/protocols.py:25), and
        # load_case_model(path, *, face, margin_nm, part=None) -> OcpCaseModel
        # takes none either. The artwork parse never touches the kernel; the
        # case-model read always does (a STEP transfer has no shortcut).
        tallies: dict[str, LeafTally] = {"read-panel": LeafTally(plain=1, kernel=1)}

        standard = DRILL_STANDARDS[DEFAULT_STANDARD]
        data = quantise(
            raw,
            enclosure=IdentifyHammondFootprint(expected_part=case_part),
            diameters=SnapDiametersToDrillTable(standard),
            positions=SnapPositions(nm_from_mm(grid_mm), None),
            scope=_CountingScope(counter, "quantise"),
        )
        tallies["quantise"] = LeafTally(*counter.tallies["quantise"])

        pipeline: Pipeline[DrillData] = Pipeline(
            [
                Deduplicate(),
                ReviewGridTies(),
                RouteHoles(),
                CheckOutlineContainment(),
                CheckCaseClearance(model),
            ]
        )
        data = pipeline.run(data, _CountingScope(counter, "drill"))
        tallies["drill"] = LeafTally(*counter.tallies["drill"])

        settings = OutputSettings(title="", case_model=model)
        formats = sorted(available())
        # Declared: Emitter.emit(self, data) -> Payload takes no scope
        # (packages/stompmodel/src/stompmodel/protocols.py:295). Only the
        # step format cuts the model (a boolean, unconditional); the other
        # four only format numbers already computed.
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
            scan = source.scan(_CountingScope(counter, "read-boards"))
            tallies["read-boards"] = LeafTally(*counter.tallies["read-boards"])

            case = registration(scan, drill_path)
            dock_data = admit(docked(scan, case), parse_filter(panel_reference))
            geometry = board_geometry(scan, case)
            board_solids = {ordinal: geom.solids for ordinal, geom in geometry.items()}

            tolerance_nm = derived_tolerance(scan.drill, drill_path)
            dock_data = Match(tolerance_nm).apply(
                dock_data, _CountingScope(counter, "match")
            )
            tallies["match"] = LeafTally(*counter.tallies["match"])

            cavity = CaseCavity(
                scan.case.solids,
                board_solids,
                nm_from_mm(seat_pitch_max_mm),
                nm_from_mm(seat_pitch_min_mm),
            )
            dock_data = Seat(cavity).apply(dock_data, _CountingScope(counter, "seat"))
            tallies["seat"] = LeafTally(*counter.tallies["seat"])

            clashes = Clashes(scan.case.solids, board_solids)
            dock_data = clashes.apply(dock_data, _CountingScope(counter, "clash"))
            tallies["clash"] = LeafTally(*counter.tallies["clash"])

            # Declared: AssemblyEmitter.emit satisfies Emitter.emit(self, data)
            # -> Payload, which takes no scope (see write-case, same line).
            # A STEP write always calls render_step -- a kernel write, no
            # shortcut -- so the one leaf is unconditionally kernel.
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


def main(argv: Sequence[str] | None = None) -> int:
    """Print each step's measured leaves, class and weight, in plan order."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    parser.add_argument("board", type=Path)
    parser.add_argument("case_model", type=Path)
    parser.add_argument("panel_reference")
    args = parser.parse_args(argv)

    tallies = count_leaves(args.panel, args.board, args.case_model, args.panel_reference)
    order = [
        "read-panel", "quantise", "drill", "write-case",
        "read-boards", "match", "seat", "clash", "write-assembly",
    ]
    for key in order:
        tally = tallies[key]
        print(f"{key:15s} plain={tally.plain:4d} kernel={tally.kernel:4d} weight={tally.weight:8.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
