"""Geometry alone determines output: ADR-0006's binding invariant."""

from __future__ import annotations

import itertools
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from stompdrill.cli import build_parser, build_pipeline
from stompdrill.emitters import get_emitter
from stompdrill.emitters.json_out import JsonEmitter
from stompdrill.pipeline import (
    IdentifyHammondFootprint,
    RouteHoles,
    SnapDiametersToDrillTable,
    SnapPositions,
)
from stompdrill.quantise import RawDrillData, quantise
from stompdrill.sources import AiPdfSource
from stompmodel.model import DrillData, Hole, RawHole, RawOutline, ReferenceOutline, SourceInfo
from stompmodel.protocols import Payload, Pipeline
from stompmodel.units import Millimetre, Nanometre
from tests.conftest import FakeCase

__all__: list[str] = []

FIXTURES = Path(__file__).parent / "fixtures"  # conftest exposes no such constant

FORMATS = ("excellon", "json", "drawing-svg", "drawing-pdf")

#: Both fixtures are within tolerance of more than one footprint (see
#: CLAUDE.md), so each needs the case its own artwork was drawn for.
CASES = {"tar.ai": "1590B", "pax.ai": "1590BB"}


def shipped_pipeline(model: object | None = None) -> Pipeline[DrillData]:
    """The composition the CLI builds, read from it rather than copied here.

    A copy of the stage list drifts the moment a stage is inserted, and the
    invariant is only worth what the pipeline under it is. Parsing the real
    defaults, rather than hand-building a namespace carrying the one attribute
    ``build_pipeline`` happens to read today, survives it growing a dependency
    on another flag. ``test_cli`` owns the order; this module consumes it.
    """
    args = build_parser().parse_args(["panel.ai"])
    args.case_model_object = model
    return build_pipeline(args)


def artifacts(
    raw: RawDrillData, case: str, pipeline: Pipeline[DrillData]
) -> dict[str, Payload]:
    """Quantise, fold, and emit -- through ``Pipeline.run`` as the CLI does, so
    the provenance records it appends are certified alongside the geometry.
    """
    data = pipeline.run(
        quantise(
            raw,
            enclosure=IdentifyHammondFootprint(case),
            diameters=SnapDiametersToDrillTable(),
            positions=SnapPositions(Nanometre(250_000)),
        )
    )
    return {name: get_emitter(name)().emit(data) for name in FORMATS}


def codes(emitted: dict[str, Payload]) -> list[str]:
    """The diagnostic codes the emitted document carries."""
    return [d["code"] for d in json.loads(emitted["json"])["diagnostics"]]


def assert_permutation_stable(
    raw: RawDrillData, case: str, pipeline: Pipeline[DrillData], seed: int
) -> dict[str, Payload]:
    """Emit the panel, then 25 shuffles of it, and demand the same bytes.

    Returns the panel's own artifacts because stability is not enough on its
    own: it cannot tell a stage's finding apart from a composition missing
    that stage, since both hold just as still under a shuffle. Each stage
    therefore has a caller here naming, as a literal, something only it
    produces -- read off the pipeline that would be the same list twice.
    """
    expected = artifacts(raw, case, pipeline)
    rng = random.Random(seed)
    for _ in range(25):
        shuffled = list(raw.holes)
        rng.shuffle(shuffled)
        assert artifacts(replace(raw, holes=tuple(shuffled)), case, pipeline) == expected

    return expected


@pytest.mark.parametrize("panel", ["tar.ai", "pax.ai"])
def test_element_order_cannot_reach_any_artifact(panel):
    """Permuting the artwork's holes must not move a single byte."""
    raw = AiPdfSource(FIXTURES / panel).read()

    assert_permutation_stable(raw, CASES[panel], shipped_pipeline(), seed=7)


def test_element_order_cannot_reach_any_artifact_with_a_case_model_either():
    """``--case-model`` appends a fifth stage, so there are two compositions to
    certify and the conditional one is not the certified one by default.

    ``FakeCase`` is a 1590BB, which is what ``pax.ai`` is drawn for: pairing it
    with the other fixture would be ``wrong-case-model`` and no artefact at all.
    """
    raw = AiPdfSource(FIXTURES / "pax.ai").read()

    expected = assert_permutation_stable(raw, "1590BB", shipped_pipeline(FakeCase()), seed=5)

    stages_run = [record["name"] for record in json.loads(expected["json"])["processing"]]
    assert "check-case-clearance" in stages_run, "the fifth stage never ran"


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
    even when the panel gives arrival order something to leak through -- a
    per-hole diagnostic and a coincident pair. Must fail if the sort
    ``quantise()`` applies to ``raw.holes`` on entry is removed.
    """
    expected = assert_permutation_stable(_synthetic_raw(), "1590B", shipped_pipeline(), seed=11)

    assert "duplicate-hole" in codes(expected), "the coincident pair was never collapsed"


def _breakout_raw() -> RawDrillData:
    """``_synthetic_raw`` with one hole hung over the edge of the panel.

    Neither shipped fixture leaves its outline, so without this the fourth
    stage is only ever certified silent. A 7 mm hole centred at x = 55 spans
    to 58.5, past 1590B's 56.2 mm half-width.
    """
    base = _synthetic_raw()
    return replace(
        base,
        holes=base.holes + (RawHole(Millimetre(55.0), Millimetre(0.0), Millimetre(7.0)),),
    )


def test_a_panel_whose_hole_breaks_out_of_the_outline_is_permutation_stable():
    """``CheckOutlineContainment`` appends one finding per offending hole, in
    hole order, and the drawings render each one: a second route by which
    arrival order could reach the bytes, and it must not.
    """
    expected = assert_permutation_stable(_breakout_raw(), "1590B", shipped_pipeline(), seed=13)

    assert "hole-outside-outline" in codes(expected), "the stage's finding never fired"


def _tied_raw() -> RawDrillData:
    """``_synthetic_raw`` with two holes sat exactly halfway between grid points.

    Nothing else here ties, so without this the third stage is only ever
    certified silent. At 0.25 mm pitch, x = ±20.125 is exactly half a pitch
    out, and two of them make the order of ``tied_locations`` observable.
    """
    base = _synthetic_raw()
    tied = (
        RawHole(Millimetre(20.125), Millimetre(18.0), Millimetre(5.0)),
        RawHole(Millimetre(-20.125), Millimetre(18.0), Millimetre(5.0)),
    )
    return replace(base, holes=base.holes + tied)


def test_a_panel_whose_holes_sit_on_a_grid_tie_is_permutation_stable():
    """``ReviewGridTies`` reports every tied place in one finding, in hole
    order, so the list it carries is a third route by which arrival order
    could reach the bytes, and it must not.
    """
    expected = assert_permutation_stable(_tied_raw(), "1590B", shipped_pipeline(), seed=17)

    assert "grid-ambiguous" in codes(expected), "the stage's finding never fired"


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
    composing ``RouteHoles`` alone gets -- and ``raw`` is serialised, so which
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
