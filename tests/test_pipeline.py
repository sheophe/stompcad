"""Unit and property tests for the pipeline stages (SPEC §5, PLAN task B).

Everything here matches diagnostics on ``code`` — never on ``message`` — because
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import math
import random

import pytest

from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    ReferenceOutline,
    Severity,
    SourceInfo,
)
from aidrill.protocols import Pipeline, Stage
from aidrill.pipeline import (
    CheckReferenceSize,
    ClusterDiameters,
    Deduplicate,
    DiameterStrategy,
    NoNormalization,
    NormalizeDiameters,
    SnapPositions,
    SortHoles,
    TableDiameters,
)
from tests.conftest import at, make_data


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def codes(data: DrillData) -> list[str]:
    return [d.code for d in data.diagnostics]


def positions(data: DrillData) -> list[tuple[float, float]]:
    return [(h.x, h.y) for h in data.holes]


def diameters(data: DrillData) -> list[float]:
    return [h.diameter for h in data.holes]


ALL_STAGES = [
    SnapPositions(grid=0.25),
    NormalizeDiameters(ClusterDiameters()),
    Deduplicate(),
    CheckReferenceSize((113.0, 60.0)),
    SortHoles(),
]


# --------------------------------------------------------------------------
# protocol conformance and purity (LSP / SRP)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_every_stage_satisfies_the_stage_protocol(stage):
    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str) and type(stage).name


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_are_pure_functions(stage):
    """A stage may not mutate its input, and must be deterministic."""
    data = make_data(
        at(-40.003, 18.002, 6.9998, index=0),
        at(-40.0, 18.0, 7.0000, index=1),
        at(19.0, -18.75, 5.0, index=2),
        reference=ReferenceOutline(113.0, 60.0),
    )
    before_holes, before_diags = data.holes, data.diagnostics

    first = stage.apply(data)
    second = stage.apply(data)

    assert data.holes == before_holes, "stage mutated input holes"
    assert data.diagnostics == before_diags, "stage mutated input diagnostics"
    assert isinstance(first, DrillData)
    assert first.holes == second.holes
    assert codes(first) == codes(second)


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_survive_empty_input(stage):
    """No stage may assume it has holes, or that a predecessor ran (LSP).

    Surviving means more than "returned something with no holes": a stage that
    bailed out with a bare ``DrillData()`` would drop the reference outline, the
    source provenance and every diagnostic raised before it, and the pipeline
    would carry on as though the panel had never had an outline at all.
    """
    prior = Diagnostic.info("prior", "something earlier said this")
    data = DrillData(
        holes=(),
        reference=ReferenceOutline(113.0, 60.0),
        diagnostics=(prior,),
        source=SourceInfo(path="test"),
    )

    out = stage.apply(data)

    assert out.holes == ()
    assert out.reference == data.reference, "an early return dropped the reference"
    assert out.source == data.source, "an early return dropped the provenance"
    assert prior in out.diagnostics, "an early return dropped earlier diagnostics"

    # And the wholly default value object must not raise either.
    assert stage.apply(DrillData()).holes == ()


@pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
def test_stages_preserve_existing_diagnostics(stage):
    prior = Diagnostic.info("prior", "something earlier said this")
    data = make_data(at(0.0, 0.0, 7.0, index=0)).with_diagnostics(prior)
    assert prior in stage.apply(data).diagnostics


# --------------------------------------------------------------------------
# SnapPositions
# --------------------------------------------------------------------------


class TestSnapPositions:
    def test_snaps_to_the_grid(self):
        out = SnapPositions(0.25).apply(make_data(at(-39.99, 18.01, index=0)))
        assert positions(out) == [(-40.0, 18.0)]

    def test_zero_grid_is_identity_with_no_diagnostics(self):
        data = make_data(at(-39.99, 18.01, index=0), at(0.13, -7.77, index=1))
        out = SnapPositions(0.0).apply(data)
        assert positions(out) == positions(data)
        assert out.diagnostics == ()

    def test_keeps_raw_provenance(self):
        out = SnapPositions(0.25).apply(make_data(at(-39.9906, 18.0, index=0)))
        hole = out.holes[0]
        assert hole.raw.x == pytest.approx(-39.9906)
        assert hole.x == pytest.approx(-40.0)
        assert hole.residual[0] == pytest.approx(-0.0094, abs=1e-9)

    def test_diameter_is_untouched(self):
        out = SnapPositions(0.25).apply(make_data(at(0.01, 0.01, 6.9998, index=0)))
        assert diameters(out) == [6.9998]

    def test_small_move_does_not_warn(self):
        # default warn_over is grid / 4 == 0.0625; this hole moves 0.01
        out = SnapPositions(0.25).apply(make_data(at(-39.99, 18.0, index=0)))
        assert codes(out) == []

    def test_large_move_emits_off_grid_warning(self):
        out = SnapPositions(0.25).apply(make_data(at(-39.9, 18.0, index=0)))
        assert codes(out) == ["off-grid"]
        diag = out.diagnostics[0]
        assert diag.severity is Severity.WARNING
        assert diag.location == (-40.0, 18.0)

    def test_explicit_warn_over_overrides_the_default(self):
        data = make_data(at(-39.9, 18.0, index=0))
        assert codes(SnapPositions(0.25, warn_over=0.2).apply(data)) == []
        assert codes(SnapPositions(0.25, warn_over=0.05).apply(data)) == ["off-grid"]

    def test_one_diagnostic_per_offending_hole(self):
        data = make_data(
            at(-39.9, 18.0, index=0), at(-20.0, 18.0, index=1), at(0.1, 18.0, index=2)
        )
        assert codes(SnapPositions(0.25).apply(data)) == ["off-grid", "off-grid"]

    def test_regression_grid_half_moves_the_five_mm_row_a_quarter_millimetre(self):
        """SPEC §9 regression: at --grid 0.5 the two ⌀5 holes go off-grid."""
        data = make_data(at(-19.0, -18.75, 5.0, index=0), at(19.0, -18.75, 5.0, index=1))
        out = SnapPositions(0.5).apply(data)

        assert codes(out) == ["off-grid", "off-grid"]
        for hole in out.holes:
            dx, dy, _ = hole.residual
            assert math.hypot(dx, dy) == pytest.approx(0.25)
        assert [h.x for h in out.holes] == [-19.0, 19.0]

    def test_property_snapping_is_idempotent(self):
        rng = random.Random(20250814)
        for _ in range(300):
            grid = rng.choice([0.05, 0.1, 0.25, 0.5, 1.0, 0.3])
            stage = SnapPositions(grid)
            data = make_data(
                *(at(rng.uniform(-60, 60), rng.uniform(-30, 30), index=i) for i in range(5))
            )
            once = stage.apply(data)
            twice = stage.apply(once)
            assert positions(twice) == positions(once)
            assert codes(twice) == codes(once), "a snapped hole cannot still be off grid"


# --------------------------------------------------------------------------
# NormalizeDiameters + strategies
# --------------------------------------------------------------------------


class TestNormalizeDiameters:
    def test_measurement_noise_yields_exactly_one_tool(self):
        """THE regression this whole stage exists for (SPEC §5.1).

        6.9998 and 7.0000 are one 7 mm hole that a measurement split in two.
        Before this stage existed the Excellon writer clustered them itself and
        the drawing did not, so the two artifacts disagreed about tool count.
        """
        data = make_data(at(-40.0, 18.0, 6.9998, index=0), at(-20.0, 18.0, 7.0000, index=1))

        out = NormalizeDiameters(ClusterDiameters(0.05)).apply(data)

        assert len(out.tools()) == 1
        assert diameters(out) == [7.0, 7.0]
        assert list(out.tools()) == [7.0]

    def test_raw_diameters_survive_normalisation(self):
        data = make_data(at(0.0, 0.0, 6.9998, index=0))
        out = NormalizeDiameters(ClusterDiameters(0.05)).apply(data)
        assert out.holes[0].raw.diameter == pytest.approx(6.9998)
        assert out.holes[0].residual[2] == pytest.approx(0.0002, abs=1e-9)

    def test_positions_are_untouched(self):
        data = make_data(at(-39.99, 18.01, 6.9998, index=0))
        out = NormalizeDiameters(ClusterDiameters()).apply(data)
        assert positions(out) == [(-39.99, 18.01)]

    def test_no_diagnostics_from_clustering(self):
        data = make_data(at(0.0, 0.0, 6.9998, index=0), at(1.0, 0.0, 7.0, index=1))
        assert codes(NormalizeDiameters(ClusterDiameters()).apply(data)) == []


class TestClusterDiameters:
    def test_distinct_sizes_are_not_merged(self):
        data = make_data(
            at(0.0, 0.0, 5.0, index=0),
            at(1.0, 0.0, 7.0, index=1),
            at(2.0, 0.0, 5.0, index=2),
        )
        out = NormalizeDiameters(ClusterDiameters(0.05)).apply(data)
        assert len(out.tools()) == 2
        assert diameters(out) == [5.0, 7.0, 5.0]

    def test_does_not_chain_beyond_tolerance_from_the_representative(self):
        """Greedy single-linkage would chain 5.00→5.04→5.08 into one group.

        The ends are 0.08 apart, well beyond the 0.05 tolerance. Membership is
        measured from the group's representative, not from the previous member.
        """
        data = make_data(
            at(0.0, 0.0, 5.00, index=0),
            at(1.0, 0.0, 5.04, index=1),
            at(2.0, 0.0, 5.08, index=2),
        )

        out = NormalizeDiameters(ClusterDiameters(0.05)).apply(data)

        assert len(out.tools()) == 2
        assert out.holes[0].diameter == out.holes[1].diameter
        assert out.holes[2].diameter != out.holes[0].diameter

    def test_a_tolerance_finer_than_a_hundredth_keeps_its_groups_apart(self):
        """Regression: rounding the nominal to a fixed 2 dp re-merged what the
        tolerance had deliberately separated.

        With a 0.001 tolerance these are three groups — the operator asked for
        sub-hundredth sizes to stay apart — but a nominal rounded to 2 dp gave
        all three the same 7.0, collapsing three tools into one, silently.
        """
        mapping = ClusterDiameters(0.001).nominal([7.0000, 7.0020, 7.0040])

        assert len(set(mapping.values())) == 3, "distinct groups share a nominal"
        assert mapping[7.0000] == pytest.approx(7.000)
        assert mapping[7.0020] == pytest.approx(7.002)
        assert mapping[7.0040] == pytest.approx(7.004)

    def test_a_fine_tolerance_does_not_corrupt_an_imperial_size(self):
        """3.175 mm is 1/8"; at 2 dp it became 3.17, a size no bit has."""
        mapping = ClusterDiameters(0.005).nominal([3.175, 6.35])
        assert mapping[3.175] == pytest.approx(3.175)
        assert mapping[6.35] == pytest.approx(6.35)

    def test_no_group_ever_spans_more_than_the_tolerance(self):
        rng = random.Random(4242)
        for _ in range(400):
            # Tolerances below 0.01 are the interesting ones: at 0.02 and coarser
            # a 2 dp nominal cannot make two groups collide, which is exactly why
            # the earlier sampling of {0.02, 0.05, 0.1} missed the bug above.
            tolerance = rng.choice([0.02, 0.05, 0.1, 0.005, 0.002, 0.001])
            # A narrow band at 4 dp puts many values inside one hundredth of a
            # millimetre of each other, so a collision is likely rather than rare.
            measured = [round(rng.uniform(6.9, 7.1), 4) for _ in range(12)]
            mapping = ClusterDiameters(tolerance).nominal(measured)

            groups: dict[float, list[float]] = {}
            for m in measured:
                groups.setdefault(mapping[m], []).append(m)
            for members in groups.values():
                assert max(members) - min(members) <= tolerance + 1e-9

    def test_representative_is_the_mean_rounded_to_the_tolerance_precision(self):
        mapping = ClusterDiameters(0.05).nominal([6.9998, 7.0000])
        assert set(mapping.values()) == {7.0}

        mapping = ClusterDiameters(0.05).nominal([5.00, 5.04])
        assert set(mapping.values()) == {5.02}

        # A finer tolerance buys finer nominals; a coarse one never goes below 2 dp.
        assert set(ClusterDiameters(0.001).nominal([5.0010, 5.0016]).values()) == {5.001}
        assert set(ClusterDiameters(1.0).nominal([5.004, 5.008]).values()) == {5.01}

    def test_ordering_of_input_does_not_change_the_result(self):
        measured = [7.0000, 5.02, 6.9998, 4.98, 5.0]
        forward = ClusterDiameters(0.05).nominal(measured)
        backward = ClusterDiameters(0.05).nominal(list(reversed(measured)))
        assert forward == backward

    def test_empty_input(self):
        assert dict(ClusterDiameters().nominal([])) == {}


class TestTableDiameters:
    SIZES = [3.2, 5.0, 6.35, 7.0]

    def test_snaps_to_the_nearest_declared_size(self):
        data = make_data(at(0.0, 0.0, 6.98, index=0), at(1.0, 0.0, 5.03, index=1))
        out = NormalizeDiameters(TableDiameters(self.SIZES, 0.15)).apply(data)
        assert diameters(out) == [7.0, 5.0]
        assert codes(out) == []

    def test_value_outside_tolerance_is_kept_and_reported(self):
        data = make_data(at(-3.0, 2.0, 4.1, index=0))
        out = NormalizeDiameters(TableDiameters(self.SIZES, 0.15)).apply(data)

        assert diameters(out) == [4.1]
        assert codes(out) == ["unknown-diameter"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.diagnostics[0].location == (-3.0, 2.0)

    def test_one_diagnostic_per_offending_hole(self):
        data = make_data(
            at(0.0, 0.0, 4.1, index=0),
            at(1.0, 0.0, 4.1, index=1),
            at(2.0, 0.0, 7.0, index=2),
        )
        out = NormalizeDiameters(TableDiameters(self.SIZES, 0.15)).apply(data)
        assert codes(out) == ["unknown-diameter", "unknown-diameter"]

    def test_tolerance_boundary_is_inclusive(self):
        assert dict(TableDiameters([7.0], 0.15).nominal([6.85])) == {6.85: 7.0}
        assert dict(TableDiameters([7.0], 0.15).nominal([6.84])) == {}

    def test_ties_are_resolved_deterministically(self):
        # 6.0 is equidistant from 5.0 and 7.0; the smaller size wins, always.
        assert dict(TableDiameters([5.0, 7.0], 1.0).nominal([6.0])) == {6.0: 5.0}

    def test_empty_table_reports_everything_unknown(self):
        data = make_data(at(0.0, 0.0, 7.0, index=0))
        out = NormalizeDiameters(TableDiameters([], 0.15)).apply(data)
        assert diameters(out) == [7.0]
        assert codes(out) == ["unknown-diameter"]


class TestNoNormalization:
    def test_is_the_identity(self):
        data = make_data(at(0.0, 0.0, 6.9998, index=0), at(1.0, 0.0, 7.0000, index=1))
        out = NormalizeDiameters(NoNormalization()).apply(data)
        assert diameters(out) == [6.9998, 7.0000]
        assert len(out.tools()) == 2
        assert codes(out) == []


class TestStrategyPatternIsOpenForExtension:
    """OCP: a fourth strategy must work without editing NormalizeDiameters."""

    def test_the_three_shipped_strategies_satisfy_the_protocol(self):
        for strategy in (ClusterDiameters(), TableDiameters([7.0]), NoNormalization()):
            assert isinstance(strategy, DiameterStrategy)

    def test_a_strategy_defined_here_needs_no_change_to_the_stage(self):
        class RoundToWholeMillimetres:
            """A fourth strategy, invented in this test file and nowhere else."""

            def nominal(self, measured):
                return {m: float(round(m)) for m in measured}

        strategy = RoundToWholeMillimetres()
        assert isinstance(strategy, DiameterStrategy)

        data = make_data(at(0.0, 0.0, 6.9998, index=0), at(1.0, 0.0, 5.4, index=1))
        out = NormalizeDiameters(strategy).apply(data)

        assert diameters(out) == [7.0, 5.0]
        assert codes(out) == []

    def test_unresolved_values_are_reported_generically(self):
        """A strategy signals "no nominal" by omitting the key; the stage
        reports it. That contract, not an isinstance check, is what keeps
        NormalizeDiameters closed for modification."""

        class RefusesEverything:
            def nominal(self, measured):
                return {}

        data = make_data(at(0.0, 0.0, 6.9998, index=0))
        out = NormalizeDiameters(RefusesEverything()).apply(data)

        assert diameters(out) == [6.9998]
        assert codes(out) == ["unknown-diameter"]


# --------------------------------------------------------------------------
# Deduplicate
# --------------------------------------------------------------------------


class TestDeduplicate:
    def test_collapses_coincident_holes_of_equal_diameter(self):
        data = make_data(at(-40.0, 18.0, 7.0, index=0), at(-40.01, 18.02, 7.0, index=1))
        out = Deduplicate(0.05).apply(data)
        assert len(out.holes) == 1

    def test_keeps_the_first_hole_in_input_order(self):
        first, second = at(-40.0, 18.0, 7.0, index=0), at(-40.01, 18.02, 7.0, index=1)
        out = Deduplicate(0.05).apply(make_data(first, second))
        assert out.holes == (first,)

    def test_emits_one_warning_per_collapsed_group(self):
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            at(-40.01, 18.0, 7.0, index=1),
            at(-40.02, 18.0, 7.0, index=2),
            at(0.0, 0.0, 7.0, index=3),
        )
        out = Deduplicate(0.05).apply(data)

        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.diagnostics[0].location == (-40.0, 18.0)

    def test_two_groups_two_warnings(self):
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            at(-40.0, 18.0, 7.0, index=1),
            at(20.0, 18.0, 7.0, index=2),
            at(20.0, 18.0, 7.0, index=3),
        )
        out = Deduplicate(0.05).apply(data)
        assert len(out.holes) == 2
        assert codes(out) == ["duplicate-hole", "duplicate-hole"]

    def test_does_not_collapse_different_diameters_at_the_same_place(self):
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.0, 0.0, 5.0, index=1))
        out = Deduplicate(0.05).apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    def test_tolerance_boundary_is_inclusive(self):
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.05, 0.0, 7.0, index=1))
        assert len(Deduplicate(0.05).apply(data).holes) == 1

    def test_does_not_collapse_holes_further_apart_than_the_tolerance(self):
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.06, 0.0, 7.0, index=1))
        out = Deduplicate(0.05).apply(data)
        assert len(out.holes) == 2
        assert codes(out) == []

    def test_tolerance_is_a_radial_distance(self):
        # dx = dy = 0.04 -> distance 0.0566, outside a 0.05 tolerance
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.04, 0.04, 7.0, index=1))
        assert len(Deduplicate(0.05).apply(data).holes) == 2

    def test_unnormalised_diameters_are_not_treated_as_equal(self):
        """Dedupe does not do the diameter stage's job (SRP)."""
        data = make_data(at(0.0, 0.0, 6.9998, index=0), at(0.0, 0.0, 7.0000, index=1))
        assert len(Deduplicate(0.05).apply(data).holes) == 2

    def test_diagnostic_carries_a_machine_readable_payload(self):
        """A consumer must be able to identify the survivor without re-deriving it.

        The drawing emitter has to mark the duplicate it was told about. Given
        only a rounded message it re-implemented this stage's rule — with its own
        tolerance and no diameter check — and flagged holes the pipeline had not.
        ``location`` is therefore the survivor's exact post-dedupe coordinate, so
        a consumer matches on ``==`` and needs no tolerance of its own.
        """
        survivor = at(-40.0031, 18.0007, 7.0, index=0)
        data = make_data(
            survivor,
            at(-40.0129, 18.0203, 7.0, index=1),
            at(-39.9902, 17.9885, 7.0, index=2),
            at(0.0, 0.0, 5.0, index=3),  # a lonely hole raises nothing
        )

        out = Deduplicate(0.05).apply(data)

        assert codes(out) == ["duplicate-hole"]
        diag = out.diagnostics[0]
        assert diag.location == (survivor.x, survivor.y)
        assert diag.location == (out.holes[0].x, out.holes[0].y)
        assert diag.get("diameter") == survivor.diameter
        assert diag.get("dropped") == 2
        assert diag.get("kept") == 1

    def test_property_dedupe_is_idempotent(self):
        rng = random.Random(90210)
        for _ in range(300):
            holes = []
            for _ in range(8):
                x, y = rng.uniform(-50, 50), rng.uniform(-25, 25)
                dia = rng.choice([5.0, 7.0])
                holes.append(at(x, y, dia, index=len(holes)))
                if rng.random() < 0.4:  # sprinkle near-duplicates
                    holes.append(
                        at(x + rng.uniform(-0.03, 0.03), y, dia, index=len(holes))
                    )
            stage = Deduplicate(0.05)
            once = stage.apply(make_data(*holes))
            twice = stage.apply(once)
            assert twice.holes == once.holes
            assert codes(twice) == codes(once), "second pass found new duplicates"


def test_duplicate_diagnostic_identifies_the_survivor_by_index_not_position():
    """The referent must survive a later coordinate change.

    protocols.py forbids a stage assuming its predecessor, so Deduplicate may
    legitimately run before SnapPositions. When it does, the survivor moves
    after the diagnostic is written and a position-keyed referent goes stale.
    """
    data = make_data(
        Hole.from_measurement(10.03, 5.02, 7.0, index=0),
        Hole.from_measurement(10.04, 5.02, 7.0, index=1),
    )
    after = Pipeline([Deduplicate(tolerance=0.05), SnapPositions(grid=0.25)]).run(data)

    duplicates = [d for d in after.diagnostics if d.code == "duplicate-hole"]
    assert len(duplicates) == 1
    survivor_index = duplicates[0].get("hole_index")
    assert survivor_index is not None
    assert [h.index for h in after.holes] == [survivor_index]


# --------------------------------------------------------------------------
# CheckReferenceSize
# --------------------------------------------------------------------------


class TestCheckReferenceSize:
    def test_matching_outline_is_silent(self):
        data = make_data(at(0.0, 0.0, index=0), reference=ReferenceOutline(113.0, 60.0))
        assert codes(CheckReferenceSize((113.0, 60.0)).apply(data)) == []

    def test_mismatch_warns(self):
        data = make_data(at(0.0, 0.0, index=0), reference=ReferenceOutline(112.4, 60.0))
        out = CheckReferenceSize((113.0, 60.0)).apply(data)
        assert codes(out) == ["reference-size-mismatch"]
        assert out.diagnostics[0].severity is Severity.WARNING

    def test_is_a_pure_validator_and_returns_holes_untouched(self):
        holes = (at(-40.0, 18.0, index=0), at(20.0, -18.75, 5.0, index=1))
        data = make_data(*holes, reference=ReferenceOutline(100.0, 60.0))
        out = CheckReferenceSize((113.0, 60.0)).apply(data)
        assert out.holes == holes
        assert out.reference == data.reference

    def test_tolerance_boundary(self):
        data = make_data(reference=ReferenceOutline(113.05, 60.0))
        assert codes(CheckReferenceSize((113.0, 60.0), 0.05).apply(data)) == []
        data = make_data(reference=ReferenceOutline(113.06, 60.0))
        assert codes(CheckReferenceSize((113.0, 60.0), 0.05).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_boundary_is_inclusive_despite_float_representation(self):
        """Regression: 60.1 - 60.0 == 0.10000000000000142, not 0.1.

        The user declared 60.0 and drew 60.1 with a 0.1 tolerance — a match they
        typed exactly — and got a warning, because this check was the one place
        in the pipeline that compared a float difference without any slack.
        """
        data = make_data(reference=ReferenceOutline(60.1, 60.0))
        assert codes(CheckReferenceSize((60.0, 60.0), 0.1).apply(data)) == []

        data = make_data(reference=ReferenceOutline(60.0, 60.1))
        assert codes(CheckReferenceSize((60.0, 60.0), 0.1).apply(data)) == []

        # Slack absorbs representation error only; a real excess still warns.
        data = make_data(reference=ReferenceOutline(60.2, 60.0))
        assert codes(CheckReferenceSize((60.0, 60.0), 0.1).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_height_mismatch_alone_is_enough(self):
        data = make_data(reference=ReferenceOutline(113.0, 59.0))
        assert codes(CheckReferenceSize((113.0, 60.0)).apply(data)) == [
            "reference-size-mismatch"
        ]

    def test_missing_outline_is_an_info_not_a_raise(self):
        data = make_data(at(0.0, 0.0, index=0))
        out = CheckReferenceSize((113.0, 60.0)).apply(data)
        assert codes(out) == ["no-reference-outline"]
        assert out.diagnostics[0].severity is Severity.INFO
        assert out.holes == data.holes


# --------------------------------------------------------------------------
# SortHoles
# --------------------------------------------------------------------------


class TestSortHoles:
    def test_default_is_descending_y_then_ascending_x(self):
        data = make_data(
            at(20.0, -18.75, 5.0, index=0),
            at(-20.0, 18.0, index=1),
            at(-40.0, 18.0, index=2),
            at(-20.0, -18.75, 5.0, index=3),
        )
        out = SortHoles().apply(data)
        assert positions(out) == [
            (-40.0, 18.0),
            (-20.0, 18.0),
            (-20.0, -18.75),
            (20.0, -18.75),
        ]

    def test_accepts_a_custom_key(self):
        data = make_data(
            at(0.0, 0.0, 7.0, index=0),
            at(10.0, 0.0, 3.2, index=1),
            at(-10.0, 0.0, 5.0, index=2),
        )
        out = SortHoles(key=lambda h: h.diameter).apply(data)
        assert diameters(out) == [3.2, 5.0, 7.0]

    def test_is_deterministic_under_input_permutation(self):
        holes = [
            at(-40.0, 18.0, index=0),
            at(0.0, 18.0, index=1),
            at(-19.0, -18.75, 5.0, index=2),
            at(20.0, 18.0, index=3),
        ]
        rng = random.Random(7)
        expected = SortHoles().apply(make_data(*holes)).holes
        for _ in range(20):
            shuffled = holes[:]
            rng.shuffle(shuffled)
            assert SortHoles().apply(make_data(*shuffled)).holes == expected

    def test_emits_no_diagnostics(self):
        data = make_data(at(0.0, 0.0, index=0), at(1.0, 1.0, index=1))
        assert codes(SortHoles().apply(data)) == []

    def test_tools_are_stable_under_hole_reordering(self):
        """SPEC §9 property: tools() does not depend on hole order."""
        holes = [at(0.0, 0.0, 7.0, index=0), at(1.0, 0.0, 5.0, index=1), at(2.0, 0.0, 3.2, index=2)]
        rng = random.Random(11)
        expected = dict(make_data(*holes).tools())
        for _ in range(20):
            shuffled = holes[:]
            rng.shuffle(shuffled)
            assert dict(make_data(*shuffled).tools()) == expected
            assert dict(SortHoles().apply(make_data(*shuffled)).tools()) == expected


# --------------------------------------------------------------------------
# Composition: Pipeline is a left fold and stage order is observable
# --------------------------------------------------------------------------


class TestPipelineComposition:
    def test_empty_pipeline_is_the_identity(self):
        data = make_data(at(0.0, 0.0, index=0))
        assert Pipeline([]).run(data) is data

    def test_run_is_a_left_fold(self):
        calls: list[str] = []

        class Recorder:
            name = "recorder"

            def __init__(self, tag: str) -> None:
                self.tag = tag

            def apply(self, data: DrillData) -> DrillData:
                calls.append(self.tag)
                return data.with_diagnostics(Diagnostic.info(self.tag, self.tag))

        out = Pipeline([Recorder("a"), Recorder("b"), Recorder("c")]).run(make_data())
        assert calls == ["a", "b", "c"]
        assert codes(out) == ["a", "b", "c"]

    def test_stage_order_is_observable(self):
        """snap-then-dedupe collapses a near-duplicate that dedupe-then-snap does not.

        The two holes are 0.06 mm apart — outside the 0.05 dedupe tolerance —
        but both snap onto the same 0.25 mm grid point.
        """
        data = make_data(at(0.0, 0.0, 7.0, index=0), at(0.06, 0.0, 7.0, index=1))
        snap, dedupe = SnapPositions(0.25), Deduplicate(0.05)

        snap_first = Pipeline([snap, dedupe]).run(data)
        dedupe_first = Pipeline([dedupe, snap]).run(data)

        assert len(snap_first.holes) == 1
        assert "duplicate-hole" in codes(snap_first)

        assert len(dedupe_first.holes) == 2
        assert "duplicate-hole" not in codes(dedupe_first)

    def test_the_canonical_order_yields_one_tool_for_a_noisy_seven_mm_row(self):
        """End-to-end shape of the CLI pipeline (PLAN task F order)."""
        data = make_data(
            at(-40.003, 18.001, 6.9998, index=0),
            at(-40.0, 18.0, 7.0000, index=1),  # duplicate of the above, once snapped
            at(-20.0, 18.0, 7.0001, index=2),
            at(-19.0, -18.75, 5.0002, index=3),
            at(19.0, -18.75, 4.9998, index=4),
            reference=ReferenceOutline(113.0, 60.0),
        )

        out = Pipeline(
            [
                SnapPositions(0.25),
                NormalizeDiameters(ClusterDiameters(0.05)),
                Deduplicate(0.05),
                CheckReferenceSize((113.0, 60.0)),
                SortHoles(),
            ]
        ).run(data)

        assert len(out.holes) == 4
        assert len(out.tools()) == 2
        assert list(out.tools()) == [5.0, 7.0]
        assert codes(out) == ["duplicate-hole"]
        assert positions(out) == [
            (-40.0, 18.0),
            (-20.0, 18.0),
            (-19.0, -18.75),
            (19.0, -18.75),
        ]
