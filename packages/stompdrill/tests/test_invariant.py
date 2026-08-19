"""Geometry alone determines output: ADR-0006's binding invariant."""

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from pathlib import Path

import pytest

from stompdrill.emitters import get_emitter
from stompdrill.emitters.json_out import JsonEmitter
from stompdrill.model import (
    DrillData,
    Hole,
    RawDrillData,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
)
from stompdrill.pipeline import (
    Deduplicate,
    IdentifyHammondFootprint,
    ReviewGridTies,
    RouteHoles,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from stompdrill.quantise import quantise
from stompdrill.sources import AiPdfSource
from stompdrill.units import Millimetre, Nanometre

__all__: list[str] = []

FIXTURES = Path(__file__).parent / "fixtures"  # conftest exposes no such constant

FORMATS = ("excellon", "json", "drawing-svg", "drawing-pdf")

#: Both fixtures are within tolerance of more than one footprint (see
#: CLAUDE.md), so each needs the case its own artwork was drawn for.
CASES = {"tar.ai": "1590B", "pax.ai": "1590BB"}


def artifacts(raw, case: str) -> dict[str, object]:
    data = quantise(
        raw,
        enclosure=IdentifyHammondFootprint(case),
        diameters=SnapDiametersToDrillTable(),
        positions=SnapPositions(Nanometre(250_000)),
    )
    for stage in (Deduplicate(), ReviewGridTies(), RouteHoles()):
        data = stage.apply(data)
    return {name: get_emitter(name)().emit(data) for name in FORMATS}


@pytest.mark.parametrize("panel", ["tar.ai", "pax.ai"])
def test_element_order_cannot_reach_any_artifact(panel):
    """Permuting the artwork's holes must not move a single byte."""
    case = CASES[panel]
    raw = AiPdfSource(FIXTURES / panel).read()
    expected = artifacts(raw, case)

    rng = random.Random(7)
    for _ in range(25):
        shuffled = list(raw.holes)
        rng.shuffle(shuffled)
        assert artifacts(replace(raw, holes=tuple(shuffled)), case) == expected


def _synthetic_raw() -> RawDrillData:
    """A panel neither ``tar.ai`` nor ``pax.ai`` can exercise: both are clean,
    raising no per-hole diagnostic and holding no duplicate. This one has two
    off-grid holes, whose diagnostics finding 1 appended in arrival order, and
    a coincident pair, whose survivor finding 1 chose by arrival too.

    The first two share an X and a diameter and differ only in Y, which is what
    makes every clause of the sort key load-bearing: drop Y from it and these
    two tie, leaving arrival order to say which diagnostic is reported first.
    """
    return RawDrillData(
        source=SourceInfo(path="synthetic.ai", drill_layer="Drill"),
        reference=RawOutline(Millimetre(113.0), Millimetre(60.0)),
        centre=(Millimetre(56.5), Millimetre(30.0)),
        holes=(
            RawHole(Millimetre(-20.13), Millimetre(18.0), Millimetre(7.0)),
            RawHole(Millimetre(-20.13), Millimetre(-18.0), Millimetre(7.0)),
            RawHole(Millimetre(20.13), Millimetre(18.0), Millimetre(5.0)),
            RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(3.0)),
            RawHole(Millimetre(0.0004), Millimetre(-0.0003), Millimetre(3.0)),
        ),
    )


def test_a_panel_with_diagnostics_and_a_duplicate_is_permutation_stable():
    """The regression test for finding 1: geometry alone determines output
    even when the panel gives arrival order something to leak through — a
    per-hole diagnostic and a coincident pair. Must fail if the sort
    ``quantise()`` applies to ``raw.holes`` on entry is removed.
    """
    case = "1590B"
    raw = _synthetic_raw()
    expected = artifacts(raw, case)

    rng = random.Random(11)
    for _ in range(25):
        shuffled = list(raw.holes)
        rng.shuffle(shuffled)
        assert artifacts(replace(raw, holes=tuple(shuffled)), case) == expected


def holes_at_one_point() -> tuple[Hole, Hole]:
    """A 3 mm and a 7 mm hole sharing one nominal point.

    Grouping by diameter already separates them into different tool blocks,
    but this locks in the case the old ``(-y, x)`` sort could not order: two
    holes at one point, distinguishable only by what they measured.
    """
    return (
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(3_000_000)),
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
    )


def routed(data: DrillData) -> DrillData:
    return RouteHoles().apply(data)


def test_a_concentric_pair_is_ordered_by_geometry_not_by_arrival():
    """The tie that defeated the old sort: same point, different diameters."""
    pair = holes_at_one_point()  # 3 mm and 7 mm at (0, 0)
    outputs = {
        tuple(h.diameter_nm for h in routed(DrillData(holes=p)).holes)
        for p in itertools.permutations(pair)
    }
    assert len(outputs) == 1


def test_a_tie_inside_one_block_cannot_reach_the_emitted_bytes():
    """Two holes of one size at one nominal point, told apart only by what they
    measured. ``Deduplicate`` collapses such a pair, so this is what a caller
    composing ``RouteHoles`` alone gets — and ``raw`` is serialised, so which
    one is numbered first is observable. Regression: this ordering was decided
    by arrival until the routing tie-break fell through to the measurement.

    The permutation test above cannot see this: its fixtures tie only across
    blocks, and within a block 2-opt converges either arrival order to one tour.
    """
    ref = ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000))

    def hole(raw_x: float) -> Hole:
        return Hole(
            Nanometre(0),
            Nanometre(0),
            Nanometre(7_000_000),
            RawHole(Millimetre(raw_x), Millimetre(0.0), Millimetre(7.0)),
        )

    pair = (hole(0.0001), hole(0.0002))
    rendered = {
        JsonEmitter().emit(routed(DrillData(holes=order, reference=ref)))
        for order in itertools.permutations(pair)
    }

    assert len(rendered) == 1, "arrival order reached the emitted bytes"
