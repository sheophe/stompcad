"""Tests for exact inclusive integer tolerances."""

from __future__ import annotations

from aidrill.tolerance import within

# One micron, in nanometres. Named here rather than reused from the module so
# that a test of the boundary cannot be satisfied by whatever the module happens
# to say the boundary is.
_MICRON = 1_000


def test_a_distance_exactly_on_the_tolerance_is_within_it():
    """A distance exactly one micron from the target is within the boundary."""
    assert within(18_001_000, 18_000_000, _MICRON) is True


def test_a_distance_one_nanometre_over_the_tolerance_is_not_within_it():
    """A distance one nanometre beyond the inclusive boundary is outside."""
    assert within(18_001_001, 18_000_000, _MICRON) is False


def test_the_boundary_is_inclusive_in_both_directions():
    """``a`` below ``b`` as well as above it — ``abs`` is a claim too."""
    assert within(17_999_000, 18_000_000, _MICRON) is True
    assert within(17_998_999, 18_000_000, _MICRON) is False


def test_a_zero_tolerance_asks_for_equality_and_gets_it():
    """No epsilon. Between two integers there is no binary error to absorb, so
    a slack quietly added here would be a widening of every comparison in the
    pipeline that nobody asked for — including this one, where a nanometre
    apart would come back as the same length."""
    assert within(7_000_000, 7_000_000, 0) is True
    assert within(7_000_001, 7_000_000, 0) is False
