"""Unit and property tests for the pipeline stages (SPEC §5, PLAN task B).

Everything here matches diagnostics on ``code`` — never on ``message`` — because
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random

import pytest

from aidrill.enclosures import footprints
from aidrill.emitters.json_out import JsonEmitter
from aidrill.pipeline import enclosure as enclosure_stage
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.protocols import Pipeline, Stage
from aidrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    CheckReferenceSize,
    Deduplicate,
    DrillStandard,
    IdentifyHammondFootprint,
    SnapDiametersToDrillTable,
    SnapPositions,
    SortHoles,
    normalize_part_name,
)
from tests.conftest import at, holes, make_data


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
    SnapDiametersToDrillTable(),
    Deduplicate(),
    CheckReferenceSize((113.0, 60.0)),
    SortHoles(),
    IdentifyHammondFootprint(),
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
    # 112 × 61 rather than the fixture's measured 113 × 60: it is a catalogue
    # footprint exactly, so IdentifyHammondFootprint's snap is the identity and
    # ``out.reference == data.reference`` still means "the outline was not
    # dropped" for every stage. Asserting only that it is not None would have
    # weakened the check for the five stages that must not touch it at all.
    data = DrillData(
        holes=(),
        reference=ReferenceOutline(112.0, 61.0),
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
# The drill standards, and snapping onto one of them
# --------------------------------------------------------------------------


class TestTheMetricSeriesIsGeneratedNotTranscribed:
    """A rule cannot carry a transcription typo, so the bands are the source."""

    METRIC = DRILL_STANDARDS["metric"]

    def test_the_bands_cover_half_a_millimetre_to_twenty_five(self):
        assert len(self.METRIC.sizes_mm) == 183
        assert self.METRIC.sizes_mm[0] == 0.5
        assert self.METRIC.sizes_mm[-1] == 25.0

    def test_each_band_steps_at_its_own_pitch_right_up_to_the_next_one(self):
        """The last size of a band and the first of the next, both spellings.

        A band boundary moved either way shows up here rather than only in a
        count: 2.95 is the last of the 0.05 band and 3.0 the first of the 0.1
        band, so a first band that ran to 3.5 would put 3.05 in the table and a
        second that started at 3.5 would take 3.0 out of it.
        """
        sizes = set(self.METRIC.sizes_mm)
        assert {2.95, 3.0, 13.9, 14.0, 14.5, 25.0} <= sizes
        assert 3.05 not in sizes, "the 0.05 band ran past its stop"
        assert 13.95 not in sizes, "the 0.1 band ran past its stop"
        assert 25.5 not in sizes, "the stop of the last band is exclusive too"

    def test_the_series_is_ascending_and_has_no_size_twice(self):
        sizes = self.METRIC.sizes_mm
        assert list(sizes) == sorted(sizes)
        assert len(set(sizes)) == len(sizes)

    def test_the_table_is_dense_enough_that_in_range_matching_cannot_fail(self):
        """``SnapDiametersToDrillTable`` says so in prose; this is the arithmetic.

        The widest step anywhere is the 0.5 mm one in the top band, so the
        furthest a measurement inside 0.5–25.0 mm can sit from a size is exactly
        half of that — which is the default tolerance, and ``within`` is
        inclusive. It is the table's *density* that protects a panel in range,
        not the tolerance number.

        Derived from the series rather than restated, so a band edited to step
        more coarsely fails here instead of leaving that docstring a lie.
        """
        sizes = self.METRIC.sizes_mm
        widest = max(sizes[i + 1] - sizes[i] for i in range(len(sizes) - 1))

        assert widest == 0.5
        assert SnapDiametersToDrillTable().tolerance_mm >= widest / 2


class TestTheFractionalSeriesIsExactByConstruction:
    FRACTIONAL = DRILL_STANDARDS["fractional"]

    def test_sixty_four_sixty_fourths_up_to_one_inch(self):
        """``n * 25.4 / 64`` for 1..64 — the last one being a 1" bit exactly.

        The count and the top of the series are asserted apart, because they
        fail for different edits: a series stopping at 63 is one bit short *and*
        no longer reaches an inch, and only the second says which end went.
        """
        assert len(self.FRACTIONAL.sizes_mm) == 64
        assert self.FRACTIONAL.sizes_mm[-1] == 25.4

    def test_the_common_bits_are_exact_millimetres_with_no_rounding_anywhere(self):
        sizes = self.FRACTIONAL.sizes_mm
        assert sizes[0] == 25.4 / 64  # 1/64", 0.396875 mm
        assert sizes[7] == 3.175  # 1/8"
        assert sizes[15] == 6.35  # 1/4"
        assert sizes[31] == 12.7  # 1/2"

    def test_the_series_is_ascending_and_has_no_size_twice(self):
        sizes = self.FRACTIONAL.sizes_mm
        assert list(sizes) == sorted(sizes)
        assert len(set(sizes)) == len(sizes)


class TestLabels:
    """What gets stamped on a drawing for each size."""

    @pytest.mark.parametrize("standard", DRILL_STANDARDS.values(), ids=lambda s: s.name)
    def test_every_size_has_a_label_that_is_unique_within_its_standard(self, standard):
        """This is what makes the drawing's schedule safe without a per-emitter guard.

        It must run per standard. A decimal-millimetre label cannot serve both:
        the metric series is unique *and* truthful at 2 dp, but 1/64" is
        0.396875 mm, which no finite decimal-mm label states exactly — so the
        fractional standard labels in sixty-fourths instead.
        """
        labels = [standard.label(d) for d in standard.sizes_mm]
        assert len(set(labels)) == len(labels), f"{standard.name}: two sizes share a label"

    def test_a_metric_label_states_its_size_exactly(self):
        metric = DRILL_STANDARDS["metric"]
        assert all(f"{d:.2f}" in metric.label(d) for d in metric.sizes_mm)
        assert metric.label(3.2) == "⌀3.20 mm"

    def test_a_fractional_label_is_the_fraction_not_a_rounded_millimetre(self):
        """0.40 mm would be a lie about a 1/64" bit, and 3.18 mm about a 1/8" one."""
        fractional = DRILL_STANDARDS["fractional"]
        assert fractional.label(25.4 / 64) == '⌀1/64"'
        assert fractional.label(25.4 / 8) == '⌀1/8"'
        assert fractional.label(12.7) == '⌀1/2"'
        assert fractional.label(25.4) == '⌀1"'

    def test_no_fractional_label_would_survive_being_written_in_millimetres(self):
        """Measured, not assumed: the fractional series is truthful at *no*
        decimal precision, which is why ``label`` is a function and not a
        ``display_decimals`` int. Every bit whose label is a proper fraction
        misstates its own millimetre value at 2, 3 and 4 decimals."""
        fractional = DRILL_STANDARDS["fractional"]
        for decimals in (2, 3, 4):
            lying = [d for d in fractional.sizes_mm if float(f"{d:.{decimals}f}") != d]
            assert lying, f"a decimal-mm label at {decimals} dp would be truthful"


class TestTheTwoStandardsAreNeverMerged:
    def test_one_size_belongs_to_both_series_under_two_names(self):
        """1/2" *is* 12.7 mm — the same physical bit, zero millimetres apart.

        Merged into one table it would appear twice, with two labels, and the
        unique-label invariant above would be unsatisfiable by construction.
        """
        metric = set(DRILL_STANDARDS["metric"].sizes_mm)
        fractional = set(DRILL_STANDARDS["fractional"].sizes_mm)
        assert metric & fractional == {12.7}
        assert DRILL_STANDARDS["metric"] is not DRILL_STANDARDS["fractional"]

    def test_neighbouring_sizes_across_the_two_series_are_closer_than_the_tolerance(self):
        """3.175 (1/8") and 3.2 (metric) are 0.025 mm apart, a tenth of the
        matching tolerance. In one table the choice between them would be
        decided by float ordering rather than by anything real."""
        metric = DRILL_STANDARDS["metric"].sizes_mm
        fractional = DRILL_STANDARDS["fractional"].sizes_mm
        crowded = [(a, b) for a in fractional for b in metric if 0.0 < abs(a - b) < 0.05]
        assert len(crowded) > 40  # 45 today; a halving of the crowding must fail

    def test_a_panel_is_drilled_with_one_set_of_bits(self):
        """The registry hands out whole standards, never a union of sizes."""
        assert set(DRILL_STANDARDS) == {"metric", "fractional"}
        assert all(isinstance(s, DrillStandard) for s in DRILL_STANDARDS.values())

    def test_the_default_standard_is_metric(self):
        assert DEFAULT_STANDARD == "metric"
        assert DRILL_STANDARDS[DEFAULT_STANDARD].name == "metric"

    def test_the_registry_cannot_be_rewritten_by_one_run(self):
        """A shared mutable registry would let one caller change another's bits."""
        with pytest.raises(TypeError):
            DRILL_STANDARDS["metric"] = DRILL_STANDARDS["fractional"]  # type: ignore[index]


class TestInventoryFiltering:
    """``select`` narrows a standard to the bits actually in the drawer."""

    METRIC = DRILL_STANDARDS["metric"]

    def test_a_whitelist_keeps_exactly_the_sizes_asked_for(self):
        # Scattered through the series on purpose: sizes that happen to be the
        # first few of the standard cannot tell selection from truncation.
        stocked = self.METRIC.select(include=(3.2, 5.0, 7.0, 12.0))
        assert stocked.sizes_mm == (3.2, 5.0, 7.0, 12.0)

    def test_a_whitelist_is_sorted_however_it_was_typed(self):
        assert self.METRIC.select(include=(12.0, 3.2, 7.0)).sizes_mm == (3.2, 7.0, 12.0)

    def test_a_blacklist_removes_exactly_the_sizes_named(self):
        """The bit that snapped, and nothing else, leaves the drawer."""
        thinned = self.METRIC.select(exclude=(3.2, 7.0, 12.0))
        assert len(thinned.sizes_mm) == len(self.METRIC.sizes_mm) - 3
        assert 3.2 not in thinned.sizes_mm
        assert 7.0 not in thinned.sizes_mm
        assert 12.0 not in thinned.sizes_mm
        assert 3.3 in thinned.sizes_mm and 6.9 in thinned.sizes_mm

    def test_a_blacklist_applies_on_top_of_a_whitelist(self):
        both = self.METRIC.select(include=(3.2, 5.0, 7.0, 12.0), exclude=(5.0,))
        assert both.sizes_mm == (3.2, 7.0, 12.0)

    def test_narrowing_leaves_the_standard_it_came_from_alone(self):
        """A narrowed copy, not an edit: the registry is shared by every run."""
        narrowed = self.METRIC.select(include=(3.2, 7.0))

        assert len(self.METRIC.sizes_mm) == 183, "select mutated the registry"
        assert narrowed is not self.METRIC
        assert narrowed.name == self.METRIC.name
        assert narrowed.label(3.2) == "⌀3.20 mm"

    def test_selecting_nothing_is_the_standard_itself(self):
        assert self.METRIC.select().sizes_mm == self.METRIC.sizes_mm

    def test_a_size_the_standard_does_not_have_is_refused_rather_than_ignored(self):
        """``--drill-sizes 3.33`` is a typo, and a silently empty drawer is the
        worst possible answer to it: every hole would then be unknown."""
        with pytest.raises(ValueError, match="3.33"):
            self.METRIC.select(include=(3.2, 3.33))
        with pytest.raises(ValueError, match="3.33"):
            self.METRIC.select(exclude=(3.33,))

    def test_a_metric_size_is_not_a_fractional_one(self):
        """The refusal is against the standard in hand, not against bits in general.

        3.2 mm is a real drill; it is not a *fractional* drill, and a drawer of
        imperial bits does not contain one.
        """
        with pytest.raises(ValueError, match="3.2"):
            DRILL_STANDARDS["fractional"].select(include=(3.2,))
        assert DRILL_STANDARDS["fractional"].select(include=(3.175,)).sizes_mm == (3.175,)

    def test_narrowing_a_standard_down_to_nothing_is_refused(self):
        with pytest.raises(ValueError, match="no sizes"):
            self.METRIC.select(include=(3.2,), exclude=(3.2,))


class TestSnapDiametersToDrillTable:
    def test_bezier_noise_collapses_onto_one_bit(self):
        """THE regression this stage exists for (SPEC §5.1).

        6.9998 and 7.0002 are one 7 mm hole that a measurement split in two.
        Before the pipeline owned this the Excellon writer clustered them itself
        and the drawing did not, so the two artifacts disagreed about tool count.
        """
        got = SnapDiametersToDrillTable().apply(
            make_data(*holes((0.0, 0.0, 6.9998), (10.0, 0.0, 7.0002)))
        )

        assert {h.diameter for h in got.holes} == {7.0}
        assert len(got.tools()) == 1
        assert codes(got) == []

    def test_the_declared_standard_decides_which_bit_a_measurement_is(self):
        """6.348 is a worn 1/4" bit *or* a wide 6.3 mm one, and no arithmetic can
        tell which. The operator declares the drawer; the stage does not guess.

        This is the fixture that a merged table could not have: the two answers
        are 0.05 mm apart, well inside the 0.25 mm matching tolerance, so a
        single sorted table would decide between them by float ordering.
        """
        measured = make_data(*holes((0.0, 0.0, 6.348)))

        metric = SnapDiametersToDrillTable(DRILL_STANDARDS["metric"]).apply(measured)
        imperial = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]).apply(measured)

        assert diameters(metric) == [6.3]
        assert diameters(imperial) == [6.35]

    def test_a_quarter_inch_bit_keeps_its_own_size_and_is_not_rounded(self):
        """6.35 is a 1/4" bit, and it stays 6.35 exactly.

        Two things could have taken it away and neither may. A 0.25 mm rounding
        grid — the tolerance misused as a step — would put it at 6.25, a size no
        bit in either series has. And 6.35 is *not* a metric size (that band
        steps 6.3, 6.4), so a table that quietly held both series would have
        somewhere else to put it.
        """
        got = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]).apply(
            make_data(*holes((0.0, 0.0, 6.348)))
        )

        assert got.holes[0].diameter == 6.35
        assert 6.35 in DRILL_STANDARDS["fractional"].sizes_mm
        assert 6.35 not in DRILL_STANDARDS["metric"].sizes_mm

    def test_a_diameter_no_bit_can_make_is_an_error_not_a_guess(self):
        """A 30 mm cut-out is a step-drill or a punch, not a twist drill.

        The old rule kept the measurement and warned. It cannot survive the
        invariant this stage now carries — every nominal diameter comes from the
        table — because a retained 30.0 would be a nominal that came from
        nowhere, and the drill file would load a bit that does not exist.
        """
        got = SnapDiametersToDrillTable().apply(make_data(*holes((0.0, 0.0, 30.0))))

        assert codes(got) == ["unknown-diameter"]
        assert got.diagnostics[0].severity is Severity.ERROR

    def test_the_unmatched_measurement_never_becomes_a_tool(self):
        """The other half of the same rule, asserted on the tool table rather
        than on the diagnostic: a hole kept at its measured 30.0 would be a
        third tool in the drill file, whatever the report said about it."""
        got = SnapDiametersToDrillTable().apply(
            make_data(*holes((0.0, 0.0, 7.0), (10.0, 0.0, 30.0), (20.0, 0.0, 5.0)))
        )

        assert list(got.tools()) == [5.0, 7.0]
        assert [h.index for h in got.holes] == [0, 2]

    def test_the_diagnostic_names_the_hole_and_the_nearest_bit(self):
        """``data`` so a consumer need not re-measure: which hole, what it
        measured, and the closest thing the drawer actually holds."""
        got = SnapDiametersToDrillTable().apply(
            make_data(at(3.0, -2.0, 30.0, index=4))
        )
        found = got.diagnostics[0]

        assert found.get("hole_index") == 4
        assert found.get("diameter_mm") == pytest.approx(30.0)
        assert found.get("nearest_mm") == pytest.approx(25.0)
        assert found.get("standard") == "metric"
        assert found.location == (3.0, -2.0)

    def test_one_diagnostic_per_offending_hole(self):
        got = SnapDiametersToDrillTable().apply(
            make_data(*holes((0.0, 0.0, 30.0), (1.0, 0.0, 30.0), (2.0, 0.0, 7.0)))
        )
        assert codes(got) == ["unknown-diameter", "unknown-diameter"]

    def test_the_matching_tolerance_is_inclusive_at_its_boundary(self):
        """25.25 is exactly 0.25 from the 25 mm bit; 25.3 is 0.3 from it."""
        inside = SnapDiametersToDrillTable().apply(make_data(*holes((0.0, 0.0, 25.25))))
        outside = SnapDiametersToDrillTable().apply(make_data(*holes((0.0, 0.0, 25.3))))

        assert diameters(inside) == [25.0]
        assert codes(inside) == []
        assert codes(outside) == ["unknown-diameter"]

    def test_a_tighter_tolerance_refuses_what_a_looser_one_accepted(self):
        measured = make_data(*holes((0.0, 0.0, 25.25)))

        assert diameters(SnapDiametersToDrillTable(tolerance_mm=0.25).apply(measured)) == [25.0]
        assert codes(SnapDiametersToDrillTable(tolerance_mm=0.2).apply(measured)) == [
            "unknown-diameter"
        ]

    def test_a_tie_goes_to_the_smaller_bit_whatever_order_the_table_is_in(self):
        """14.25 sits exactly between the 14.0 and 14.5 mm sizes — exactly in
        binary too, which 6.35 between 6.3 and 6.4 is not: it is nearer 6.3 by
        one part in 10^15, so a fixture built on it would prove nothing about
        ties at all.

        The second half is the half that bites. Every shipped standard is
        ascending, so ``min`` returns the smaller of a tied pair *by accident*,
        and a test using one cannot tell the tie-break from that accident. A
        caller may hand this stage a table in any order, and the answer may not
        depend on which.
        """
        assert abs(14.25 - 14.0) == abs(14.5 - 14.25), "the fixture is not a tie"
        measured = make_data(*holes((0.0, 0.0, 14.25)))
        label = DRILL_STANDARDS["metric"].label

        assert diameters(SnapDiametersToDrillTable().apply(measured)) == [14.0]

        for order in ((14.0, 14.5), (14.5, 14.0)):
            drawer = DrillStandard(name="drawer", sizes_mm=order, label=label)
            got = SnapDiametersToDrillTable(drawer).apply(measured)
            assert diameters(got) == [14.0], f"the answer changed with the table order {order}"

    def test_it_quantises_against_the_narrowed_table_not_the_whole_standard(self):
        """The drawer, not the catalogue: with no 7 mm bit in it, a 6.9998 mm
        hole is drilled with whatever *is* there."""
        drawer = DRILL_STANDARDS["metric"].select(include=(3.2, 6.8, 12.0))
        got = SnapDiametersToDrillTable(drawer).apply(make_data(*holes((0.0, 0.0, 6.9998))))

        assert diameters(got) == [6.8]

    def test_it_quantises_the_value_it_was_handed_not_the_original_measurement(self):
        """No stage may reach behind its input (LSP).

        ``raw`` is provenance — what the artwork measured — and the value to
        quantise is whatever the previous stage left, whether or not there was
        one. Reading ``raw`` here would silently undo any upstream transform,
        and it reads identically on every fixture where nothing has moved yet,
        which is most of them.
        """
        handed_on = at(0.0, 0.0, 4.0, index=0).with_diameter(6.9998)

        got = SnapDiametersToDrillTable().apply(make_data(handed_on))

        assert diameters(got) == [7.0]
        assert got.holes[0].raw.diameter == 4.0, "the measurement was rewritten"

    def test_positions_and_raw_measurements_are_untouched(self):
        got = SnapDiametersToDrillTable().apply(make_data(*holes((-39.99, 18.01, 6.9998))))

        assert positions(got) == [(-39.99, 18.01)]
        assert got.holes[0].raw.diameter == pytest.approx(6.9998)
        assert got.holes[0].residual[2] == pytest.approx(0.0002, abs=1e-9)

    def test_distinct_sizes_stay_distinct(self):
        got = SnapDiametersToDrillTable().apply(
            make_data(*holes((0.0, 0.0, 5.02), (1.0, 0.0, 6.98), (2.0, 0.0, 4.99)))
        )
        assert diameters(got) == [5.0, 7.0, 5.0]
        assert len(got.tools()) == 2

    def test_every_nominal_it_produces_comes_from_the_table(self):
        """The invariant, stated as a property over the whole series.

        Every measurement inside the standard's range lands on a size the drawer
        holds — never on a rounded value, and never on its own measurement.
        """
        rng = random.Random(20250815)
        standard = DRILL_STANDARDS["metric"]
        measured = [round(rng.uniform(0.5, 25.0), 4) for _ in range(200)]
        got = SnapDiametersToDrillTable().apply(
            make_data(*holes(*[(float(i), 0.0, m) for i, m in enumerate(measured)]))
        )

        assert len(got.holes) == len(measured)
        assert set(diameters(got)) <= set(standard.sizes_mm)
        for hole in got.holes:
            # Spelled out rather than routed through ``tolerance.within``: a test
            # that borrows the implementation's own comparison cannot catch the
            # implementation getting that comparison wrong.
            assert abs(hole.diameter - hole.raw.diameter) <= 0.25 + 1e-9


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
        ``hole_index`` is therefore the key a consumer matches on: it names the
        survivor and stays true however far a later stage moves it. ``location``
        is the survivor's coordinate at the time of the report — human context
        for the CLI and the drawing's NOTES, and no longer a referent.
        """
        # Identities deliberately do not match positions: an implementation that
        # reported where the survivor sits rather than who it is would answer 0.
        survivor = at(-40.0031, 18.0007, 7.0, index=4)
        data = make_data(
            survivor,
            at(-40.0129, 18.0203, 7.0, index=5),
            at(-39.9902, 17.9885, 7.0, index=6),
            at(0.0, 0.0, 5.0, index=9),  # a lonely hole raises nothing
        )

        out = Deduplicate(0.05).apply(data)

        assert codes(out) == ["duplicate-hole"]
        diag = out.diagnostics[0]
        assert diag.get("hole_index") == survivor.index
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

    The two identities are out of order and neither equals a position, so the
    rejected design — reporting the survivor's index in the surviving tuple —
    would answer 0 here rather than 7, and SortHoles would invalidate it later.
    """
    data = make_data(
        Hole.from_measurement(10.03, 5.02, 7.0, index=7),
        Hole.from_measurement(10.04, 5.02, 7.0, index=3),
    )
    after = Pipeline([Deduplicate(tolerance=0.05), SnapPositions(grid=0.25)]).run(data)

    duplicates = [d for d in after.diagnostics if d.code == "duplicate-hole"]
    assert len(duplicates) == 1
    survivor_index = duplicates[0].get("hole_index")
    assert survivor_index == 7
    assert [h.index for h in after.holes] == [survivor_index]

    # The move the docstring turns on, made observable: by the end of the run
    # the reported coordinate names nowhere a hole is, and only the id resolves.
    survivor = after.holes[0]
    assert (survivor.x, survivor.y) == (10.0, 5.0)
    assert duplicates[0].location == (10.03, 5.02)
    assert duplicates[0].location != (survivor.x, survivor.y)


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
        holes = [
            at(0.0, 0.0, 7.0, index=0),
            at(1.0, 0.0, 5.0, index=1),
            at(2.0, 0.0, 3.2, index=2),
        ]
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

            def describe(self) -> StageRun:
                return StageRun(self.name, (("tag", self.tag),))

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

    def test_a_realistic_composition_yields_one_tool_for_a_noisy_seven_mm_row(self):
        """Several stages folded together, on the shape of panel they meet.

        Deliberately *not* a second statement of the CLI's stage order — that
        lives in ``cli.build_pipeline`` and is pinned once, in
        ``tests/test_cli.py``, by reading the pipeline the CLI actually builds.
        A parallel list here has already drifted once.
        """
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
                SnapDiametersToDrillTable(),
                Deduplicate(0.05),
                IdentifyHammondFootprint(),
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


# --------------------------------------------------------------------------
# Provenance: what the data records about the stages that shaped it
# --------------------------------------------------------------------------


class TestStageRunAndProcessing:
    """The record itself, before any stage fills one in."""

    def test_get_reads_a_parameter_and_falls_back_to_the_default(self):
        run = StageRun("snap", (("grid_mm", 0.5), ("enabled", True)))
        assert run.get("grid_mm") == 0.5
        assert run.get("enabled") is True
        assert run.get("warn_over_mm") is None
        assert run.get("warn_over_mm", 0.0) == 0.0

    def test_is_an_immutable_value(self):
        run = StageRun("snap", (("grid_mm", 0.5),))
        assert run == StageRun("snap", (("grid_mm", 0.5),))
        with pytest.raises(dataclasses.FrozenInstanceError):
            run.name = "sort"  # type: ignore[misc]
        # slots, not just frozen: no per-instance dict to grow a stray attribute.
        assert not hasattr(run, "__dict__")

    def test_a_mutable_payload_is_coerced_on_the_way_in(self):
        """Task 3 deserialises into this: JSON hands back lists, not tuples.

        A ``StageRun`` holding a list is unhashable and compares unequal to the
        identical record built from tuples, so a round-tripped document would
        differ from the one it was written from — while looking right in print.
        """
        run = StageRun("normalize-diameters", [["sizes_mm", [3.2, 7.0]]])

        assert run == StageRun("normalize-diameters", (("sizes_mm", (3.2, 7.0)),))
        assert run.get("sizes_mm") == (3.2, 7.0)
        assert hash(run) == hash(StageRun("normalize-diameters", (("sizes_mm", (3.2, 7.0)),)))

    def test_data_starts_with_no_processing_history(self):
        assert make_data(at(0.0, 0.0, index=0)).processing == ()

    def test_with_processing_appends_without_mutating(self):
        data = make_data(at(0.0, 0.0, index=0))
        first = data.with_processing(StageRun("snap", ()))
        second = first.with_processing(StageRun("sort", ()))

        assert data.processing == (), "with_processing mutated its receiver"
        assert [r.name for r in first.processing] == ["snap"]
        assert [r.name for r in second.processing] == ["snap", "sort"]

    def test_the_other_transforms_carry_the_history_forward(self):
        """Every transform returns a new value; none of them may drop provenance.

        A stage that rebuilt its holes and lost the record of the stages before
        it would leave the drawing with a history that starts halfway through.
        """
        run = StageRun("snap", (("grid_mm", 0.5),))
        data = make_data(at(0.0, 0.0, index=0)).with_processing(run)

        assert data.with_holes(data.holes).processing == (run,)
        assert data.with_diagnostics(Diagnostic.info("x", "x")).processing == (run,)

    def test_with_processing_of_nothing_is_the_identity(self):
        data = make_data(at(0.0, 0.0, index=0))
        assert data.with_processing() is data

    def test_last_run_answers_the_most_recent_of_a_repeated_stage(self):
        """A stage may legitimately run twice; the title block wants the last one."""
        data = make_data().with_processing(
            StageRun("snap", (("grid_mm", 1.0),)),
            StageRun("sort", ()),
            StageRun("snap", (("grid_mm", 0.25),)),
        )
        assert data.last_run("snap").get("grid_mm") == 0.25
        assert data.last_run("deduplicate") is None


class TestDescribe:
    """Every stage reports what it was configured to do, in effective values."""

    @pytest.mark.parametrize("stage", ALL_STAGES, ids=lambda s: type(s).__name__)
    def test_a_stage_describes_itself_under_its_own_name(self, stage):
        assert stage.describe().name == type(stage).name

    def test_snap_reports_grid_and_the_resolved_warning_threshold(self):
        run = SnapPositions(grid=0.5).describe()
        assert run.get("grid_mm") == 0.5
        assert run.get("warn_over_mm") == 0.125
        assert run.get("enabled") is True

    def test_describe_reports_resolved_defaults_not_raw_arguments(self):
        """warn_over defaults to grid/4; provenance must record the effective value."""
        assert SnapPositions(grid=0.25).describe().get("warn_over_mm") == 0.0625

    def test_snap_reports_an_explicit_warning_threshold_as_given(self):
        assert SnapPositions(0.25, warn_over=0.2).describe().get("warn_over_mm") == 0.2

    def test_a_non_positive_grid_describes_itself_as_disabled(self):
        run = SnapPositions(grid=0.0).describe()
        assert run.get("enabled") is False
        assert run.get("grid_mm") == 0.0

    def test_deduplicate_reports_its_resolved_tolerance(self):
        assert Deduplicate().describe().get("tolerance_mm") == 0.05
        assert Deduplicate(0.02).describe().get("tolerance_mm") == 0.02

    def test_check_reference_size_reports_the_declared_panel_and_slack(self):
        run = CheckReferenceSize((113.0, 60.0)).describe()
        assert run.get("expected_width_mm") == 113.0
        assert run.get("expected_height_mm") == 60.0
        assert run.get("tolerance_mm") == 0.05

    def test_sort_names_its_key_function(self):
        def by_diameter(hole):
            return hole.diameter

        assert SortHoles().describe().get("key") == "default"
        assert SortHoles(key=by_diameter).describe().get("key") == "by_diameter"

    def test_snap_diameters_reports_the_standard_it_quantised_against(self):
        run = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"], 0.1).describe()
        assert run.get("standard") == "fractional"
        assert run.get("tolerance_mm") == 0.1
        assert run.get("size_count") == 64

    def test_snap_diameters_records_the_sizes_that_were_actually_available(self):
        """The narrowed drawer, written out in full, because nothing else says it.

        A consumer's one likely question — "what is the nearest size this panel
        could have used?" — is answered wrongly by the standard's name once the
        operator has told us which bits they own. The set is run-specific, so it
        travels with the run; it is also small, which is why it can.
        """
        drawer = DRILL_STANDARDS["metric"].select(include=(3.2, 5.0, 7.0, 12.0))
        run = SnapDiametersToDrillTable(drawer).describe()

        assert run.get("standard") == "metric"
        assert run.get("sizes_mm") == (3.2, 5.0, 7.0, 12.0)
        assert run.get("size_count") == 4

    def test_an_unnarrowed_standard_is_recorded_by_name_and_count_alone(self):
        """183 sizes a reader can look up are not worth 90 % of the document.

        The name is an address into a registry of physical constants, and a
        consumer that cannot expand it cannot use the numbers either. The key is
        *absent* rather than empty: ``StageRun.get`` cannot tell an absent key
        from a null one, so an empty tuple here would read as "quantised against
        no bits at all".
        """
        run = SnapDiametersToDrillTable().describe()
        parameters = dict(run.parameters)

        assert run.get("standard") == "metric"
        assert run.get("size_count") == 183
        assert run.get("tolerance_mm") == 0.25
        assert "sizes_mm" not in parameters

    def test_a_table_no_registry_name_can_rebuild_records_its_sizes(self):
        """The rule is "can a reader rebuild this from the name?", not "did
        ``select`` run?" — a hand-built standard answers no just as a narrowed
        one does, and a reader looking up its name would find nothing at all."""
        label = DRILL_STANDARDS["metric"].label
        run = SnapDiametersToDrillTable(
            DrillStandard(name="the-drawer-in-the-shed", sizes_mm=(3.2, 7.0), label=label)
        ).describe()

        assert run.get("sizes_mm") == (3.2, 7.0)
        assert run.get("size_count") == 2


class TestPipelineRecordsProvenance:
    def test_pipeline_records_what_each_stage_actually_did(self):
        data = make_data(*holes((10.03, 5.02), (-20.0, 5.0, 5.0)))
        after = Pipeline([SnapPositions(grid=0.5), Deduplicate(tolerance=0.05)]).run(data)

        assert [r.name for r in after.processing] == ["snap", "deduplicate"]
        snap = after.last_run("snap")
        assert snap.get("grid_mm") == 0.5
        assert snap.get("warn_over_mm") == 0.125  # the *resolved* default, not None

    @pytest.mark.parametrize(
        "grid, expected", [(0.25, [(10.25, 5.0)]), (0.5, [(10.5, 5.0)])]
    )
    def test_the_recorded_grid_is_the_grid_the_holes_were_snapped_to(self, grid, expected):
        """Finding 08: the sheet stated a grid the data had never been snapped to.

        The record must *predict* the coordinates, which is only true if it comes
        from the stage that moved them. Divisibility alone does not say that —
        every multiple of 0.5 is also a multiple of 0.25, so a record finer than
        the reality, which is finding 08 exactly, would satisfy it. Hence the
        literal positions per grid, plus the residual bound: a snap to a pitch
        can never move a hole further than half of it, so a doubled pitch under a
        record that still says 0.25 is caught here too.
        """
        after = Pipeline([SnapPositions(grid=grid)]).run(make_data(*holes((10.3, 5.02))))

        recorded = after.last_run("snap").get("grid_mm")
        assert recorded == grid
        assert positions(after) == expected
        for hole in after.holes:
            assert abs(hole.x - hole.raw.x) <= recorded / 2 + 1e-9
            assert abs(hole.y - hole.raw.y) <= recorded / 2 + 1e-9

    def test_a_disabled_stage_still_records_that_it_ran_and_did_nothing(self):
        after = Pipeline([SnapPositions(grid=0.0)]).run(make_data(*holes((10.03, 5.02))))

        assert [r.name for r in after.processing] == ["snap"]
        assert after.last_run("snap").get("enabled") is False
        assert positions(after) == [(10.03, 5.02)], "a disabled snap moved a hole"

    def test_a_stage_never_sees_its_own_provenance_in_its_input(self):
        """The record says what a stage *did*, so it cannot exist before it acts.

        Recording before applying would also hand every stage a record of itself
        it had not yet earned — and if ``apply`` then raised, the history would
        claim work that never happened.
        """
        class Nosy:
            name = "nosy"

            def apply(self, data: DrillData) -> DrillData:
                return data.with_diagnostics(
                    Diagnostic.info(
                        "seen", "counted the history", data=(("runs", len(data.processing)),)
                    )
                )

            def describe(self) -> StageRun:
                return StageRun(self.name, ())

        out = Pipeline([Nosy(), Nosy(), Nosy()]).run(make_data())

        assert [d.get("runs") for d in out.diagnostics] == [0, 1, 2]
        assert len(out.processing) == 3

    def test_a_stage_that_raises_records_nothing(self):
        class Explodes:
            name = "explodes"

            def apply(self, data: DrillData) -> DrillData:
                raise RuntimeError("boom")

            def describe(self) -> StageRun:
                return StageRun(self.name, ())

        data = make_data(at(0.0, 0.0, index=0))
        with pytest.raises(RuntimeError):
            Pipeline([SnapPositions(0.25), Explodes()]).run(data)
        assert data.processing == ()

    def test_a_pipeline_records_its_stages_in_order(self):
        """Read off the stages that were handed in, not from a copy of the list.

        The literal spelling drifted once already — it named the CLI's order,
        which this list has not been since the enclosure stage joined it — and a
        parallel list is what let that happen quietly. What is being asserted is
        that ``Pipeline`` records *in order*, which the input already states.
        """
        stages = ALL_STAGES
        after = Pipeline(stages).run(
            make_data(
                *holes((-40.003, 18.001, 6.9998), (19.0, -18.75, 5.0002)),
                reference=ReferenceOutline(113.0, 60.0),
            )
        )
        assert [r.name for r in after.processing] == [type(s).name for s in stages]
        assert len(after.processing) == len(stages), "a stage recorded nothing"


# --------------------------------------------------------------------------
# IdentifyHammondFootprint
# --------------------------------------------------------------------------


def an_outline(width: float, height: float) -> DrillData:
    """A panel whose reference outline is the measurement, and nothing else."""
    return make_data(reference=ReferenceOutline.from_measurement(width, height))


class TestIdentifyHammondFootprint:
    def test_the_fixture_outline_snaps_to_the_1590B_footprint(self):
        """tar.ai measures 113.0 × 60.0; the catalogue says 112 × 61. Snap, silently."""
        out = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0))

        assert (out.reference.width, out.reference.height) == (112.0, 61.0)
        assert (out.reference.raw.width, out.reference.raw.height) == (113.0, 60.0)
        assert out.enclosure.candidates == ("1590B", "1590B2", "1590BS")
        assert out.enclosure.family == "Hammond 1590"
        assert (out.enclosure.length_mm, out.enclosure.width_mm) == (112, 61)
        assert out.diagnostics == ()  # silence is the decision

    def test_the_catalogue_dimensions_are_whole_millimetres_not_floats(self):
        """The datasheet's metric column is integral; the outline's is not.

        Recorded as ``int`` so a consumer printing the enclosure gets "112 × 61"
        rather than "112.0 × 61.0" and cannot mistake a catalogue constant for a
        measurement that happened to land on a whole number.
        """
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure

        assert isinstance(match.length_mm, int) and isinstance(match.width_mm, int)
        assert isinstance(match.rotated, bool)

    def test_no_reference_outline_is_left_alone(self):
        """LSP: the source may simply not have had a reference layer."""
        data = make_data(at(0.0, 0.0, index=0))

        out = IdentifyHammondFootprint().apply(data)

        assert out == data
        assert out.enclosure is None
        assert out.diagnostics == ()

    def test_an_outline_matching_nothing_is_reported_without_being_refused(self):
        """A warning, not an error, and never a guess.

        This is the one finding in this stage that is about *our catalogue*
        rather than about the operator's panel: we hold 22 Hammond footprints
        and the world holds rather more. It still may not be silent — an
        unmatched outline is not snapped, so every downstream number keeps the
        artwork's fractional millimetres — but refusing the run would be this
        tool claiming an authority it does not have.
        """
        out = IdentifyHammondFootprint().apply(an_outline(500.0, 500.0))

        assert codes(out) == ["unknown-enclosure"]
        assert out.diagnostics[0].severity is Severity.WARNING
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == (500.0, 500.0)

    def test_drawing_an_unrecognised_outline_is_not_punished_harder_than_omitting_one(self):
        """The asymmetry that decided the severity, asserted as one comparison.

        A panel with no reference layer returns untouched and clean, because no
        stage may assume a predecessor ran. If an unrecognised outline were an
        ERROR, then *drawing* your panel outline would fail the run while
        leaving it out would pass — and the two would be judged by two different
        standards for the same missing knowledge. Whatever severity these two
        carry, the drawn one may not be the worse of them.
        """
        omitted = IdentifyHammondFootprint().apply(make_data(at(0.0, 0.0, index=0)))
        drawn = IdentifyHammondFootprint().apply(an_outline(500.0, 500.0))

        assert omitted.worst_severity is None
        assert drawn.worst_severity is not Severity.ERROR

    def test_the_unknown_diagnostic_carries_what_was_measured_and_what_was_searched(self):
        """``Diagnostic.data`` is a consumer contract, not a debug aid: it is
        there so a report can say what failed without re-deriving the predicate.
        Unasserted, it is an unpinned contract."""
        # 113.6 rather than 500: the size must come from the outline as it
        # stands, and a payload sourced from ``raw`` instead would be
        # indistinguishable on an outline nothing has snapped.
        diagnostic = IdentifyHammondFootprint(tolerance_mm=0.4).apply(
            make_data(reference=ReferenceOutline(113.6, 60.0, raw=RawOutline(1.0, 2.0)))
        ).diagnostics[0]

        assert diagnostic.get("width_mm") == 113.6
        assert diagnostic.get("height_mm") == 60.0
        assert diagnostic.get("tolerance_mm") == 0.4
        assert diagnostic.get("catalogue") == "Hammond 1590"

    def test_a_near_miss_is_unknown_rather_than_the_footprint_it_nearly_is(self):
        """113.6 × 60.0 is 1.6 mm off 1590B on one axis. Outside is outside.

        The far-away 500 × 500 fixture cannot tell a tolerance check from a
        catalogue lookup that only ever succeeds on an exact hit, and it would
        stay green under a tolerance widened to 2 mm. This one dies to both.
        """
        out = IdentifyHammondFootprint().apply(an_outline(113.6, 60.0))

        assert codes(out) == ["unknown-enclosure"]
        assert out.enclosure is None
        assert out.reference.width == 113.6, "an unmatched outline was snapped anyway"

    def test_the_tolerance_boundary_is_inclusive(self):
        """1.5 mm exactly is a match; the machinist typed the number they meant."""
        assert IdentifyHammondFootprint().apply(an_outline(113.5, 61.0)).enclosure is not None
        assert IdentifyHammondFootprint().apply(an_outline(113.51, 61.0)).enclosure is None

    def test_a_tighter_tolerance_rejects_what_the_default_accepts(self):
        """The fixture's own 1.0 mm error, against a tolerance that will not have it."""
        tight = IdentifyHammondFootprint(tolerance_mm=0.5)
        assert tight.apply(an_outline(113.0, 60.0)).enclosure is None
        assert IdentifyHammondFootprint(tolerance_mm=1.5).apply(an_outline(113.0, 60.0)).enclosure

    def test_both_axes_must_be_within_the_tolerance(self):
        """One axis on the nose does not carry the other one home.

        The assertion is on the *code*, not on ``enclosure is None``, and that
        distinction is the whole test. ``enclosure is None`` is reachable by two
        paths — nothing matched, and too much matched — so it asserts the union
        rather than the case the name claims. Drop the height clause from
        ``_fits`` and 112.0 × 65.0 matches three footprints on width alone,
        (111, 82), (112, 61) and (192, 112) turned 90°, giving
        ``ambiguous-enclosure`` with ``enclosure`` still ``None``: the half of
        this test that names the height axis would have stayed green.
        """
        # Width exact, height 4 mm out.
        assert codes(IdentifyHammondFootprint().apply(an_outline(112.0, 65.0))) == [
            "unknown-enclosure"
        ]
        # Height exact, width 4 mm out.
        assert codes(IdentifyHammondFootprint().apply(an_outline(108.0, 61.0))) == [
            "unknown-enclosure"
        ]


class TestRotation:
    def test_a_portrait_panel_matches_its_landscape_catalogue_entry(self):
        out = IdentifyHammondFootprint().apply(an_outline(60.0, 113.0))

        assert out.enclosure.rotated is True
        assert (out.reference.width, out.reference.height) == (61.0, 112.0)

    def test_a_rotated_match_records_the_catalogue_orientation_not_the_artworks(self):
        """The datasheet says 1590B is 112 × 61. Transposing it here would make
        the identified part unfindable in the document it was identified from."""
        match = IdentifyHammondFootprint().apply(an_outline(60.0, 113.0)).enclosure

        assert (match.length_mm, match.width_mm) == (112, 61)
        assert match.candidates == ("1590B", "1590B2", "1590BS")

    def test_a_landscape_panel_is_recorded_as_not_rotated(self):
        """Paired with the portrait case so neither hardcoded flag survives."""
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure
        assert match.rotated is False

    def test_a_square_footprint_is_not_a_rotation(self):
        """1590Y is 92 × 92, so both readings fit. A turn of no consequence is
        not a turn, and reporting one would put "rotated" on a drawing for a
        panel nobody rotated."""
        match = IdentifyHammondFootprint().apply(an_outline(92.4, 91.8)).enclosure

        assert match.candidates == ("1590Y",)
        assert match.rotated is False

    def test_a_rotated_match_is_silent_too(self):
        assert IdentifyHammondFootprint().apply(an_outline(60.0, 113.0)).diagnostics == ()


class TestAmbiguity:
    # 1590B3 (116 × 77) and 1590T (120 × 80) are the closest pair in the whole
    # catalogue, 4 mm apart on the wider axis. An outline halfway between them
    # is within 2 mm of both — the only shape of fixture that can reach rule 5.
    TIED = (118.0, 78.5)

    def test_an_ambiguous_tie_is_an_error_not_a_choice(self):
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.TIED

    def test_the_tie_diagnostic_names_every_footprint_it_could_not_choose_between(self):
        """Naming one of them would be the guess this rule exists to refuse."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("footprints") == "116 × 77, 120 × 80"
        assert diagnostic.get("candidates") == "1590B3, 1590T"
        # The tolerance is the actionable half of this finding: it is the one
        # thing the operator can change to break the tie.
        assert diagnostic.get("tolerance_mm") == 2.0

    def test_the_same_outline_is_unambiguous_at_the_default_tolerance(self):
        """The tie is a property of the tolerance, not of the outline."""
        assert codes(IdentifyHammondFootprint().apply(an_outline(*self.TIED))) == [
            "unknown-enclosure"
        ]

    def test_the_default_tolerance_admits_no_tie_anywhere_in_the_catalogue(self):
        """Nothing had checked this, so check it against the real catalogue.

        Two footprints can both match one outline exactly when their per-axis
        separation — minimised over the rotated reading as well, since a stage
        that compares both is comparing against both orientations of every
        entry — is at most twice the tolerance. So the largest safe tolerance is
        half the closest approach in the catalogue, exclusive. That approach is
        4 mm (1590B3 116 × 77 against 1590T 120 × 80), which puts the ceiling
        just under 2 mm and leaves the default 1.5 mm clear.
        """
        outlines = sorted(footprints())
        separations = [
            min(
                max(abs(a[0] - b[0]), abs(a[1] - b[1])),
                max(abs(a[0] - b[1]), abs(a[1] - b[0])),
            )
            for i, a in enumerate(outlines)
            for b in outlines[i + 1 :]
        ]

        assert len(outlines) == 22
        assert min(separations) == 4
        assert 2 * IdentifyHammondFootprint().tolerance_mm < min(separations)

    def test_two_millimetres_is_where_ambiguity_becomes_reachable(self):
        """The bound above is tight, not merely sufficient: at exactly half the
        closest approach the tie is real, which is why the default is not 2."""
        assert codes(IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))) == [
            "ambiguous-enclosure"
        ]
        just_under = IdentifyHammondFootprint(tolerance_mm=1.99).apply(an_outline(*self.TIED))
        assert just_under.enclosure is None
        assert codes(just_under) == ["unknown-enclosure"]

    def test_the_tie_is_reported_in_size_order_whatever_order_the_catalogue_is_in(
        self, monkeypatch
    ):
        """The message must not reshuffle when an unrelated part is added.

        Needs a stand-in catalogue: the real one is *generated* ordered by
        footprint, so its insertion order already equals its sorted order and
        nothing built on it can tell the two apart. Two entries, deliberately
        the wrong way round.
        """
        monkeypatch.setattr(
            enclosure_stage,
            "footprints",
            lambda: {(120, 80): ("FAKE-T",), (116, 77): ("FAKE-B3",)},
        )
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert out.diagnostics[0].get("footprints") == "116 × 77, 120 × 80"
        assert out.diagnostics[0].get("candidates") == "FAKE-B3, FAKE-T"


class TestDeclaredCase:
    def test_declaring_the_wrong_case_is_an_error(self):
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))

        assert codes(out) == ["wrong-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR

    def test_the_wrong_case_diagnostic_names_both_parts(self):
        """The operator needs to know what they asked for *and* what they drew;
        either alone leaves them re-deriving the other from the artwork."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590BB"
        assert diagnostic.get("identified_parts") == "1590B, 1590B2, 1590BS"
        # And the footprint that identified them, so a consumer can show the
        # measurement that produced the disagreement rather than re-taking it.
        assert (diagnostic.get("length_mm"), diagnostic.get("width_mm")) == (112, 61)

    def test_a_wrongly_declared_panel_is_still_identified_and_still_snapped(self):
        """The outline matched; only the declaration disagrees. Dropping the
        match would leave the report with nothing to name."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(an_outline(113.0, 60.0))

        assert out.enclosure.candidates == ("1590B", "1590B2", "1590BS")
        assert out.enclosure.selected_part == "1590BB"
        assert (out.reference.width, out.reference.height) == (112.0, 61.0)

    def test_a_correctly_declared_case_becomes_the_selected_part(self):
        """A footprint names candidates; only the operator can pick among them."""
        out = IdentifyHammondFootprint(expected_part="1590B2").apply(an_outline(113.0, 60.0))

        assert out.enclosure.selected_part == "1590B2"
        assert out.diagnostics == ()

    def test_nothing_is_selected_when_nothing_was_declared(self):
        """The artwork does not contain the height, so it cannot be inferred."""
        match = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0)).enclosure
        assert match.selected_part is None

    def test_a_declared_case_is_matched_however_it_was_typed(self):
        out = IdentifyHammondFootprint(expected_part=" 1590b2 ").apply(an_outline(113.0, 60.0))

        assert out.diagnostics == ()
        assert out.enclosure.selected_part == "1590B2"

    def test_a_blank_declaration_is_no_declaration(self):
        """An empty ``--case`` must not become a part number nothing can match."""
        out = IdentifyHammondFootprint(expected_part="   ").apply(an_outline(113.0, 60.0))

        assert out.diagnostics == ()
        assert out.enclosure.selected_part is None


class TestADeclarationIsCheckedOnEveryOutcome:
    """The declaration has to bite where the geometry *failed*, not only where
    it succeeded.

    Regression for the review's central finding: ``expected_part`` used to be
    compared only after a unique catalogue match, so the three early returns —
    no reference outline, no footprint, a tie — each walked past it. The panel
    that reached the operator was the worst case of all: a declared case, an
    outline nothing recognised, ``unknown-enclosure`` at WARNING, and a drill
    file on disk. ``--true-size`` was deleted on the understanding that
    ``--case`` carried this assertion; these tests are that understanding.

    Every case below is paired with its undeclared twin, because the asymmetry
    *is* the policy: declare nothing and an unidentifiable panel still runs;
    declare something and it must be checked.
    """

    # 1590B3 (116 × 77) and 1590T (120 × 80) are the catalogue's closest pair,
    # and this outline sits within 2 mm of both — the only shape of fixture that
    # can reach a tie at all.
    TIED = (118.0, 78.5)
    #: Larger than every footprint in the catalogue, on both axes.
    UNRECOGNISED = (300.0, 300.0)

    def test_a_declaration_with_no_outline_to_check_it_against_is_refused(self):
        """Silence here would be indistinguishable from a confirmed declaration."""
        data = make_data(at(3.0, -4.0, index=7))

        out = IdentifyHammondFootprint(expected_part="1590B").apply(data)

        assert codes(out) == ["unverifiable-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.holes == data.holes
        assert out.enclosure is None

    def test_no_outline_and_no_declaration_is_still_left_alone(self):
        """The undeclared twin: nothing was claimed, so nothing is checked."""
        data = make_data(at(3.0, -4.0, index=7))

        assert IdentifyHammondFootprint().apply(data) == data

    def test_the_unverifiable_diagnostic_names_the_part_and_the_size_it_would_be(self):
        """A consumer must be able to say what the panel *should* measure
        without going back to the catalogue the stage has already read."""
        out = IdentifyHammondFootprint(expected_part=" 1590b ").apply(
            make_data(at(3.0, -4.0, index=7))
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590B"
        assert (diagnostic.get("expected_length_mm"), diagnostic.get("expected_width_mm")) == (
            112,
            61,
        )
        assert diagnostic.get("catalogue") == "Hammond 1590"

    def test_a_declaration_the_artwork_matches_nothing_for_is_refused(self):
        """The reproduction from the review, exactly: a declared 1590B against
        an outline no footprint fits used to exit 1 and write the drill file."""
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(
            an_outline(*self.UNRECOGNISED)
        )

        assert codes(out) == ["unmatched-enclosure"]
        assert out.diagnostics[0].severity is Severity.ERROR
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.UNRECOGNISED

    def test_an_unrecognised_outline_nobody_declared_stays_a_warning(self):
        """The undeclared twin, and the reason the new code is not
        ``unknown-enclosure`` at a second severity."""
        out = IdentifyHammondFootprint().apply(an_outline(*self.UNRECOGNISED))

        assert codes(out) == ["unknown-enclosure"]
        assert out.diagnostics[0].severity is Severity.WARNING

    def test_the_unmatched_diagnostic_carries_the_declaration_and_the_measurement(self):
        """Both halves of the disagreement, so the consumer re-measures nothing.

        ``footprints``/``candidates`` are empty because nothing fitted; the keys
        are still there, so one payload shape serves both ways of failing to
        confirm a declaration.
        """
        out = IdentifyHammondFootprint(expected_part="1590BB").apply(
            an_outline(*self.UNRECOGNISED)
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.get("requested_part") == "1590BB"
        assert (diagnostic.get("expected_length_mm"), diagnostic.get("expected_width_mm")) == (
            120,
            94,
        )
        assert (diagnostic.get("width_mm"), diagnostic.get("height_mm")) == self.UNRECOGNISED
        assert diagnostic.get("tolerance_mm") == 1.5
        assert diagnostic.get("catalogue") == "Hammond 1590"
        assert diagnostic.get("footprints") == ""
        assert diagnostic.get("candidates") == ""

    def test_a_declaration_breaks_a_tie_the_catalogue_cannot(self):
        """Two footprints fit; the operator already said which one it is.

        1590T's 120 × 80 rather than the nearer 1590B3, so the resolved match
        cannot be confused with "the first candidate" or "the closest one" —
        116 × 77 is both.
        """
        out = IdentifyHammondFootprint(tolerance_mm=2.0, expected_part="1590T").apply(
            an_outline(*self.TIED)
        )

        assert out.diagnostics == ()
        assert (out.enclosure.length_mm, out.enclosure.width_mm) == (120, 80)
        assert out.enclosure.selected_part == "1590T"
        assert (out.reference.width, out.reference.height) == (120.0, 80.0)
        assert (out.reference.raw.width, out.reference.raw.height) == self.TIED

    def test_a_tie_the_declaration_does_not_resolve_is_refused(self):
        """Declared 1590B; the outline is within tolerance of two footprints and
        neither of them is 1590B. Naming either would be the guess."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0, expected_part="1590B").apply(
            an_outline(*self.TIED)
        )
        diagnostic = out.diagnostics[0]

        assert codes(out) == ["unmatched-enclosure"]
        assert diagnostic.severity is Severity.ERROR
        assert diagnostic.get("requested_part") == "1590B"
        assert diagnostic.get("footprints") == "116 × 77, 120 × 80"
        assert diagnostic.get("candidates") == "1590B3, 1590T"
        assert out.enclosure is None
        assert (out.reference.width, out.reference.height) == self.TIED

    def test_an_undeclared_tie_is_still_ambiguous_and_still_asks_for_a_case(self):
        """The undeclared twin. ``ambiguous-enclosure`` keeps its one meaning —
        more than one footprint fits and nothing was said to choose between
        them — which is why the advice in its message is still sound."""
        out = IdentifyHammondFootprint(tolerance_mm=2.0).apply(an_outline(*self.TIED))

        assert codes(out) == ["ambiguous-enclosure"]
        assert "declare the case" in out.diagnostics[0].message

    def test_a_declared_part_no_catalogue_holds_invents_no_footprint_for_it(self):
        """The CLI refuses this as a usage error before the file is opened, but
        a library caller can hand the stage anything, and a payload key filled
        in with a plausible number would be worse than an absent one."""
        out = IdentifyHammondFootprint(expected_part="1590ZZ").apply(
            an_outline(*self.UNRECOGNISED)
        )
        diagnostic = out.diagnostics[0]

        assert diagnostic.code == "unmatched-enclosure"
        assert diagnostic.get("requested_part") == "1590ZZ"
        assert diagnostic.get("expected_length_mm") is None
        assert diagnostic.get("expected_width_mm") is None


class TestNormalizePartName:
    """The public resolver. Its contract is owned here, not inherited from the
    extraction script's private ``_base_designator``."""

    @pytest.mark.parametrize(
        "typed, expected",
        [
            ("1590b", "1590B"),
            (" 1590BB\n", "1590BB"),
            ("1590BB", "1590BB"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_case_and_surrounding_space_are_the_only_things_normalised(self, typed, expected):
        assert normalize_part_name(typed) == expected

    def test_a_finish_or_flange_suffix_is_left_alone(self):
        """Deliberate. Collapsing 1590BBBK to 1590BB would need the datasheet's
        suffix grammar, whose 1590W and flange cases are subtle enough to have
        been wrong once already. An order code typed in full gets a
        ``wrong-enclosure`` naming both parts, which is a legible mistake; a
        silent collapse to the wrong base part is not.
        """
        assert normalize_part_name("1590BBBK") == "1590BBBK"
        assert normalize_part_name("1590WF") == "1590WF"


class TestIdentifyHammondFootprintDescribe:
    def test_it_reports_the_tolerance_and_the_catalogue_it_searched(self):
        run = IdentifyHammondFootprint(tolerance_mm=0.75).describe()

        assert run.name == "identify-enclosure"
        assert run.get("tolerance_mm") == 0.75
        assert run.get("catalogue") == "Hammond 1590"

    def test_it_reports_the_declared_part_as_the_stage_resolved_it(self):
        """Effective values, not raw arguments: the comparison is made against
        the normalised form, so that is what provenance must show."""
        run = IdentifyHammondFootprint(expected_part=" 1590bb ").describe()
        assert run.get("expected_part") == "1590BB"

    def test_an_undeclared_part_is_absent_rather_than_present_and_empty(self):
        """``get`` cannot tell an absent key from a null one, and ``None`` is not
        a legal ``ParameterValue``."""
        parameters = dict(IdentifyHammondFootprint().describe().parameters)
        blank = dict(IdentifyHammondFootprint(expected_part="   ").describe().parameters)

        assert "expected_part" not in parameters
        assert "expected_part" not in blank


class TestTheMeasurementSurvivesTheSnap:
    def test_the_emitted_document_still_quotes_what_the_artwork_said(self):
        """End-to-end, and it has to be: ``ReferenceOutline(112.0, 61.0)`` is
        legitimate code whose ``raw`` defaults to its own dimensions, so a snap
        that builds a fresh outline instead of calling ``resized`` silently
        rewrites the measurement to the snapped size. Nothing at the unit level
        can see the difference — both spellings produce a 112 × 61 outline — so
        the claim is made where the loss becomes visible: in the serialised
        document a library consumer actually reads.
        """
        data = make_data(
            at(-40.0, 18.0, 7.0, index=0),
            reference=ReferenceOutline.from_measurement(
                113.0, 60.0, centre_x=306.0, centre_y=170.0
            ),
        )

        after = Pipeline([IdentifyHammondFootprint()]).run(data)
        document = json.loads(JsonEmitter().emit(after))

        assert document["reference"]["width"] == 112.0
        assert document["reference"]["height"] == 61.0
        assert document["reference"]["raw"] == {"width": 113.0, "height": 60.0}

    def test_the_snap_keeps_the_outlines_source_space_centre(self):
        """``centre_x``/``centre_y`` say where the outline sat on the page. A
        fresh construction would drop them back to the origin."""
        data = make_data(
            reference=ReferenceOutline.from_measurement(113.0, 60.0, 306.0, 170.0)
        )
        out = IdentifyHammondFootprint().apply(data)

        assert out.reference.width == 112.0, "the outline was never snapped at all"
        assert (out.reference.centre_x, out.reference.centre_y) == (306.0, 170.0)

    def test_a_second_snap_does_not_rewrite_the_measurement(self):
        """Idempotence, and provenance under it: 112 × 61 is already a footprint,
        so running twice must change nothing and must not promote the snapped
        size to a measurement."""
        once = IdentifyHammondFootprint().apply(an_outline(113.0, 60.0))
        twice = IdentifyHammondFootprint().apply(once)

        assert once.reference.width == 112.0, "the first pass never snapped anything"
        assert twice.reference == once.reference
        assert (twice.reference.raw.width, twice.reference.raw.height) == (113.0, 60.0)
        assert twice.diagnostics == ()
