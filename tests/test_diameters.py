"""Tests for the drill standards and ``SnapDiametersToDrillTable`` (SPEC §5, PLAN task B).

Split out of ``test_pipeline.py``, which had grown to 2160 lines covering six
stages with three agents about to work on it in parallel: one file per stage
gives each agent disjoint ownership instead of a merge conflict waiting to
happen. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import random

import pytest

from aidrill.model import Severity
from aidrill.pipeline import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    DrillStandard,
    SnapDiametersToDrillTable,
)
from aidrill.pipeline.diameters import _METRIC_DECIMALS, METRIC_BANDS, _metric_sizes
from tests.conftest import at, codes, diameters, holes, make_data, positions


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

    def test_a_band_is_counted_not_accumulated(self):
        """The size a truncating count drops, on a band that actually misses.

        None of the shipped bands can show this: ``(3.0 - 0.5) / 0.05``, and
        both of its neighbours, come out exact (50.0, 110.0, 23.0), so
        truncating the quotient and rounding it agree on all 183 sizes. Editing
        the bands is the documented way to adopt another preferred series,
        though, and ``(2.9 - 0.2) / 0.1`` is ``26.999999999999996`` — a band
        whose top size disappears the moment the count stops being rounded,
        silently, with the series still ascending and still gap-free.
        """
        sizes = _metric_sizes([(0.2, 2.9, 0.1)])

        assert len(sizes) == 27
        assert sizes[-1] == 2.8, "the top of the band went missing"

    def test_the_bands_are_no_finer_than_the_decimals_they_are_rounded_to(self):
        """Rounding is dust removal; a finer band would make it corruption.

        Every size goes through ``round(..., _METRIC_DECIMALS)`` to clear
        binary-accumulation dust, which is only harmless while every band step
        is a whole number of that last decimal. A band stepping 0.025 against
        two decimals would not be tidied but *falsified* — 0.525 recorded as
        0.52, a size in no drawer — so the two are asserted against each other
        rather than each on its own.
        """
        unit = 10**-_METRIC_DECIMALS

        for start, stop, step in METRIC_BANDS:
            for value in (start, stop, step):
                assert abs(round(value / unit) * unit - value) < 1e-12, (
                    f"{value} is finer than {_METRIC_DECIMALS} decimal places"
                )


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

    def test_a_narrowed_drawer_is_blamed_as_the_drawer_and_not_as_the_standard(self):
        """5.0 *is* a metric size. What it is not in is the drawer just declared.

        ``--drill-sizes 7.0`` on a panel with 5 mm holes used to report them as
        matching "no metric drill size", which sends the operator to check the
        one thing that is right and points away from the flag they typed.
        """
        stocked = DRILL_STANDARDS["metric"].select(include=(7.0,))
        got = SnapDiametersToDrillTable(stocked).apply(
            make_data(*holes((0.0, 0.0, 5.0001)))
        )
        found = got.diagnostics[0]

        assert codes(got) == ["unknown-diameter"]
        assert "narrowed to 1 size" in found.message
        assert "no metric drill size" not in found.message
        assert found.get("stocked_size_count") == 1
        assert found.get("standard") == "metric"

    def test_an_untouched_standard_is_blamed_as_the_standard(self):
        """The other branch, and it needs its own fixture rather than a flag.

        A 30 mm cut-out is outside the whole series, so there is no drawer to
        name: reporting one would send the operator hunting for a narrowing they
        never asked for. The count goes out either way, so that a consumer
        rendering the finding never has to branch on a key's absence.
        """
        got = SnapDiametersToDrillTable().apply(make_data(*holes((0.0, 0.0, 30.0))))
        found = got.diagnostics[0]

        assert codes(got) == ["unknown-diameter"]
        assert "no metric drill size" in found.message
        assert "narrowed" not in found.message
        assert found.get("stocked_size_count") == 183

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
