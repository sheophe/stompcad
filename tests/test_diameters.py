"""Tests for drill standards and diameter quantisation."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from aidrill.model import RawHole, Severity
from aidrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    FRACTIONAL_SIXTY_FOURTHS,
    METRIC_BANDS,
    DrillStandard,
    SnapDiametersToDrillTable,
)
from aidrill.units import Nanometre, format_nm, nm_from_mm


def measured(diameter: float, *, index: int = 4, x: float = 0.0, y: float = 0.0) -> RawHole:
    """One circle as the artwork measured it, in millimetres.

    ``index`` defaults to 4 rather than 0 so that no assertion about a hole's
    identity can be satisfied by its position in a list instead.
    """
    return RawHole(x, y, diameter, index)


def codes(diagnostics) -> list[str]:
    """The stable machine key of every finding, in order."""
    return [d.code for d in diagnostics]


class TestTheMetricSeriesIsGeneratedNotTranscribed:
    """A rule cannot carry a transcription typo, so the bands are the source."""

    METRIC = DRILL_STANDARDS["metric"]

    def test_the_bands_cover_half_a_millimetre_to_twenty_five(self):
        assert len(self.METRIC.sizes_nm) == 183
        assert self.METRIC.sizes_nm[0] == 500_000
        assert self.METRIC.sizes_nm[-1] == 25_000_000

    def test_each_band_steps_at_its_own_pitch_right_up_to_the_next_one(self):
        """The last size of a band and the first of the next, both spellings."""
        sizes = set(self.METRIC.sizes_nm)
        assert {2_950_000, 3_000_000, 13_900_000, 14_000_000, 14_500_000, 25_000_000} <= sizes
        assert 3_050_000 not in sizes, "the 0.05 band ran past its stop"
        assert 13_950_000 not in sizes, "the 0.1 band ran past its stop"
        assert 25_500_000 not in sizes, "the stop of the last band is exclusive too"

    def test_the_series_is_ascending_and_has_no_size_twice(self):
        sizes = self.METRIC.sizes_nm
        assert list(sizes) == sorted(sizes)
        assert len(set(sizes)) == len(sizes)

    def test_every_size_is_a_whole_number_of_nanometres_on_its_band_step(self):
        """Exact by construction, and checkable rather than asserted."""
        steps = {}
        for start, stop, step in METRIC_BANDS:
            for size in self.METRIC.sizes_nm:
                if nm_from_mm(start) <= size < nm_from_mm(stop):
                    steps[size] = nm_from_mm(step)

        assert len(steps) == len(self.METRIC.sizes_nm), "a size fell outside every band"
        for size, step_nm in steps.items():
            assert type(size) is int, f"{size!r} is not a whole number of nanometres"
            assert size % step_nm == 0, f"{size} is not a multiple of its band's {step_nm} step"

    def test_the_table_is_dense_enough_that_in_range_matching_cannot_fail(self):
        """The maximum half-step equals the inclusive matching tolerance."""
        sizes = self.METRIC.sizes_nm
        widest = max(sizes[i + 1] - sizes[i] for i in range(len(sizes) - 1))

        assert widest == 500_000
        assert SnapDiametersToDrillTable().tolerance_nm >= widest // 2


class TestTheFractionalSeriesIsExactByConstruction:
    FRACTIONAL = DRILL_STANDARDS["fractional"]

    def test_sixty_four_sixty_fourths_up_to_one_inch(self):
        """The count and the top of the series are asserted apart, because they
        fail for different edits: a series stopping at 63 is one bit short *and*
        no longer reaches an inch, and only the second says which end went."""
        assert len(self.FRACTIONAL.sizes_nm) == 64
        assert self.FRACTIONAL.sizes_nm[-1] == 25_400_000

    def test_every_sixty_fourth_is_a_whole_number_of_nanometres(self):
        """1/64" is 396 875 nm exactly, and this is the reason the unit is nanometres
        rather than microns: 396.875 microns is not a whole one, and 56 of these 64
        sizes would be rounded by a micron model — reintroducing "is 396.875 the same
        bit as 397?", the question a fixed unit abolishes.
        """
        assert 396_875 * 64 == nm_from_mm(25.4), "1/64 of an inch is not what it is"

        for n, size in zip(FRACTIONAL_SIXTY_FOURTHS, self.FRACTIONAL.sizes_nm, strict=True):
            assert size == n * 396_875
            assert type(size) is int, f"{n}/64\" came out as {size!r}"

    def test_the_common_bits_are_exact_with_no_rounding_anywhere(self):
        sizes = self.FRACTIONAL.sizes_nm
        assert sizes[0] == 396_875  # 1/64", 0.396875 mm
        assert sizes[7] == 3_175_000  # 1/8"
        assert sizes[15] == 6_350_000  # 1/4"
        assert sizes[31] == 12_700_000  # 1/2"

    def test_the_series_is_ascending_and_has_no_size_twice(self):
        sizes = self.FRACTIONAL.sizes_nm
        assert list(sizes) == sorted(sizes)
        assert len(set(sizes)) == len(sizes)


class TestLabels:
    """What gets stamped on a drawing for each size."""

    @pytest.mark.parametrize("standard", DRILL_STANDARDS.values(), ids=lambda s: s.name)
    def test_every_size_has_a_label_that_is_unique_within_its_standard(self, standard):
        """This is what makes the drawing's schedule safe without a per-emitter guard."""
        labels = [standard.label(d) for d in standard.sizes_nm]
        assert len(set(labels)) == len(labels), f"{standard.name}: two sizes share a label"

    def test_a_metric_label_states_its_size_exactly(self):
        """Truthful, not merely unique: every label reads back as its own size."""
        metric = DRILL_STANDARDS["metric"]
        for size in metric.sizes_nm:
            stated = metric.label(size).removeprefix("⌀").removesuffix(" mm")
            assert nm_from_mm(float(stated)) == size, f"{metric.label(size)} misstates {size}"
        assert metric.label(3_200_000) == "⌀3.20 mm"

    def test_a_fractional_label_is_the_fraction_not_a_rounded_millimetre(self):
        """0.40 mm would be a lie about a 1/64" bit, and 3.18 mm about a 1/8" one."""
        fractional = DRILL_STANDARDS["fractional"]
        assert fractional.label(396_875) == '⌀1/64"'
        assert fractional.label(3_175_000) == '⌀1/8"'
        assert fractional.label(12_700_000) == '⌀1/2"'
        assert fractional.label(25_400_000) == '⌀1"'

    def test_no_fractional_label_would_survive_being_written_in_millimetres(self):
        """Measured, not assumed: the fractional series is truthful at *no*
        decimal precision, which is why ``label`` is a function and not a
        ``display_decimals`` int. Every bit whose label is a proper fraction
        misstates its own millimetre value at 2, 3 and 4 decimals."""
        fractional = DRILL_STANDARDS["fractional"]
        for decimals in (2, 3, 4):
            lying = [
                s for s in fractional.sizes_nm if nm_from_mm(float(format_nm(s, decimals))) != s
            ]
            assert lying, f"a decimal-mm label at {decimals} dp would be truthful"


class TestTheTwoStandardsAreNeverMerged:
    def test_one_size_belongs_to_both_series_under_two_names(self):
        """1/2 inch and 12.7 mm are one size with standard-specific labels."""
        metric = set(DRILL_STANDARDS["metric"].sizes_nm)
        fractional = set(DRILL_STANDARDS["fractional"].sizes_nm)
        assert metric & fractional == {12_700_000}
        assert DRILL_STANDARDS["metric"] is not DRILL_STANDARDS["fractional"]

    def test_neighbouring_sizes_across_the_two_series_are_closer_than_the_tolerance(self):
        """3.175 (1/8") and 3.2 (metric) are 25 000 nm apart, a tenth of the
        matching tolerance. In one table the choice between them would be
        decided by table ordering rather than by anything real."""
        metric = DRILL_STANDARDS["metric"].sizes_nm
        fractional = DRILL_STANDARDS["fractional"].sizes_nm
        crowded = [(a, b) for a in fractional for b in metric if 0 < abs(a - b) < 50_000]
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
        stocked = self.METRIC.select(include=(3_200_000, 5_000_000, 7_000_000, 12_000_000))
        assert stocked.sizes_nm == (3_200_000, 5_000_000, 7_000_000, 12_000_000)

    def test_a_whitelist_is_sorted_however_it_was_typed(self):
        typed = (12_000_000, 3_200_000, 7_000_000)
        assert self.METRIC.select(include=typed).sizes_nm == (3_200_000, 7_000_000, 12_000_000)

    def test_a_blacklist_removes_exactly_the_sizes_named(self):
        """The bit that snapped, and nothing else, leaves the drawer."""
        thinned = self.METRIC.select(exclude=(3_200_000, 7_000_000, 12_000_000))
        assert len(thinned.sizes_nm) == len(self.METRIC.sizes_nm) - 3
        assert 3_200_000 not in thinned.sizes_nm
        assert 7_000_000 not in thinned.sizes_nm
        assert 12_000_000 not in thinned.sizes_nm
        assert 3_300_000 in thinned.sizes_nm and 6_900_000 in thinned.sizes_nm

    def test_a_blacklist_applies_on_top_of_a_whitelist(self):
        both = self.METRIC.select(
            include=(3_200_000, 5_000_000, 7_000_000, 12_000_000), exclude=(5_000_000,)
        )
        assert both.sizes_nm == (3_200_000, 7_000_000, 12_000_000)

    def test_narrowing_leaves_the_standard_it_came_from_alone(self):
        """A narrowed copy, not an edit: the registry is shared by every run."""
        narrowed = self.METRIC.select(include=(3_200_000, 7_000_000))

        assert len(self.METRIC.sizes_nm) == 183, "select mutated the registry"
        assert narrowed is not self.METRIC
        assert narrowed.name == self.METRIC.name
        assert narrowed.label(3_200_000) == "⌀3.20 mm"

    def test_selecting_nothing_is_the_standard_itself(self):
        assert self.METRIC.select().sizes_nm == self.METRIC.sizes_nm

    def test_a_size_the_standard_does_not_have_is_refused_rather_than_ignored(self):
        """``--drill-sizes 3.33`` is a typo, and a silently empty drawer is the
        worst possible answer to it: every hole would then be unknown."""
        with pytest.raises(ValueError, match="3.33"):
            self.METRIC.select(include=(3_200_000, 3_330_000))
        with pytest.raises(ValueError, match="3.33"):
            self.METRIC.select(exclude=(3_330_000,))

    def test_a_size_one_nanometre_off_is_a_size_the_standard_does_not_have(self):
        """Membership is exact, because both sides are exact."""
        assert self.METRIC.select(include=(3_200_000,)).sizes_nm == (3_200_000,)
        with pytest.raises(ValueError, match="no such size"):
            self.METRIC.select(include=(3_200_001,))

    def test_a_metric_size_is_not_a_fractional_one(self):
        """The refusal is against the standard in hand, not against bits in general.

        3.2 mm is a real drill; it is not a *fractional* drill, and a drawer of
        imperial bits does not contain one.
        """
        with pytest.raises(ValueError, match="3.2"):
            DRILL_STANDARDS["fractional"].select(include=(3_200_000,))
        assert DRILL_STANDARDS["fractional"].select(include=(3_175_000,)).sizes_nm == (3_175_000,)

    def test_narrowing_a_standard_down_to_nothing_is_refused(self):
        with pytest.raises(ValueError, match="no sizes"):
            self.METRIC.select(include=(3_200_000,), exclude=(3_200_000,))


class TestTheAnswerSetAndItsBoundAreCheckedWhereTheyAreDeclared:
    """Reject invalid tables and bounds at construction.

    The bad size is not first, so validation of only the first entry cannot pass.
    """

    LABEL = DRILL_STANDARDS["metric"].label

    def drawer(self, sizes_nm) -> DrillStandard:
        return DrillStandard(name="drawer", sizes_nm=sizes_nm, label=self.LABEL)

    def test_a_size_that_is_not_whole_nanometres_is_no_size(self):
        """Every drill-table size must be plain-integer nanometres at construction."""
        with pytest.raises(TypeError, match=r"size\[1\]"):
            self.drawer((3_200_000, 7_000_000.0))

    def test_a_boolean_size_is_no_size_either(self):
        """Checked apart from the float because ``bool`` is an ``int`` in
        Python: ``True`` passes an ``isinstance`` guard and is then offered to
        an operator as the nearest bit to their hole, one nanometre across."""
        with pytest.raises(TypeError, match=r"size\[1\]"):
            self.drawer((3_200_000, True))

    @pytest.mark.parametrize("size_nm", [0, -3_200_000])
    def test_a_size_no_bit_could_have_is_refused(self, size_nm):
        with pytest.raises(ValueError, match="no bit is nothing across"):
            self.drawer((3_200_000, size_nm))

    def test_a_tolerance_that_is_not_whole_nanometres_is_refused(self):
        """0.25 mm typed as millimetres is the plausible mistake, and it is the
        one the bound cannot survive: it is published under ``tolerance_nm`` in
        the record and in every refusal's payload, where a consumer reads it as
        nanometres."""
        with pytest.raises(TypeError, match="tolerance_nm"):
            SnapDiametersToDrillTable(tolerance_nm=250_000.0)

    def test_a_boolean_tolerance_is_refused(self):
        with pytest.raises(TypeError, match="tolerance_nm"):
            SnapDiametersToDrillTable(tolerance_nm=True)

    def test_a_negative_tolerance_is_refused_rather_than_clamped(self):
        """No measurement is inside a negative bound, so every hole on the panel
        becomes an ``unknown-diameter`` ERROR — a report naming every hole and
        not the one number that refused them all."""
        with pytest.raises(ValueError, match="negative"):
            SnapDiametersToDrillTable(tolerance_nm=Nanometre(-1))

    def test_a_bound_of_nothing_is_a_bound_and_is_kept(self):
        """Zero is a real answer — the measurement *is* a size in the table, to
        the nanometre — and refusing it would refuse a question the operator is
        entitled to ask."""
        quantiser = SnapDiametersToDrillTable(tolerance_nm=Nanometre(0))

        assert quantiser.quantise(measured(7.0)) == (7_000_000, ())
        assert quantiser.quantise(measured(7.000001))[0] is None


class TestTheMeasurementIsNeverRoundedBeforeItIsCompared:
    """Compare measurements with the drill table before rounding them."""

    def test_a_measurement_a_hair_past_the_midpoint_takes_the_larger_bit(self):
        """5.0250004 mm, against a drawer holding 5.000 and 5.050."""
        drawer = DrillStandard(
            name="drawer", sizes_nm=(5_000_000, 5_050_000), label=DRILL_STANDARDS["metric"].label
        )
        exact = Decimal("5.0250004") * 1_000_000
        assert abs(exact - 5_050_000) < abs(exact - 5_000_000), "the fixture is not past centre"
        assert nm_from_mm(5.0250004) == 5_025_000, "the rounded copy is not a tie"

        size, found = SnapDiametersToDrillTable(drawer).quantise(measured(5.0250004))

        assert size == 5_050_000
        assert found == ()

    def test_the_same_hair_moves_a_bit_on_the_shipped_metric_series(self):
        """2.9750004 mm, between the 2.95 and 3.00 sizes the standard really has."""
        size, found = SnapDiametersToDrillTable().quantise(measured(2.9750004))

        assert size == 3_000_000
        assert found == ()

    def test_the_tolerance_is_decided_on_the_measurement_and_not_on_a_rounding(self):
        """25.2500004 mm lies outside the 250 000 nm tolerance unrounded.

        Rounding first puts it exactly on the inclusive bound and would accept it.
        """
        exact = Decimal("25.2500004") * 1_000_000
        assert abs(exact - 25_000_000) > 250_000, "the fixture is inside the bound"
        assert nm_from_mm(25.2500004) - 25_000_000 == 250_000, (
            "the rounded copy is not on the bound"
        )

        size, found = SnapDiametersToDrillTable().quantise(measured(25.2500004))

        assert size is None
        assert codes(found) == ["unknown-diameter"]


class TestSnapDiametersToDrillTable:
    def test_bezier_noise_collapses_onto_one_bit(self):
        """Bézier noise collapses onto one bit."""
        quantiser = SnapDiametersToDrillTable()

        low = quantiser.quantise(measured(6.9998, index=4))
        high = quantiser.quantise(measured(7.0002, index=1))

        assert low == (7_000_000, ())
        assert high == (7_000_000, ())

    def test_the_declared_standard_decides_which_bit_a_measurement_is(self):
        """6.348 is a worn 1/4" bit *or* a wide 6.3 mm one, and no arithmetic can tell
        which. The operator declares the drawer; the quantiser does not guess.
        """
        hole = measured(6.348)

        metric = SnapDiametersToDrillTable(DRILL_STANDARDS["metric"])
        imperial = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"])

        assert metric.quantise(hole)[0] == 6_300_000
        assert imperial.quantise(hole)[0] == 6_350_000

    def test_a_quarter_inch_bit_keeps_its_own_size_and_is_not_rounded(self):
        """6.35 mm is a 1/4" bit, and it stays 6 350 000 nm exactly."""
        size, _ = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]).quantise(
            measured(6.348)
        )

        assert size == 6_350_000
        assert 6_350_000 in DRILL_STANDARDS["fractional"].sizes_nm
        assert 6_350_000 not in DRILL_STANDARDS["metric"].sizes_nm

    def test_a_diameter_no_bit_can_make_is_dropped_rather_than_guessed(self):
        """A 30 mm cut-out is a step-drill or a punch, not a twist drill."""
        size, found = SnapDiametersToDrillTable().quantise(measured(30.0))

        assert size is None
        assert codes(found) == ["unknown-diameter"]
        assert found[0].severity is Severity.ERROR

    def test_a_size_it_accepts_is_reported_without_a_finding(self):
        """The other branch of the same rule: no diagnostic rides along with a
        hole that matched, so a run of clean holes is a clean run."""
        assert SnapDiametersToDrillTable().quantise(measured(7.0002))[1] == ()

    def test_the_diagnostic_names_the_hole_and_the_nearest_bit(self):
        """``data`` so a consumer need not re-measure: which hole, what it
        measured, and the closest thing the drawer actually holds."""
        _, found = SnapDiametersToDrillTable().quantise(measured(30.0, index=4, x=3.0, y=-2.0))
        diagnostic = found[0]

        assert diagnostic.get("hole_index") == 4
        assert diagnostic.get("diameter_nm") == 30_000_000
        assert diagnostic.get("nearest_nm") == 25_000_000
        assert diagnostic.get("standard") == "metric"
        assert diagnostic.get("tolerance_nm") == 250_000
        assert diagnostic.location_nm == (3_000_000, -2_000_000)

    def test_the_dropped_hole_is_named_by_its_identity_not_its_position(self):
        """Holes numbered 4, 1, 9 — so a payload reporting a list position
        cannot pass by coincidence. The two refused holes sit at positions 0 and
        2 and are numbered 4 and 9, and it is the numbers that go out."""
        quantiser = SnapDiametersToDrillTable()
        panel = (measured(30.0, index=4), measured(7.0, index=1), measured(0.1, index=9))

        refused = []
        for hole in panel:
            _, found = quantiser.quantise(hole)
            refused.extend(d.get("hole_index") for d in found)

        assert refused == [4, 9]

    def test_a_narrowed_drawer_is_blamed_as_the_drawer_and_not_as_the_standard(self):
        """5.0 *is* a metric size. What it is not in is the drawer just declared."""
        stocked = DRILL_STANDARDS["metric"].select(include=(7_000_000,))
        _, found = SnapDiametersToDrillTable(stocked).quantise(measured(5.0001))
        diagnostic = found[0]

        assert codes(found) == ["unknown-diameter"]
        assert "narrowed to 1 size;" in diagnostic.message
        assert "no metric drill size" not in diagnostic.message
        assert diagnostic.get("stocked_size_count") == 1
        assert diagnostic.get("standard") == "metric"

    def test_an_untouched_standard_is_blamed_as_the_standard(self):
        """An untouched standard is blamed as the standard."""
        _, found = SnapDiametersToDrillTable().quantise(measured(30.0))
        diagnostic = found[0]

        assert "no metric drill size" in diagnostic.message
        assert "narrowed" not in diagnostic.message
        assert diagnostic.get("stocked_size_count") == 183

    def test_the_matching_tolerance_is_inclusive_at_its_boundary(self):
        """25.25 mm is exactly 250 000 nm from the 25 mm bit; 25.3 is further.

        Exactly, in integers: this is the boundary the bound decides, and a
        measurement sitting on a number the operator typed is one they meant.
        """
        quantiser = SnapDiametersToDrillTable()

        assert quantiser.quantise(measured(25.25)) == (25_000_000, ())
        assert quantiser.quantise(measured(25.3))[0] is None

    def test_a_tighter_tolerance_refuses_what_a_looser_one_accepted(self):
        hole = measured(25.25)

        assert SnapDiametersToDrillTable(tolerance_nm=Nanometre(250_000)).quantise(hole)[0] == 25_000_000
        assert SnapDiametersToDrillTable(tolerance_nm=Nanometre(200_000)).quantise(hole)[0] is None

    def test_a_tie_goes_to_the_smaller_bit_whatever_order_the_table_is_in(self):
        """14.25 mm sits exactly between the 14.0 and 14.5 mm sizes — exactly, because 14
        250 000 is an integer and both distances are 250 000.
        """
        hole = measured(14.25)
        label = DRILL_STANDARDS["metric"].label

        assert SnapDiametersToDrillTable().quantise(hole)[0] == 14_000_000

        for order in ((14_000_000, 14_500_000), (14_500_000, 14_000_000)):
            drawer = DrillStandard(name="drawer", sizes_nm=order, label=label)
            size, _ = SnapDiametersToDrillTable(drawer).quantise(hole)
            assert size == 14_000_000, f"the answer changed with the table order {order}"

    def test_it_quantises_against_the_narrowed_table_not_the_whole_standard(self):
        """The drawer, not the catalogue: with no 7 mm bit in it, a 6.9998 mm
        hole is drilled with whatever *is* there."""
        drawer = DRILL_STANDARDS["metric"].select(include=(3_200_000, 6_800_000, 12_000_000))

        assert SnapDiametersToDrillTable(drawer).quantise(measured(6.9998))[0] == 6_800_000

    def test_distinct_sizes_stay_distinct(self):
        """Normalisation is not clustering: three measurements, two bits."""
        quantiser = SnapDiametersToDrillTable()
        panel = (measured(5.02, index=4), measured(6.98, index=1), measured(4.99, index=9))

        assert [quantiser.quantise(h)[0] for h in panel] == [5_000_000, 7_000_000, 5_000_000]

    def test_every_nominal_it_produces_is_a_size_the_drawer_holds(self):
        """Every accepted nominal is a table size within tolerance.

        Membership rejects returning the rounded measurement, which distance permits.
        """
        rng = random.Random(20250815)
        standard = DRILL_STANDARDS["metric"]
        quantiser = SnapDiametersToDrillTable()
        measurements = [round(rng.uniform(0.5, 25.0), 4) for _ in range(200)]

        for index, millimetres in enumerate(measurements):
            size, found = quantiser.quantise(measured(millimetres, index=index))

            assert found == ()
            assert size in standard.sizes_nm
            assert type(size) is int
            # Spelled out rather than routed through the module's own helper: a
            # test that borrows the implementation's arithmetic cannot catch the
            # implementation getting that arithmetic wrong.
            assert abs(Decimal(str(millimetres)) * 1_000_000 - size) <= 250_000


class TestDescribe:
    """What the run records about the drawer it quantised against."""

    def test_it_describes_itself_under_its_own_name(self):
        assert SnapDiametersToDrillTable().describe().name == SnapDiametersToDrillTable.name

    def test_it_reports_the_standard_it_quantised_against(self):
        run = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"], Nanometre(100_000)).describe()

        assert run.get("standard") == "fractional"
        assert run.get("tolerance_nm") == 100_000
        assert run.get("size_count") == 64

    def test_it_records_the_sizes_that_were_actually_available(self):
        """The narrowed drawer, written out in full, because nothing else says it."""
        drawer = DRILL_STANDARDS["metric"].select(
            include=(3_200_000, 5_000_000, 7_000_000, 12_000_000)
        )
        run = SnapDiametersToDrillTable(drawer).describe()

        assert run.get("standard") == "metric"
        assert run.get("sizes_nm") == (3_200_000, 5_000_000, 7_000_000, 12_000_000)
        assert run.get("size_count") == 4

    def test_an_unnarrowed_standard_is_recorded_by_name_and_count_alone(self):
        """183 sizes a reader can look up are not worth 90 % of the document."""
        run = SnapDiametersToDrillTable().describe()

        assert run.get("standard") == "metric"
        assert run.get("size_count") == 183
        assert run.get("tolerance_nm") == 250_000
        assert "sizes_nm" not in dict(run.parameters)

    def test_a_table_no_registry_name_can_rebuild_records_its_sizes(self):
        """The rule is "can a reader rebuild this from the name?", not "did
        ``select`` run?" — a hand-built standard answers no just as a narrowed
        one does, and a reader looking up its name would find nothing at all."""
        shed = DrillStandard(
            name="the-drawer-in-the-shed",
            sizes_nm=(3_200_000, 7_000_000),
            label=DRILL_STANDARDS["metric"].label,
        )
        run = SnapDiametersToDrillTable(shed).describe()

        assert run.get("sizes_nm") == (3_200_000, 7_000_000)
        assert run.get("size_count") == 2
