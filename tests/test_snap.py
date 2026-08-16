"""Tests for ``SnapPositions`` (SPEC §5, PLAN task B).

Split out of ``test_pipeline.py``, which had grown to 2160 lines covering six
stages with three agents about to work on it in parallel: one file per stage
gives each agent disjoint ownership instead of a merge conflict waiting to
happen. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.

Holes are built here rather than through ``conftest.at``: a quantiser is handed
a *measurement*, and ``at`` builds the quantised hole that comes out the far
end of the phase this one is a third of.
"""

from __future__ import annotations

import math
import random

import pytest

from aidrill.model import RawHole, Severity
from aidrill.pipeline import SnapPositions


def raw(x: float, y: float, *, index: int, diameter: float = 7.0) -> RawHole:
    """One measured circle. ``index`` is keyword-only so it cannot be passed
    where ``diameter`` was meant, and no test numbers its holes in order."""
    return RawHole(x, y, diameter, index)


def codes(diagnostics) -> list[str]:
    """The stable machine key of every finding, in order."""
    return [d.code for d in diagnostics]


class TestSnapPositions:
    def test_snaps_a_measurement_onto_the_grid(self):
        (x_nm, y_nm), diagnostics = SnapPositions(250_000).quantise(
            raw(-39.99, 18.01, index=4)
        )
        assert (x_nm, y_nm) == (-40_000_000, 18_000_000)
        assert diagnostics == ()

    def test_a_hole_already_on_the_grid_neither_moves_nor_speaks(self):
        (x_nm, y_nm), diagnostics = SnapPositions(250_000).quantise(
            raw(-40.0, 18.25, index=9)
        )
        assert (x_nm, y_nm) == (-40_000_000, 18_250_000)
        assert diagnostics == ()

    def test_every_position_is_a_member_of_the_answer_set(self):
        """Exact *by construction*, and checkable rather than asserted.

        The result is ``k * grid_nm`` for a whole ``k``, so the two things worth
        proving are that it divides and that it is a plain ``int`` — a float
        that happened to divide would still be a quantity two artifacts could
        round differently, and ``bool`` divides by anything.
        """
        rng = random.Random(20250815)
        for grid_nm in (1_000, 50_000, 250_000, 300_000, 1_000_000):
            stage = SnapPositions(grid_nm)
            for index in range(60):
                hole = raw(rng.uniform(-60, 60), rng.uniform(-30, 30), index=index)
                (x_nm, y_nm), _ = stage.quantise(hole)
                assert type(x_nm) is int and type(y_nm) is int
                assert x_nm % grid_nm == 0 and y_nm % grid_nm == 0

    def test_the_measurement_is_never_rounded_before_it_is_compared(self):
        """0.1250004 mm is 125 000.4 nm, and its nearest 0.25 mm point is 0.25.

        Quantising the measurement first gives 125 000 nm, which is an exact tie
        the measurement never had, and half-to-even then resolves that fabricated
        ambiguity to 0 — a whole grid pitch from the right answer, in the number
        a machinist reads. Half a nanometre is 250 000x finer than the grid, so
        the defect is not coarseness: it is the manufactured tie.

        The hole either side of the midpoint is here too, because a quantiser
        that simply always rounded up would pass the first assertion alone.
        """
        stage = SnapPositions(250_000)

        assert stage.quantise(raw(0.1250004, 0.0, index=7))[0][0] == 250_000
        assert stage.quantise(raw(0.1249996, 0.0, index=7))[0][0] == 0
        assert stage.quantise(raw(-0.1250004, 0.0, index=7))[0][0] == -250_000
        assert stage.quantise(raw(-0.1249996, 0.0, index=7))[0][0] == 0

    def test_a_genuine_midpoint_ties_half_to_even(self):
        """The pipeline's rule, and deliberately not the unit boundary's.

        ``units`` ties away from zero because a measurement carries no meaning
        in its last digit's parity. Here the question is which grid point a hole
        should *move to*, where a consistent bias walks a whole panel one way.
        0.125 mm sits on 0.5 of a pitch and goes to 0; 0.375 sits on 1.5 and goes
        to 0.5 — the same tie resolved in two directions, which is what a
        parity rule means and what an away-from-zero rule cannot produce.
        """
        stage = SnapPositions(250_000)

        assert stage.quantise(raw(0.125, 0.0, index=3))[0][0] == 0
        assert stage.quantise(raw(0.375, 0.0, index=3))[0][0] == 500_000
        assert stage.quantise(raw(-0.125, 0.0, index=3))[0][0] == 0
        assert stage.quantise(raw(-0.375, 0.0, index=3))[0][0] == -500_000

    def test_both_axes_are_snapped(self):
        """One axis snapped and the other carried over is a live mistake.

        The two coordinates are deliberately different multiples of the grid, so
        neither can stand in for the other, and each is off the grid by a
        different amount.
        """
        (x_nm, y_nm), _ = SnapPositions(500_000).quantise(raw(-19.4, 3.1, index=1))
        assert (x_nm, y_nm) == (-19_500_000, 3_000_000)

    def test_a_small_move_does_not_warn(self):
        # default warn_over is grid / 4 == 62 500 nm; this hole moves 10 000
        _, diagnostics = SnapPositions(250_000).quantise(raw(-39.99, 18.0, index=0))
        assert codes(diagnostics) == []

    def test_a_large_move_emits_an_off_grid_warning(self):
        (x_nm, y_nm), diagnostics = SnapPositions(250_000).quantise(
            raw(-39.9, 18.0, index=0)
        )
        assert codes(diagnostics) == ["off-grid"]
        diag = diagnostics[0]
        assert diag.severity is Severity.WARNING
        assert diag.location_nm == (x_nm, y_nm) == (-40_000_000, 18_000_000)

    def test_an_explicit_threshold_overrides_the_default(self):
        hole = raw(-39.9, 18.0, index=0)
        assert codes(SnapPositions(250_000, warn_over_nm=200_000).quantise(hole)[1]) == []
        assert codes(SnapPositions(250_000, warn_over_nm=50_000).quantise(hole)[1]) == [
            "off-grid"
        ]

    def test_the_reported_distance_is_the_whole_move_and_not_one_axis(self):
        """Both axes are in the distance, and the distance is a whole number.

        The 3-4-5 fixture is chosen so no single term can stand in for the sum:
        drop the X term and the answer is 400 000, drop the Y term and it is
        300 000, and only both together give 500 000. ``math.hypot`` would
        return a float, which the payload guard refuses because a millimetre
        float under an ``_nm`` key prints as a plausible number in all three
        artifacts.
        """
        _, diagnostics = SnapPositions(1_000_000).quantise(raw(0.3, -0.4, index=8))

        assert codes(diagnostics) == ["off-grid"]
        moved_nm = diagnostics[0].get("moved_nm")
        assert moved_nm == 500_000
        assert type(moved_nm) is int

    def test_the_warning_threshold_is_inclusive_at_its_own_boundary(self):
        """A number the operator typed is a number they meant.

        The 3-4-5 hole moves exactly 500 000 nm, so a threshold of 500 000 must
        stay quiet and one nanometre under it must speak. This is the one
        boundary ``tolerance.within`` decides, sitting on it in the units the
        stage actually compares — squares of nanometres.
        """
        hole = raw(0.3, -0.4, index=8)
        assert codes(SnapPositions(1_000_000, warn_over_nm=500_000).quantise(hole)[1]) == []
        assert codes(SnapPositions(1_000_000, warn_over_nm=499_999).quantise(hole)[1]) == [
            "off-grid"
        ]

    def test_the_off_grid_diagnostic_names_the_hole_it_moved(self):
        """The stage that moves coordinates is the worst one to leave anonymous.

        ``off-grid`` was the only hole-level diagnostic carrying no payload at
        all, so a consumer joining on ``hole_index`` — as ``duplicate-hole`` and
        ``unknown-diameter`` both invite it to — dropped every off-grid finding,
        and the drawing could not ring an off-grid hole because it had nothing
        to ring it by.

        The identity is deliberately neither array position nor anything derived
        from one: this hole is numbered 6 and it is the only hole in the test.
        """
        _, diagnostics = SnapPositions(250_000).quantise(raw(-39.9, 18.0, index=6))

        diag = diagnostics[0]
        assert diag.get("hole_index") == 6
        assert diag.get("moved_nm") == 100_000
        assert diag.get("grid_nm") == 250_000

    def test_the_off_grid_message_says_which_hole_and_which_moment(self):
        """Both coordinates appear, and neither is left to be guessed at.

        The message quotes where the hole was drawn; ``location_nm`` is where it
        now is. That is one finding about two moments, and the only thing that
        makes it readable is saying so — with the hole's identity in front, so
        the sentence and the payload name the same hole.
        """
        _, diagnostics = SnapPositions(250_000).quantise(raw(-39.9, 18.0, index=6))
        message = diagnostics[0].message

        assert "hole 6" in message
        assert "-39.9000" in message and "-40.0000" in message

    def test_regression_grid_half_moves_the_five_mm_row_a_quarter_millimetre(self):
        """SPEC §9 regression: at --grid 0.5 the two ⌀5 holes go off-grid."""
        stage = SnapPositions(500_000)
        for index, x in ((5, -19.0), (2, 19.0)):
            (x_nm, y_nm), diagnostics = stage.quantise(raw(x, -18.75, index=index))
            assert codes(diagnostics) == ["off-grid"]
            assert diagnostics[0].get("moved_nm") == 250_000
            assert (x_nm, y_nm) == (round(x * 1_000_000), -19_000_000)

    def test_property_snapping_is_idempotent(self):
        """Feeding a snapped position back in must move nothing and say nothing.

        The result is an exact multiple of the grid and a whole number of
        microns, so it round-trips through millimetres without loss — which is
        what makes "snap again" a question worth asking of a value the model
        holds as an integer.
        """
        rng = random.Random(20250814)
        for grid_nm in (50_000, 100_000, 250_000, 500_000, 1_000_000, 300_000):
            stage = SnapPositions(grid_nm)
            for index in range(30):
                once, first = stage.quantise(
                    raw(rng.uniform(-60, 60), rng.uniform(-30, 30), index=index)
                )
                twice, second = stage.quantise(
                    raw(once[0] / 1_000_000, once[1] / 1_000_000, index=index)
                )
                assert twice == once
                assert codes(second) == [], "a snapped hole cannot still be off grid"
                assert len(first) <= 1


class TestSnapPositionsDescribesWhatItReallyDid:
    def test_describe_reports_the_grid_and_the_resolved_threshold(self):
        """``warn_over_nm`` is reported resolved, not as the ``None`` it was
        constructed with: a record of ``None`` tells a reader nothing about what
        happened to the data, and the drawing's title block reads this."""
        run = SnapPositions(250_000).describe()

        assert run.name == "snap"
        assert run.parameters == (("grid_nm", 250_000), ("warn_over_nm", 62_500))

    def test_describe_reports_the_effective_grid_and_not_the_requested_one(self):
        """The sheet must never stamp a pitch the holes were not snapped to.

        A clamped grid is the one case where the two differ, so it is the one
        case that can prove ``describe`` reports the effective value — and the
        threshold derives from the effective grid too, or a quarter of a pitch
        nothing was snapped to would decide which holes are reported off-grid.
        """
        run = SnapPositions(500).describe()

        assert run.parameters == (("grid_nm", 1_000), ("warn_over_nm", 250))


class TestTheGridIsAWholeNumberOfMicrons:
    """Below a micron the printed artifact stops being injective.

    The drill file and the drawing both print three decimals of a millimetre, so
    two grid points closer than a micron can come out as one coordinate — the
    model holds them apart and the sheet the machinist reads does not. The grid
    is therefore floored at a micron, and quantised to whole microns so that
    every pitch is even, which is what lets an integer midpoint test be exact
    equality.
    """

    @pytest.mark.parametrize("grid_nm", [1_001, 1_500, 250_001])
    def test_a_grid_that_is_not_a_whole_micron_is_refused(self, grid_nm):
        with pytest.raises(ValueError, match="micron"):
            SnapPositions(grid_nm)

    @pytest.mark.parametrize("requested_nm", [500, 999, 1, 0, -250_000])
    def test_a_grid_below_a_micron_is_clamped_to_one(self, requested_nm):
        """Both bounds of the clamp, zero and a negative pitch included.

        There is no way to disable snapping, so a grid at or below zero is not a
        request to leave the holes alone — it is a pitch nothing can be snapped
        to, and the floor answers it the same way it answers 500 nm.
        """
        stage = SnapPositions(requested_nm)

        assert stage.grid_nm == 1_000
        assert codes(stage.diagnostics) == ["grid-too-fine"]
        assert stage.quantise(raw(0.0005004, 0.0, index=4))[0][0] == 1_000

    def test_the_clamp_warning_names_both_the_requested_pitch_and_the_used_one(self):
        """Naming only one of them leaves the operator unable to tell which.

        Three decimals of a millimetre cannot print the two apart — that being
        the whole argument for the floor — so the requested pitch is printed at
        the resolution it was asked for, and the payload carries both as whole
        nanometres for a consumer that would rather not parse a sentence.
        """
        stage = SnapPositions(500)
        diag = stage.diagnostics[0]

        assert diag.severity is Severity.WARNING
        assert diag.get("requested_grid_nm") == 500
        assert diag.get("grid_nm") == 1_000
        assert "0.000500" in diag.message and "0.001" in diag.message

    def test_a_grid_at_or_above_a_micron_raises_nothing(self):
        assert SnapPositions(1_000).diagnostics == ()
        assert SnapPositions(250_000).diagnostics == ()

    def test_the_clamp_is_reported_once_and_not_once_per_hole(self):
        """It is a finding about the configuration, not about a hole.

        ``quantise`` sees one hole at a time, so a warning returned from there
        would be repeated for every circle on the panel — and would vanish
        entirely from a panel with no circles at all, which is precisely the run
        where the operator most needs to be told what their grid did.
        """
        stage = SnapPositions(0)

        for index in (4, 1, 9):
            # Already on the clamped micron grid, so nothing else can speak.
            _, diagnostics = stage.quantise(raw(0.001 * index, 0.0, index=index))
            assert codes(diagnostics) == []
        assert codes(stage.diagnostics) == ["grid-too-fine"]


class TestSnapPositionsRefusesAGridThatIsNotAWholeNumber:
    """K5: ``--grid=nan`` and ``--grid=inf`` both got past ``grid <= 0``.

    Every comparison against NaN is False, so the "disabled" gate let it through
    and ``round(x / nan)`` raised ``ValueError`` out of the stage — uncaught, so
    the process exited **1**, the code reserved for "warnings present". A wrapper
    testing ``[ $? -le 1 ]`` read a crash as a clean run. ``inf`` did not even
    crash: ``round(x / inf) * inf`` is ``0 * inf``, so every hole snapped to
    ``nan`` and the artifact was written with ``XnanYnan`` in it.

    A pitch in whole nanometres cannot *be* either value, but an annotation is
    not a check and nothing stops a caller passing one anyway. So the guard is
    the same guard, asking the question the model asks everywhere else: is this
    a plain ``int``? Checked once, in the constructor, on the
    ``DrillStandard.__post_init__`` precedent, so a bad value is refused before
    any hole is looked at.
    """

    @pytest.mark.parametrize(
        "grid", [float("nan"), float("inf"), float("-inf"), 0.25, 250_000.0, True]
    )
    def test_a_grid_that_is_not_an_int_is_refused_at_construction(self, grid):
        with pytest.raises(TypeError, match=r"^grid_nm"):
            SnapPositions(grid)

    @pytest.mark.parametrize(
        "warn_over", [float("nan"), float("inf"), float("-inf"), 0.0625, True]
    )
    def test_a_warning_threshold_that_is_not_an_int_is_refused_too(self, warn_over):
        """``--grid-warn=nan`` warns about every hole, including the still ones.

        ``within(moved, 0, nan)`` is False whatever the hole did, so every hole
        on the panel — the ones that did not move at all included — is reported
        off-grid. That is the same defect as a negative threshold, wearing a
        different value.
        """
        with pytest.raises(TypeError, match=r"^warn_over_nm"):
            SnapPositions(250_000, warn_over_nm=warn_over)

    def test_a_negative_warning_threshold_is_refused(self):
        """No hole can be inside it, so every hole is reported off-grid."""
        with pytest.raises(ValueError, match=r"^warn_over_nm"):
            SnapPositions(250_000, warn_over_nm=-100_000)

    def test_a_zero_warning_threshold_is_allowed(self):
        """"Tell me about every hole that moved at all" is a real request."""
        stage = SnapPositions(250_000, warn_over_nm=0)

        assert codes(stage.quantise(raw(0.0, 0.0, index=4))[1]) == []
        assert codes(stage.quantise(raw(0.01, 0.0, index=1))[1]) == ["off-grid"]


def test_the_stage_reports_a_distance_it_could_not_have_got_from_hypot():
    """``math.isqrt`` floors; ``math.hypot`` returns a float that is not it.

    A hole moving 100 000 nm on both axes is 141 421.35... nm from where it was
    drawn. The payload must hold the floor of that as an ``int``, and the point
    of asserting the two against each other is that a stage reaching for the
    float would round to 141 421 as well — and then fail the model's guard for
    reasons no arithmetic here would explain.
    """
    _, diagnostics = SnapPositions(1_000_000, warn_over_nm=100_000).quantise(
        raw(0.1, 0.1, index=2)
    )

    moved_nm = diagnostics[0].get("moved_nm")
    assert moved_nm == 141_421
    assert moved_nm < math.hypot(100_000, 100_000)
