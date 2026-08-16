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

from aidrill.model import Hole, RawHole, Severity
from aidrill.pipeline import SnapPositions


def raw(x: float, y: float, *, index: int, diameter: float = 7.0) -> RawHole:
    """One measured circle. ``index`` is keyword-only so it cannot be passed
    where ``diameter`` was meant, and no test numbers its holes in order."""
    return RawHole(x, y, diameter, index)


def snapped(stage: SnapPositions, *measurements: RawHole) -> tuple[Hole, ...]:
    """The finished holes, assembled the way the quantisation phase assembles them.

    ``review_panel`` reads ``Hole.residual_nm``, which is the same subtraction
    ``quantise`` made, so the fixtures go through the real snap rather than
    stating a residual by hand: a ``Hole`` whose ``raw`` was written to sit half
    a pitch away would prove the predicate reads what the test wrote and nothing
    at all about what snapping does to a measurement.
    """
    holes = []
    for measurement in measurements:
        (x_nm, y_nm), _ = stage.quantise(measurement)
        holes.append(
            Hole(
                x_nm=x_nm,
                y_nm=y_nm,
                diameter_nm=7_000_000,
                raw=measurement,
                index=measurement.index,
            )
        )
    return tuple(holes)


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


class TestAPanelFullOfTiesWasDrawnOnAnotherGrid:
    """Half-to-even is deterministic and says nothing about what was meant.

    A hole exactly halfway between two grid points gets one of them by a rule
    rather than by evidence. One such hole is nothing — the question genuinely
    had two equally good answers and either is drillable. Half a panel is a
    different fact: artwork drawn on 0.5 mm and run at ``--grid 1.0`` puts
    *every* hole on a midpoint, and the tool drilled it without comment. The
    holes are snapped either way; the operator is owed being told before the
    drill finds out.

    Every fixture here runs at a 250 000 nm pitch, so a tie is a residual of
    exactly 125 000 nm on either axis.
    """

    @pytest.mark.parametrize(
        "x, y",
        [(0.125, 0.0), (-0.125, 0.0), (0.0, 0.375), (0.0, -0.375)],
    )
    def test_a_tie_counts_on_either_axis_and_at_either_sign(self, x, y):
        """Four cases, because a plausible implementation drops half of them.

        A ``Decimal`` remainder keeps the dividend's sign — ``Decimal("-1.5") %
        1`` is ``Decimal("-0.5")`` — so the natural spelling would have counted
        the positive residuals and silently ignored every negative one, which on
        a centre-origin panel is half the holes. ``abs`` makes the integer form
        sign-safe for free, and these four exist because that defect was
        invisible until somebody went looking for it.

        The Y fixtures sit on 1.5 pitches rather than 0.5 so that half-to-even
        resolves them the other way: X yields residuals of −125 000 and
        +125 000, Y of +125 000 and −125 000, and each axis therefore carries a
        tie of each sign rather than the two axes agreeing on one.
        """
        stage = SnapPositions(250_000)

        assert codes(stage.review_panel(snapped(stage, raw(x, y, index=4)))) == [
            "grid-ambiguous"
        ]

    def test_a_hole_tied_on_both_axes_counts_where_the_scalar_distance_would_not(self):
        """The most obvious way to draw on the wrong grid, and the one a
        Euclidean test fails hardest on.

        ``moved_nm`` is ``math.isqrt`` of the summed squares, and that equals
        half a pitch only when exactly one axis moved half a pitch and the other
        did not move at all. This hole moves 125 000 nm on each axis, so it is
        176 776 nm from where it was drawn — nothing a rule looking for 125 000
        would recognise — while both of its residuals are exact midpoints. The
        scalar distance stays right for the off-grid report and is no use here.
        """
        stage = SnapPositions(250_000)
        measurement = raw(0.125, 0.125, index=4)

        assert stage.quantise(measurement)[1][0].get("moved_nm") == 176_776
        assert codes(stage.review_panel(snapped(stage, measurement))) == [
            "grid-ambiguous"
        ]

    def test_a_tie_on_one_axis_survives_an_ordinary_residual_on_the_other(self):
        """``or``, and never ``and``.

        A tie on either axis already proves the declared pitch is not the one
        the artwork was drawn on. ``and`` would ask every tied hole to be offset
        diagonally, and would score a row of pots at constant Y — offset in X
        alone, the common case — as evidence that nothing is wrong. Here Y moves
        31 000 nm, which is neither a tie nor nothing.
        """
        stage = SnapPositions(250_000)

        assert codes(
            stage.review_panel(snapped(stage, raw(0.125, 0.031, index=4)))
        ) == ["grid-ambiguous"]

    def test_a_hole_already_on_a_grid_point_is_not_tied(self):
        """Residual zero, and ``2 * 0 == grid_nm`` is false for any real pitch.

        A hole on-grid in both axes is consistent with the declared grid *and*
        with the finer one it might have been drawn on, so it is not evidence
        either way and the predicate abstains. Counting it would warn about
        every well-drawn panel there is.
        """
        stage = SnapPositions(250_000)
        holes = snapped(stage, raw(-0.25, 0.5, index=4), raw(0.75, -1.0, index=1))

        assert stage.review_panel(holes) == ()

    def test_one_tie_among_many_is_enough_and_none_stays_quiet(self):
        """A single tie is a hole placed by a rule rather than by the artwork.

        The proportion this once required is gone. It bought nothing and cost
        two things: it made the answer depend on *which* holes were counted, so
        a duplicated circle could push a panel over the line or hold it under
        and leave the finding disagreeing with the drill file about how many
        holes the panel has; and it stayed silent on the panel with one
        deliberate half-offset hole, which is the case most worth naming.

        One tied hole in four, therefore — the case the old rule ignored.
        """
        stage = SnapPositions(250_000)
        one_tie = (
            raw(0.125, 0.0, index=4),
            raw(-1.0, 0.0, index=1),
            raw(2.0, 0.0, index=9),
            raw(3.0, 0.0, index=7),
        )

        assert codes(stage.review_panel(snapped(stage, *one_tie))) == ["grid-ambiguous"]
        assert stage.review_panel(snapped(stage, *one_tie[1:])) == ()

    def test_a_duplicated_tie_cannot_change_the_verdict(self):
        """Two marks at one place are one hole, and must not count as evidence twice.

        This is what asking "did any hole tie" buys over asking "did half of
        them". A duplicate is identical by definition, so it carries the
        identical residual, and ``Deduplicate`` keeps one of each group — so the
        answer is the same whether the review sees the drawn circles or the
        holes that survive into the artifacts, and nothing here has to know
        which side of dedupe it was handed.
        """
        stage = SnapPositions(250_000)
        tied, twin = raw(0.125, 0.0, index=4), raw(0.125, 0.0, index=9)
        ordinary = (raw(-1.0, 0.0, index=1), raw(2.0, 0.0, index=7))

        with_twin = stage.review_panel(snapped(stage, tied, twin, *ordinary))
        without = stage.review_panel(snapped(stage, tied, *ordinary))

        assert codes(with_twin) == codes(without) == ["grid-ambiguous"]

    def test_a_panel_with_no_holes_on_it_says_nothing(self):
        """No ties, nothing to say — and an empty tuple is falsey, so this needs
        no guard of its own. A warning about a run with no circles in it is
        noise in front of an operator who has nothing to fix."""
        assert SnapPositions(250_000).review_panel(()) == ()

    def test_the_finding_names_the_tied_holes_by_identity_and_not_by_position(self):
        """4, 1, 9 — and the tied ones are the first and the last.

        Numbered in order, the answer ``(0, 2)`` would be indistinguishable from
        the positions those holes occupy in the list, and an assertion about
        identity that also passes for position is not an assertion about
        identity. Hole 1 sits between them, on the grid, and must not appear.
        """
        stage = SnapPositions(250_000)
        holes = snapped(
            stage,
            raw(0.125, 0.0, index=4),
            raw(-0.5, 0.0, index=1),
            raw(0.0, -0.375, index=9),
        )

        diag = stage.review_panel(holes)[0]

        assert diag.severity is Severity.WARNING
        assert diag.get("tied_indices") == (4, 9)
        # No denominator, deliberately: nothing decides by proportion now, so a
        # hole count would be context measured before dedupe — free to say
        # three where the drill file says two.
        assert "hole_count" not in dict(diag.data)
        assert "tied_count" not in dict(diag.data)

    def test_the_finding_is_about_the_panel_and_names_no_representative_hole(self):
        """A singular ``hole_index`` is the payload of a hole-level finding.

        Naming one hole out of a tied set would put an arbitrary member where
        the cause belongs: the drawing rings whatever ``hole_index`` names, and
        the operator would go and inspect a hole no more at fault than the two
        beside it. There is no coordinate either — the finding is about the
        pitch, which is nowhere on the panel.
        """
        stage = SnapPositions(250_000)
        diag = stage.review_panel(snapped(stage, raw(0.125, 0.0, index=4)))[0]

        # The key must be *absent*, not present and null. ``get`` cannot tell
        # those apart — its default is ``None`` too — and they are different
        # public shapes: a consumer routing findings by key presence reads
        # ``"hole_index": null`` as a hole-shaped payload with no hole in it.
        assert "hole_index" not in dict(diag.data)
        assert diag.location_nm is None

    def test_the_message_says_how_many_tied_and_which_pitch(self):
        """What the operator can act on is the grid they declared, so the
        sentence has to point there — the positions are not wrong, and a message
        about the holes would send them looking for a defect in the artwork."""
        stage = SnapPositions(250_000)
        holes = snapped(
            stage,
            raw(0.125, 0.0, index=4),
            raw(-0.5, 0.0, index=1),
            raw(0.0, -0.375, index=9),
        )

        message = stage.review_panel(holes)[0].message

        assert "2 hole(s)" in message
        assert "0.250 mm" in message

    def test_reviewing_the_same_panel_twice_gives_the_same_answer(self):
        """No state accumulates across calls, in either direction.

        A quantiser that counted ties into itself would be order-dependent, and
        a second run over the same holes would disagree with the first. The
        empty review at the end is the half that a tie *counter* would fail: it
        must still be silent after two panels' worth of ties have gone past.
        """
        stage = SnapPositions(250_000)
        holes = snapped(stage, raw(0.125, 0.0, index=4))

        assert codes(stage.review_panel(holes)) == ["grid-ambiguous"]
        assert codes(stage.review_panel(holes)) == ["grid-ambiguous"]
        assert stage.review_panel(()) == ()


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
