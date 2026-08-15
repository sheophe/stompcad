"""Tests for ``SnapPositions`` (SPEC §5, PLAN task B).

Split out of ``test_pipeline.py``, which had grown to 2160 lines covering six
stages with three agents about to work on it in parallel: one file per stage
gives each agent disjoint ownership instead of a merge conflict waiting to
happen. Diagnostics are still matched on ``code``, never on ``message`` --
``code`` is the stable machine API and the wording is not.
"""

from __future__ import annotations

import math
import random

import pytest

from aidrill.model import Severity
from aidrill.pipeline import Deduplicate, SnapPositions
from aidrill.protocols import Pipeline
from tests.conftest import at, codes, diameters, make_data, positions


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

    def test_the_off_grid_diagnostic_names_the_hole_it_moved(self):
        """The stage that moves coordinates is the worst one to leave anonymous.

        ``off-grid`` was the only hole-level diagnostic carrying no payload at
        all, so a consumer joining on ``hole_index`` — as ``duplicate-hole`` and
        ``unknown-diameter`` both invite it to — dropped every off-grid finding,
        and the drawing could not ring an off-grid hole because it had nothing
        to ring it by.

        The identity is deliberately neither array position nor anything derived
        from one: hole 6 is second in the tuple, and it is the only hole that
        moves.
        """
        data = make_data(at(-20.0, 18.0, index=2), at(-39.9, 18.0, index=6))

        out = SnapPositions(0.25).apply(data)

        assert codes(out) == ["off-grid"]
        diag = out.diagnostics[0]
        assert diag.get("hole_index") == 6
        assert diag.get("moved_mm") == pytest.approx(0.1)
        assert diag.get("grid_mm") == 0.25

    def test_the_off_grid_message_says_which_hole_and_which_moment(self):
        """Both coordinates appear, and neither is left to be guessed at.

        The message quotes where the hole was drawn; ``location`` is where it
        now is. That is one finding about two moments, and the only thing that
        makes it readable is saying so — with the hole's identity in front, so
        the sentence and the payload name the same hole.
        """
        out = SnapPositions(0.25).apply(make_data(at(-39.9, 18.0, index=6)))
        message = out.diagnostics[0].message

        assert "hole 6" in message
        assert "-39.9000" in message and "-40.0000" in message

    def test_two_coincident_off_grid_holes_each_get_their_own_warning(self):
        """Ruled deliberately: one warning per artwork circle, not per survivor.

        Snapping runs before deduplication, so two circles that collapse into
        one hole have already raised two ``off-grid`` warnings. Both are true
        statements about the artwork — there really are two circles off the grid
        and the operator will want to fix both in the source file — and this
        stage may not know that a later one will drop either of them (LSP), nor
        retract a diagnostic it has already written.

        What made the pair look like noise was that the two warnings were
        indistinguishable. They no longer are: each names its own hole, and
        ``duplicate-hole`` names the ones that went, so the join resolves and a
        consumer can tell an off-grid warning about a dropped hole from one
        about a hole in the drill file.
        """
        data = make_data(at(0.1, 0.1, 7.0, index=5), at(0.12, 0.09, 7.0, index=2))

        after = Pipeline([SnapPositions(0.25), Deduplicate()]).run(data)

        off_grid = [d for d in after.diagnostics if d.code == "off-grid"]
        duplicate = [d for d in after.diagnostics if d.code == "duplicate-hole"]
        assert [d.get("hole_index") for d in off_grid] == [5, 2]
        assert [hole.index for hole in after.holes] == [5]
        assert duplicate[0].get("dropped_indices") == "2"
        # The join the ruling turns on: the second warning is about a hole that
        # reaches no artifact, and a consumer can find that out.
        assert str(off_grid[1].get("hole_index")) in duplicate[0].get("dropped_indices")

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


class TestSnapPositionsRefusesAGridThatIsNotANumber:
    """K5: ``--grid=nan`` and ``--grid=inf`` both got past ``grid <= 0``.

    Every comparison against NaN is False, so the "disabled" gate let it through
    and ``round(x / nan)`` raised ``ValueError`` out of ``apply`` — uncaught, so
    the process exited **1**, the code reserved for "warnings present". A wrapper
    testing ``[ $? -le 1 ]`` read a crash as a clean run. ``inf`` did not even
    crash: ``round(x / inf) * inf`` is ``0 * inf``, so every hole snapped to
    ``nan`` and the artifact was written with ``XnanYnan`` in it.

    Checked once, in the constructor, on the ``DrillStandard.__post_init__``
    precedent, so a bad value is refused before any hole is looked at.
    """

    @pytest.mark.parametrize("grid", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_grid_is_refused_at_construction(self, grid):
        with pytest.raises(ValueError, match="grid"):
            SnapPositions(grid)

    @pytest.mark.parametrize("warn_over", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_warning_threshold_is_refused_too(self, warn_over):
        """``--grid-warn=nan`` warns about every hole, including the still ones.

        ``within(moved, 0.0, nan)`` is False whatever the hole did, so every
        hole on the panel — the ones that did not move at all included — is
        reported off-grid. That is the same defect as a negative threshold,
        wearing a different value.
        """
        with pytest.raises(ValueError, match="warn"):
            SnapPositions(0.25, warn_over=warn_over)

    def test_a_negative_warning_threshold_is_refused(self):
        with pytest.raises(ValueError, match="warn"):
            SnapPositions(0.25, warn_over=-0.1)

    def test_a_zero_warning_threshold_is_allowed(self):
        """"Tell me about every hole that moved at all" is a real request."""
        out = SnapPositions(0.25, warn_over=0.0).apply(
            make_data(at(0.0, 0.0, index=0), at(0.01, 0.0, index=1))
        )
        assert codes(out) == ["off-grid"]

    def test_a_non_positive_grid_is_still_how_the_stage_is_switched_off(self):
        """The finiteness rule must not take the documented disable with it."""
        data = make_data(at(-39.99, 18.01, index=0))
        for grid in (0.0, -0.25):
            out = SnapPositions(grid).apply(data)
            assert positions(out) == positions(data)
            assert codes(out) == []
