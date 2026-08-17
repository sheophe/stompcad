"""Behavioural tests for ``RouteHoles``: tool-major blocks, routed and numbered."""

from __future__ import annotations

import itertools

import pytest

from aidrill.model import DrillData, Hole, RawHole, ReferenceOutline
from aidrill.pipeline import RouteHoles
from aidrill.units import Millimetre, Nanometre
from tests.conftest import at

__all__: list[str] = []


def panel(*holes):
    return DrillData(
        holes=holes, reference=ReferenceOutline(Nanometre(120_000_000), Nanometre(94_000_000))
    )


def test_two_holes_at_one_nominal_point_are_ordered_by_their_measurements():
    """Nominal position alone ties here, and a tie must not be settled by arrival.

    ``Deduplicate`` normally collapses these, but ``RouteHoles`` is an
    independent stage and a caller may compose it alone. The measurements
    differ, so the order is still decided by geometry rather than by input.
    """
    ref = ReferenceOutline(Nanometre(100_000_000), Nanometre(100_000_000))

    def hole(raw_x: float, index: int) -> Hole:
        return Hole(
            Nanometre(0),
            Nanometre(0),
            Nanometre(7_000_000),
            RawHole(Millimetre(raw_x), Millimetre(0.0), Millimetre(7.0), index),
            index,
        )

    left, right = hole(0.0001, 1), hole(0.0002, 2)
    routes = {
        tuple(h.raw.x for h in RouteHoles().apply(DrillData(holes=pair, reference=ref)).holes)
        for pair in ((left, right), (right, left))
    }

    assert routes == {(0.0001, 0.0002)}, "input order reached the routed sequence"


def test_each_tool_occupies_one_contiguous_block():
    """A second block of the same diameter is a second bit change."""
    out = RouteHoles().apply(
        panel(
            at(0, 0, 7_000_000, index=4),
            at(10_000_000, 0, 3_000_000, index=1),
            at(20_000_000, 0, 7_000_000, index=9),
        )
    )
    seen, blocks = None, []
    for hole in out.holes:
        if hole.diameter_nm != seen:
            blocks.append(hole.diameter_nm)
            seen = hole.diameter_nm
    assert blocks == sorted(set(blocks)), "a diameter appears in two blocks"


def test_numbers_run_one_to_n_in_emission_order():
    out = RouteHoles().apply(
        panel(
            at(0, 0, 7_000_000, index=4),
            at(10_000_000, 0, 7_000_000, index=1),
            at(20_000_000, 0, 7_000_000, index=9),
        )
    )
    assert [h.index for h in out.holes] == [1, 2, 3]


def test_a_block_starts_at_its_topmost_then_leftmost_hole():
    out = RouteHoles().apply(
        panel(
            at(30_000_000, 10_000_000, 7_000_000, index=4),
            at(-30_000_000, 20_000_000, 7_000_000, index=1),
            at(30_000_000, 20_000_000, 7_000_000, index=9),
        )
    )
    assert (out.holes[0].x_nm, out.holes[0].y_nm) == (-30_000_000, 20_000_000)


def test_a_single_hole_block_routes_to_itself():
    """``while block`` and the 2-opt sweep both iterate zero times here."""
    out = RouteHoles().apply(panel(at(5_000_000, 5_000_000, 3_000_000, index=4)))
    assert [h.index for h in out.holes] == [1]


def test_the_route_does_not_depend_on_input_order():
    """A mirror-symmetric block guarantees equidistant candidates."""
    holes = (
        at(-20_000_000, 20_000_000, 7_000_000, index=4),
        at(20_000_000, 20_000_000, 7_000_000, index=1),
        at(-20_000_000, -20_000_000, 7_000_000, index=9),
        at(20_000_000, -20_000_000, 7_000_000, index=2),
    )
    first = [(h.x_nm, h.y_nm) for h in RouteHoles().apply(panel(*holes)).holes]
    for rotation in range(1, len(holes)):
        shuffled = holes[rotation:] + holes[:rotation]
        assert [
            (h.x_nm, h.y_nm) for h in RouteHoles().apply(panel(*shuffled)).holes
        ] == first


def test_two_opt_reaches_the_optimum_nearest_neighbour_misses():
    """Plain NN strands the far hole and returns for it, costing 210.9 against
    162.2. Asserted against brute force rather than a hand-written order, which
    would only pin whatever the implementation happened to produce."""
    out = RouteHoles().apply(
        panel(
            at(-35_000_000, -40_000_000, 7_000_000, index=4),
            at(-20_000_000, 40_000_000, 7_000_000, index=1),
            at(5_000_000, -5_000_000, 7_000_000, index=9),
            at(35_000_000, 40_000_000, 7_000_000, index=2),
        )
    )
    path = [(h.x_nm, h.y_nm) for h in out.holes]

    def length(points):
        return sum(
            ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            for a, b in itertools.pairwise(points)
        )

    start, rest = path[0], path[1:]
    assert start == (-20_000_000, 40_000_000), "the block must start topmost-then-leftmost"
    best = min(length([start, *order]) for order in itertools.permutations(rest))
    assert length(path) == pytest.approx(best), f"2-opt left a crossing: {path}"


def test_a_custom_key_orders_and_numbers_without_grouping():
    out = RouteHoles(key=lambda h: -h.diameter_nm).apply(
        panel(
            at(0, 0, 3_000_000, index=4),
            at(10_000_000, 0, 7_000_000, index=1),
        )
    )
    assert [h.diameter_nm for h in out.holes] == [7_000_000, 3_000_000]
    assert [h.index for h in out.holes] == [1, 2]
