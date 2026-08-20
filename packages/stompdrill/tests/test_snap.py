"""Tests for position snapping and midpoint review."""

from __future__ import annotations

import math
import random

import pytest

from stompdrill.pipeline import ReviewGridTies, SnapPositions
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.model import DrillData, Hole, RawHole, StageRun
from stompmodel.units import Millimetre, Nanometre


def raw(x: float, y: float, *, diameter: float = 7.0) -> RawHole:
    """One measured circle, keyword-only past position so ``diameter`` cannot
    be mistaken for another positional argument."""
    return RawHole(Millimetre(x), Millimetre(y), Millimetre(diameter))


def snapped(stage: SnapPositions, *measurements: RawHole) -> tuple[Hole, ...]:
    """The finished holes, assembled the way the quantisation phase assembles them."""
    holes = []
    for measurement in measurements:
        (x_nm, y_nm), _ = stage.quantise(measurement)
        holes.append(
            Hole(
                x_nm=x_nm,
                y_nm=y_nm,
                diameter_nm=Nanometre(7_000_000),
                raw=measurement,
            )
        )
    return tuple(holes)


def reviewed(stage: SnapPositions, *measurements: RawHole) -> tuple[Diagnostic, ...]:
    """What ``ReviewGridTies`` finds on a panel that ``stage`` snapped."""
    data = DrillData(holes=snapped(stage, *measurements)).with_processing(stage.describe())
    return ReviewGridTies().apply(data).diagnostics


def codes(diagnostics) -> list[str]:
    """The stable machine key of every finding, in order."""
    return [d.code for d in diagnostics]


class TestSnapPositions:
    def test_snaps_a_measurement_onto_the_grid(self):
        (x_nm, y_nm), diagnostics = SnapPositions(Nanometre(250_000)).quantise(
            raw(-39.99, 18.01)
        )
        assert (x_nm, y_nm) == (-40_000_000, 18_000_000)
        assert diagnostics == ()

    def test_a_hole_already_on_the_grid_neither_moves_nor_speaks(self):
        (x_nm, y_nm), diagnostics = SnapPositions(Nanometre(250_000)).quantise(
            raw(-40.0, 18.25)
        )
        assert (x_nm, y_nm) == (-40_000_000, 18_250_000)
        assert diagnostics == ()

    def test_every_position_is_a_member_of_the_answer_set(self):
        """Exact *by construction*, and checkable rather than asserted."""
        rng = random.Random(20250815)
        for grid_nm in (1_000, 50_000, 250_000, 300_000, 1_000_000):
            stage = SnapPositions(grid_nm)
            for index in range(1, 61):
                hole = raw(rng.uniform(-60, 60), rng.uniform(-30, 30))
                (x_nm, y_nm), _ = stage.quantise(hole)
                assert type(x_nm) is int, "x is a plain int"
                assert type(y_nm) is int, "y is a plain int"
                assert x_nm % grid_nm == 0, "x lands on the grid"
                assert y_nm % grid_nm == 0, "y lands on the grid"

    def test_the_measurement_is_never_rounded_before_it_is_compared(self):
        """0.1250004 mm is nearer 0.25 mm than zero.

        Neighbours on both sides and signs prevent an always-up rule from passing.
        """
        stage = SnapPositions(Nanometre(250_000))

        assert stage.quantise(raw(0.1250004, 0.0))[0][0] == 250_000
        assert stage.quantise(raw(0.1249996, 0.0))[0][0] == 0
        assert stage.quantise(raw(-0.1250004, 0.0))[0][0] == -250_000
        assert stage.quantise(raw(-0.1249996, 0.0))[0][0] == 0

    def test_a_genuine_midpoint_ties_half_to_even(self):
        """Grid midpoints tie half-to-even.

        0.125 and 0.375 mm resolve oppositely, excluding away-from-zero rounding.
        """
        stage = SnapPositions(Nanometre(250_000))

        assert stage.quantise(raw(0.125, 0.0))[0][0] == 0
        assert stage.quantise(raw(0.375, 0.0))[0][0] == 500_000
        assert stage.quantise(raw(-0.125, 0.0))[0][0] == 0
        assert stage.quantise(raw(-0.375, 0.0))[0][0] == -500_000

    def test_both_axes_are_snapped(self):
        """One axis snapped and the other carried over is a live mistake."""
        (x_nm, y_nm), _ = SnapPositions(Nanometre(500_000)).quantise(raw(-19.4, 3.1))
        assert (x_nm, y_nm) == (-19_500_000, 3_000_000)

    def test_a_small_move_does_not_warn(self):
        # default warn_over is grid / 4 == 62 500 nm; this hole moves 10 000
        _, diagnostics = SnapPositions(Nanometre(250_000)).quantise(raw(-39.99, 18.0))
        assert codes(diagnostics) == []

    def test_a_large_move_emits_an_off_grid_warning(self):
        (x_nm, y_nm), diagnostics = SnapPositions(Nanometre(250_000)).quantise(
            raw(-39.9, 18.0)
        )
        assert codes(diagnostics) == ["off-grid"]
        diag = diagnostics[0]
        assert diag.severity is Severity.WARNING
        assert diag.location_nm == (x_nm, y_nm) == (-40_000_000, 18_000_000)

    def test_an_explicit_threshold_overrides_the_default(self):
        hole = raw(-39.9, 18.0)
        assert codes(SnapPositions(Nanometre(250_000), warn_over_nm=Nanometre(200_000)).quantise(hole)[1]) == []
        assert codes(SnapPositions(Nanometre(250_000), warn_over_nm=Nanometre(50_000)).quantise(hole)[1]) == [
            "off-grid"
        ]

    def test_the_reported_distance_is_the_whole_move_and_not_one_axis(self):
        """Movement is the whole-integer Euclidean distance.

        A 3-4-5 offset makes either single-axis result distinct.
        """
        _, diagnostics = SnapPositions(Nanometre(1_000_000)).quantise(raw(0.3, -0.4))

        assert codes(diagnostics) == ["off-grid"]
        moved_nm = diagnostics[0].get("moved_nm")
        assert moved_nm == 500_000
        assert type(moved_nm) is int

    def test_the_warning_threshold_is_inclusive_at_its_own_boundary(self):
        """A 500 000 nm move is quiet at that bound and warns one nanometre below."""
        hole = raw(0.3, -0.4)
        assert codes(SnapPositions(Nanometre(1_000_000), warn_over_nm=Nanometre(500_000)).quantise(hole)[1]) == []
        assert codes(SnapPositions(Nanometre(1_000_000), warn_over_nm=Nanometre(499_999)).quantise(hole)[1]) == [
            "off-grid"
        ]

    def test_the_off_grid_diagnostic_names_the_place_it_moved_to(self):
        """The off-grid finding names the snapped place, not the hole's identity."""
        _, diagnostics = SnapPositions(Nanometre(250_000)).quantise(raw(-39.9, 18.0))

        diag = diagnostics[0]
        assert diag.location_nm == (-40_000_000, 18_000_000)
        assert diag.get("moved_nm") == 100_000
        assert diag.get("grid_nm") == 250_000

    def test_the_off_grid_message_says_where_and_by_how_much(self):
        """Both coordinates appear, and neither is left to be guessed at."""
        _, diagnostics = SnapPositions(Nanometre(250_000)).quantise(raw(-39.9, 18.0))
        message = diagnostics[0].message

        assert "hole 6" not in message
        assert "-39.9000" in message and "-40.0000" in message

    def test_an_off_grid_finding_names_a_place_not_a_number(self):
        """The number is assigned by a later stage, so it cannot be cited."""
        _, diagnostics = SnapPositions(Nanometre(250_000)).quantise(raw(-39.9, 18.0))
        diag = diagnostics[0]

        assert diag.get("hole_index") is None
        assert "hole 1" not in diag.message
        assert "-40.000" in diag.message and "18.000" in diag.message

    def test_regression_grid_half_moves_the_five_mm_row_a_quarter_millimetre(self):
        """At ``--grid 0.5``, the two ⌀5 holes go off-grid."""
        stage = SnapPositions(Nanometre(500_000))
        for index, x in ((5, -19.0), (2, 19.0)):
            (x_nm, y_nm), diagnostics = stage.quantise(raw(x, -18.75))
            assert codes(diagnostics) == ["off-grid"]
            assert diagnostics[0].get("moved_nm") == 250_000
            assert (x_nm, y_nm) == (round(x * 1_000_000), -19_000_000)

    def test_property_snapping_is_idempotent(self):
        """Feeding a snapped position back in must move nothing and say nothing."""
        rng = random.Random(20250814)
        for grid_nm in (50_000, 100_000, 250_000, 500_000, 1_000_000, 300_000):
            stage = SnapPositions(grid_nm)
            for index in range(1, 31):
                once, first = stage.quantise(
                    raw(rng.uniform(-60, 60), rng.uniform(-30, 30))
                )
                twice, second = stage.quantise(
                    raw(once[0] / 1_000_000, once[1] / 1_000_000)
                )
                assert twice == once
                assert codes(second) == [], "a snapped hole cannot still be off grid"
                assert len(first) <= 1


class TestSnapPositionsDescribesWhatItReallyDid:
    def test_describe_reports_the_grid_and_the_resolved_threshold(self):
        """``warn_over_nm`` is reported resolved, not as the ``None`` it was
        constructed with: a record of ``None`` tells a reader nothing about what
        happened to the data, and the drawing's title block reads this."""
        run = SnapPositions(Nanometre(250_000)).describe()

        assert run.name == "snap"
        assert run.parameters == (("grid_nm", 250_000), ("warn_over_nm", 62_500))

    def test_describe_reports_the_effective_grid_and_not_the_requested_one(self):
        """The sheet must never stamp a pitch the holes were not snapped to."""
        run = SnapPositions(Nanometre(500)).describe()

        assert run.parameters == (("grid_nm", 1_000), ("warn_over_nm", 250))


class TestTheGridIsAWholeNumberOfMicrons:
    """Below a micron the printed artefact stops being injective."""

    @pytest.mark.parametrize("grid_nm", [1_001, 1_500, 250_001])
    def test_a_grid_that_is_not_a_whole_micron_is_refused(self, grid_nm):
        with pytest.raises(ValueError, match="micron"):
            SnapPositions(grid_nm)

    @pytest.mark.parametrize("requested_nm", [500, 999, 1, 0, -250_000])
    def test_a_grid_below_a_micron_is_clamped_to_one(self, requested_nm):
        """Both bounds of the clamp, zero and a negative pitch included."""
        stage = SnapPositions(requested_nm)

        assert stage.grid_nm == 1_000
        assert codes(stage.diagnostics) == ["grid-too-fine"]
        assert stage.quantise(raw(0.0005004, 0.0))[0][0] == 1_000

    def test_the_clamp_warning_names_both_the_requested_pitch_and_the_used_one(self):
        """Naming only one of them leaves the operator unable to tell which."""
        stage = SnapPositions(Nanometre(500))
        diag = stage.diagnostics[0]

        assert diag.severity is Severity.WARNING
        assert diag.get("requested_grid_nm") == 500
        assert diag.get("grid_nm") == 1_000
        assert "0.000500" in diag.message and "0.001" in diag.message

    def test_a_grid_at_or_above_a_micron_raises_nothing(self):
        assert SnapPositions(Nanometre(1_000)).diagnostics == ()
        assert SnapPositions(Nanometre(250_000)).diagnostics == ()

    def test_the_clamp_is_reported_once_and_not_once_per_hole(self):
        """It is a finding about the configuration, not about a hole."""
        stage = SnapPositions(Nanometre(0))

        for index in (4, 1, 9):
            # Already on the clamped micron grid, so nothing else can speak.
            _, diagnostics = stage.quantise(raw(0.001 * index, 0.0))
            assert codes(diagnostics) == []
        assert codes(stage.diagnostics) == ["grid-too-fine"]


class TestSnapPositionsRefusesAGridThatIsNotAWholeNumber:
    """Pitch and warning threshold must be plain-integer nanometres."""

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
        """``--grid-warn=nan`` warns about every hole, including the still ones."""
        with pytest.raises(TypeError, match=r"^warn_over_nm"):
            SnapPositions(Nanometre(250_000), warn_over_nm=warn_over)

    def test_a_negative_warning_threshold_is_refused(self):
        """No hole can be inside it, so every hole is reported off-grid."""
        with pytest.raises(ValueError, match=r"^warn_over_nm"):
            SnapPositions(Nanometre(250_000), warn_over_nm=Nanometre(-100_000))

    def test_a_zero_warning_threshold_is_allowed(self):
        """"Tell me about every hole that moved at all" is a real request."""
        stage = SnapPositions(Nanometre(250_000), warn_over_nm=Nanometre(0))

        assert codes(stage.quantise(raw(0.0, 0.0))[1]) == []
        assert codes(stage.quantise(raw(0.01, 0.0))[1]) == ["off-grid"]


class TestReviewGridTies:
    """Report exact per-axis midpoints chosen by half-to-even."""

    @pytest.mark.parametrize(
        "x, y",
        [(0.125, 0.0), (-0.125, 0.0), (0.0, 0.375), (0.0, -0.375)],
    )
    def test_a_tie_counts_on_either_axis_and_at_either_sign(self, x, y):
        """Both axes and signs count, with opposing half-to-even outcomes."""
        assert codes(reviewed(SnapPositions(Nanometre(250_000)), raw(x, y))) == [
            "grid-ambiguous"
        ]

    def test_a_hole_tied_on_both_axes_counts_where_the_scalar_distance_would_not(self):
        """The most obvious way to draw on the wrong grid, and the one a Euclidean test
        fails hardest on.
        """
        stage = SnapPositions(Nanometre(250_000))
        measurement = raw(0.125, 0.125)

        assert stage.quantise(measurement)[1][0].get("moved_nm") == 176_776
        assert codes(reviewed(stage, measurement)) == ["grid-ambiguous"]

    def test_a_tie_on_one_axis_survives_an_ordinary_residual_on_the_other(self):
        """``or``, and never ``and``."""
        assert codes(reviewed(SnapPositions(Nanometre(250_000)), raw(0.125, 0.031))) == [
            "grid-ambiguous"
        ]

    def test_a_hole_already_on_a_grid_point_is_not_tied(self):
        """Residual zero, and ``2 * 0 == grid_nm`` is false for any real pitch."""
        stage = SnapPositions(Nanometre(250_000))

        assert reviewed(stage, raw(-0.25, 0.5), raw(0.75, -1.0)) == ()

    def test_one_tie_among_many_is_enough_and_none_stays_quiet(self):
        """A single tie is a hole placed by a rule rather than by the artwork."""
        stage = SnapPositions(Nanometre(250_000))
        one_tie = (
            raw(0.125, 0.0),
            raw(-1.0, 0.0),
            raw(2.0, 0.0),
            raw(3.0, 0.0),
        )

        assert codes(reviewed(stage, *one_tie)) == ["grid-ambiguous"]
        assert reviewed(stage, *one_tie[1:]) == ()

    def test_a_panel_with_no_holes_on_it_says_nothing(self):
        """No ties, nothing to say. A warning about a run with no circles in it
        is noise in front of an operator who has nothing to fix."""
        assert reviewed(SnapPositions(Nanometre(250_000))) == ()

    def test_the_finding_names_the_tied_places_and_not_their_identities(self):
        """Snapped at (0, 0) and (0, -500 000); the untied hole sits elsewhere."""
        stage = SnapPositions(Nanometre(250_000))

        (diag,) = reviewed(
            stage,
            raw(0.125, 0.0),
            raw(-0.5, 0.0),
            raw(0.0, -0.375),
        )

        assert diag.severity is Severity.WARNING
        assert diag.get("tied_indices") is None
        assert diag.get("tied_locations") == ((0, 0), (0, -500_000))
        # No denominator, deliberately: nothing decides by proportion, so a hole
        # count in the payload would be context rather than evidence.
        assert "hole_count" not in dict(diag.data)
        assert "tied_count" not in dict(diag.data)

    def test_the_finding_is_about_the_panel_and_names_no_representative_place(self):
        """A single ``location_nm`` is what a hole-level finding carries."""
        (diag,) = reviewed(SnapPositions(Nanometre(250_000)), raw(0.125, 0.0))

        # ``location_nm`` must be *absent* (``None``), not present and pointing
        # at one of several tied holes: a panel-wide finding has no single
        # representative place, so a consumer routing findings by location
        # must not read a stale or arbitrary one here.
        assert diag.location_nm is None
        assert "hole_index" not in dict(diag.data)

    def test_the_message_says_how_many_tied_and_which_pitch(self):
        """What the operator can act on is the grid they declared, so the
        sentence has to point there — the positions are not wrong, and a message
        about the holes would send them looking for a defect in the artwork."""
        stage = SnapPositions(Nanometre(250_000))

        (diag,) = reviewed(
            stage,
            raw(0.125, 0.0),
            raw(-0.5, 0.0),
            raw(0.0, -0.375),
        )

        assert "2 hole(s)" in diag.message
        assert "0.250 mm" in diag.message

    def test_reviewing_the_same_panel_twice_gives_the_same_answer(self):
        """No state accumulates across calls, in either direction."""
        stage = SnapPositions(Nanometre(250_000))
        tied = raw(0.125, 0.0)

        assert codes(reviewed(stage, tied)) == ["grid-ambiguous"]
        assert codes(reviewed(stage, tied)) == ["grid-ambiguous"]
        assert reviewed(stage) == ()

    def test_the_pitch_is_the_one_the_holes_were_snapped_to_and_not_a_default(self):
        """Tie review uses the recorded pitch.

        The same panel ties at 500 000 nm but not at 250 000 nm.
        """
        panel = (raw(0.25, 0.0), raw(-1.0, 0.0), raw(2.0, 0.0))

        assert codes(reviewed(SnapPositions(Nanometre(500_000)), *panel)) == ["grid-ambiguous"]
        assert reviewed(SnapPositions(Nanometre(250_000)), *panel) == ()

    def test_a_run_that_never_snapped_is_reviewed_against_no_pitch_at_all(self):
        """``last_run`` answers ``None``, and ``None`` is rendered, not defaulted."""
        stage = SnapPositions(Nanometre(500_000))
        prior = Diagnostic.info("prior", "something earlier said this")
        data = DrillData(
            holes=snapped(stage, raw(0.25, 0.0), raw(-1.0, 0.0)),
            diagnostics=(prior,),
        )

        assert ReviewGridTies().apply(data) is data

    def test_a_record_from_some_other_stage_is_not_a_pitch(self):
        """The pitch is looked up by name, and only ``snap`` has one to give."""
        stage = SnapPositions(Nanometre(500_000))
        data = DrillData(
            holes=snapped(stage, raw(0.25, 0.0))
        ).with_processing(StageRun("route", (("key", "default"),)))

        assert ReviewGridTies().apply(data).diagnostics == ()

    def test_the_stage_records_that_it_ran_without_restating_the_pitch(self):
        """A second copy of one number is two numbers as soon as either moves."""
        run = ReviewGridTies().describe()

        assert run.name == "review-grid-ties"
        assert run.parameters == ()


def test_a_tie_finding_lists_places_not_numbers():
    """A tie is reported by where it sits, not by a number a later stage assigns."""
    stage = SnapPositions(Nanometre(250_000))
    (diag,) = reviewed(stage, raw(0.125, 0.0))

    assert diag.get("tied_indices") is None
    assert diag.get("tied_locations") == ((0, 0),)


def test_the_stage_reports_a_distance_it_could_not_have_got_from_hypot():
    """``math.isqrt`` floors; ``math.hypot`` returns a float that is not it."""
    _, diagnostics = SnapPositions(Nanometre(1_000_000), warn_over_nm=Nanometre(100_000)).quantise(
        raw(0.1, 0.1)
    )

    moved_nm = diagnostics[0].get("moved_nm")
    assert moved_nm == 141_421
    assert moved_nm < math.hypot(100_000, 100_000)
