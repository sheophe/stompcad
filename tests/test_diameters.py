"""Tests for the drill standards and ``SnapDiametersToDrillTable`` (SPEC §5, PLAN task B).

Split out of ``test_pipeline.py``, which had grown to 2160 lines covering six
stages with three agents about to work on it in parallel: one file per stage
gives each agent disjoint ownership instead of a merge conflict waiting to
happen. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.

Every size here is a whole number of nanometres, and the tests say so in
nanometres rather than in millimetres they would have to convert: the point of
the unit is that a drill size is an exact integer, and a fixture written as
``6.35`` could not tell an exact 6 350 000 from a float that merely prints like
one.
"""

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
from aidrill.units import format_nm, nm_from_mm


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
        """The last size of a band and the first of the next, both spellings.

        A band boundary moved either way shows up here rather than only in a
        count: 2.95 is the last of the 0.05 band and 3.0 the first of the 0.1
        band, so a first band that ran to 3.5 would put 3.05 in the table and a
        second that started at 3.5 would take 3.0 out of it.
        """
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
        """Exact by construction, and checkable rather than asserted.

        ``type(size) is int`` and not ``isinstance``: a float that landed here
        would be a size no comparison could ever meet exactly, and a ``bool``
        passes an ``isinstance`` check. Each size is also a whole number of its
        own band's step, which is what a float quotient in the generator could
        not stay true to.
        """
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
        """``SnapDiametersToDrillTable`` says so in prose; this is the arithmetic.

        The widest step anywhere is the 0.5 mm one in the top band, so the
        furthest a measurement inside 0.5–25.0 mm can sit from a size is exactly
        half of that — which is the default tolerance, and the bound is
        inclusive. It is the table's *density* that protects a panel in range,
        not the tolerance number.

        Derived from the series rather than restated, so a band edited to step
        more coarsely fails here instead of leaving that docstring a lie.
        """
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
        """1/64" is 396 875 nm exactly, and this is the reason the unit is
        nanometres rather than microns: 396.875 microns is not a whole one, and
        56 of these 64 sizes would be rounded by a micron model — reintroducing
        "is 396.875 the same bit as 397?", the question a fixed unit abolishes.

        The literal is pinned to the definition of an inch on the first line, so
        it cannot be a transcription; the multiplication is then asserted for
        every size, and the type with it, so that a float division reintroduced
        into the generator fails loudly instead of printing plausibly.
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
        """This is what makes the drawing's schedule safe without a per-emitter guard.

        It must run per standard. A decimal-millimetre label cannot serve both:
        the metric series is unique *and* truthful at 2 dp, but 1/64" is
        0.396875 mm, which no finite decimal-mm label states exactly — so the
        fractional standard labels in sixty-fourths instead.
        """
        labels = [standard.label(d) for d in standard.sizes_nm]
        assert len(set(labels)) == len(labels), f"{standard.name}: two sizes share a label"

    def test_a_metric_label_states_its_size_exactly(self):
        """Truthful, not merely unique: every label reads back as its own size.

        The round trip is the assertion. A band stepping finer than the label's
        two decimals would print 0.525 as ``⌀0.52 mm``, a size in no drawer, and
        a uniqueness check alone would not notice.
        """
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
        """1/2" *is* 12.7 mm — the same physical bit, and now the same integer.

        Merged into one table it would appear twice, with two labels, and the
        unique-label invariant above would be unsatisfiable by construction.
        """
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
        """Membership is exact, because both sides are exact.

        The drawer and the request are whole nanometres that came through the
        same unit boundary, so "is this one of mine?" is equality and not a
        near-miss — a lenient answer here would hand back a bit the operator did
        not ask for, under the name of one they did.
        """
        assert self.METRIC.select(include=(3_200_000,)).sizes_nm == (3_200_000,)
        with pytest.raises(ValueError):
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


class TestTheMeasurementIsNeverRoundedBeforeItIsCompared:
    """The defect ``units.scaled_nm`` exists to prevent, on the drill table.

    Quantising the measurement to whole nanometres *before* asking which size is
    nearest does not merely lose half a nanometre — it **manufactures a tie the
    measurement did not have**, and the tie-break, which exists to resolve
    genuine ambiguity, then resolves a fabricated one in whichever direction it
    happens to point. The answer moves by a whole drill size.
    """

    def test_a_measurement_a_hair_past_the_midpoint_takes_the_larger_bit(self):
        """5.0250004 mm, against a drawer holding 5.000 and 5.050.

        Exactly: 5 025 000.4 nm, which is 24 999.6 from 5 050 000 and 25 000.4
        from 5 000 000 — the larger bit, by six tenths of a nanometre. Rounded
        to whole nanometres first it is 5 025 000, dead centre, and the
        smaller-bit tie-break sends it to 5 000 000: a whole size away, in the
        number the machinist reads.

        The pair has to be hand-built because the metric series steps 0.05 only
        below 3 mm; the arithmetic is asserted here rather than trusted, so a
        fixture that stops being a counterexample fails as one.
        """
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
        """2.9750004 mm, between the 2.95 and 3.00 sizes the standard really has.

        The bespoke drawer above proves the arithmetic; this proves the series a
        panel is actually quantised against is exposed to it, so the defect
        cannot be dismissed as an artefact of a hand-built table.
        """
        size, found = SnapDiametersToDrillTable().quantise(measured(2.9750004))

        assert size == 3_000_000
        assert found == ()


class TestSnapDiametersToDrillTable:
    def test_bezier_noise_collapses_onto_one_bit(self):
        """THE regression this quantiser exists for (SPEC §5.1).

        6.9998 and 7.0002 are one 7 mm hole that a measurement split in two.
        Before the pipeline owned this the Excellon writer clustered them itself
        and the drawing did not, so the two artifacts disagreed about tool count.
        """
        quantiser = SnapDiametersToDrillTable()

        low = quantiser.quantise(measured(6.9998, index=4))
        high = quantiser.quantise(measured(7.0002, index=1))

        assert low == (7_000_000, ())
        assert high == (7_000_000, ())

    def test_the_declared_standard_decides_which_bit_a_measurement_is(self):
        """6.348 is a worn 1/4" bit *or* a wide 6.3 mm one, and no arithmetic can
        tell which. The operator declares the drawer; the quantiser does not guess.

        This is the fixture that a merged table could not have: the two answers
        are 50 000 nm apart, well inside the 250 000 nm matching tolerance, so a
        single sorted table would decide between them by table ordering.
        """
        hole = measured(6.348)

        metric = SnapDiametersToDrillTable(DRILL_STANDARDS["metric"])
        imperial = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"])

        assert metric.quantise(hole)[0] == 6_300_000
        assert imperial.quantise(hole)[0] == 6_350_000

    def test_a_quarter_inch_bit_keeps_its_own_size_and_is_not_rounded(self):
        """6.35 mm is a 1/4" bit, and it stays 6 350 000 nm exactly.

        Two things could have taken it away and neither may. A 0.25 mm rounding
        grid — the tolerance misused as a step — would put it at 6.25, a size no
        bit in either series has. And 6.35 is *not* a metric size (that band
        steps 6.3, 6.4), so a table that quietly held both series would have
        somewhere else to put it.
        """
        size, _ = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"]).quantise(
            measured(6.348)
        )

        assert size == 6_350_000
        assert 6_350_000 in DRILL_STANDARDS["fractional"].sizes_nm
        assert 6_350_000 not in DRILL_STANDARDS["metric"].sizes_nm

    def test_a_diameter_no_bit_can_make_is_dropped_rather_than_guessed(self):
        """A 30 mm cut-out is a step-drill or a punch, not a twist drill.

        Keeping the measurement and warning cannot survive the invariant this
        quantiser carries — every nominal diameter comes from the table —
        because a retained 30 000 000 would be a nominal that came from nowhere,
        and the drill file would load a bit that does not exist. So the answer
        is ``None``: the hole appears in no artifact, and the finding is an
        ERROR, because a drill file missing a hole looks perfectly well-formed.
        """
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
        """5.0 *is* a metric size. What it is not in is the drawer just declared.

        ``--drill-sizes 7.0`` on a panel with 5 mm holes used to report them as
        matching "no metric drill size", which sends the operator to check the
        one thing that is right and points away from the flag they typed.
        """
        stocked = DRILL_STANDARDS["metric"].select(include=(7_000_000,))
        _, found = SnapDiametersToDrillTable(stocked).quantise(measured(5.0001))
        diagnostic = found[0]

        assert codes(found) == ["unknown-diameter"]
        assert "narrowed to 1 size" in diagnostic.message
        assert "no metric drill size" not in diagnostic.message
        assert diagnostic.get("stocked_size_count") == 1
        assert diagnostic.get("standard") == "metric"

    def test_an_untouched_standard_is_blamed_as_the_standard(self):
        """The other branch, and it needs its own fixture rather than a flag.

        A 30 mm cut-out is outside the whole series, so there is no drawer to
        name: reporting one would send the operator hunting for a narrowing they
        never asked for. The count goes out either way, so that a consumer
        rendering the finding never has to branch on a key's absence.
        """
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

        assert SnapDiametersToDrillTable(tolerance_nm=250_000).quantise(hole)[0] == 25_000_000
        assert SnapDiametersToDrillTable(tolerance_nm=200_000).quantise(hole)[0] is None

    def test_a_tie_goes_to_the_smaller_bit_whatever_order_the_table_is_in(self):
        """14.25 mm sits exactly between the 14.0 and 14.5 mm sizes — exactly,
        because 14 250 000 is an integer and both distances are 250 000.

        The second half is the half that bites. Every shipped standard is
        ascending, so ``min`` returns the smaller of a tied pair *by accident*,
        and a test using one cannot tell the tie-break from that accident. A
        caller may hand this quantiser a table in any order, and the answer may
        not depend on which.
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
        """The invariant, stated as a property over the whole series.

        Every measurement inside the standard's range lands on a size the drawer
        holds — never on a rounded value, and never on its own measurement. The
        membership test is what makes "exact by construction" checkable rather
        than asserted: a quantiser that returned its own rounded measurement
        would satisfy every distance assertion and fail this one.
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
        run = SnapDiametersToDrillTable(DRILL_STANDARDS["fractional"], 100_000).describe()

        assert run.get("standard") == "fractional"
        assert run.get("tolerance_nm") == 100_000
        assert run.get("size_count") == 64

    def test_it_records_the_sizes_that_were_actually_available(self):
        """The narrowed drawer, written out in full, because nothing else says it.

        A consumer's one likely question — "what is the nearest size this panel
        could have used?" — is answered wrongly by the standard's name once the
        operator has told us which bits they own. The set is run-specific, so it
        travels with the run; it is also small, which is why it can.
        """
        drawer = DRILL_STANDARDS["metric"].select(
            include=(3_200_000, 5_000_000, 7_000_000, 12_000_000)
        )
        run = SnapDiametersToDrillTable(drawer).describe()

        assert run.get("standard") == "metric"
        assert run.get("sizes_nm") == (3_200_000, 5_000_000, 7_000_000, 12_000_000)
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
