"""Geometry alone determines output: ADR-0006's binding invariant."""

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from pathlib import Path

import pytest

from aidrill.emitters import get_emitter
from aidrill.model import DrillData, Hole
from aidrill.pipeline import (
    Deduplicate,
    IdentifyHammondFootprint,
    ReviewGridTies,
    RouteHoles,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from aidrill.quantise import quantise
from aidrill.sources import AiPdfSource
from aidrill.units import Nanometre

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
