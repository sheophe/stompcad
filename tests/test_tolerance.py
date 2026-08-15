"""Tests for :mod:`aidrill.tolerance` — the boundary, which is all it decides.

``within`` is one line, and every one of its characters is a decision someone
downstream reads as a promise. Two of them are pinned here:

* **The boundary is inclusive.** An operator who writes ``--grid-warn 0.05``
  means a hole that moved exactly 0.05 mm to stay quiet, and ``<`` would make
  the flag mean something a hair tighter than it says. This went unpinned for a
  long time: mutating ``<=`` to ``<`` left the whole suite green, because every
  fixture sat comfortably inside or outside its tolerance and none of them sat
  *on* it. So the tests below use distances that are exactly the tolerance, and
  exactly one nanometre either side of it.
* **The comparison is exact.** Lengths are whole nanometres, so there is no
  representation error for an epsilon to absorb, and a ``within`` that widened
  every tolerance by even a nanometre would answer a question nobody asked. A
  zero tolerance therefore means equality and nothing else.
"""

from __future__ import annotations

from aidrill.tolerance import ROW_SLACK_NM, within

# One micron, in nanometres. Named here rather than reused from the module so
# that a test of the boundary cannot be satisfied by whatever the module happens
# to say the boundary is.
_MICRON = 1_000


def test_a_distance_exactly_on_the_tolerance_is_within_it():
    """The inclusive boundary, which is the only thing ``within`` decides.

    A number an operator typed is a number they meant. This is the test that
    dies for ``<``.
    """
    assert within(18_001_000, 18_000_000, _MICRON) is True


def test_a_distance_one_nanometre_over_the_tolerance_is_not_within_it():
    """The other side of the same boundary, one nanometre out.

    Without it the inclusive test above is satisfied by a ``within`` that
    returns ``True`` for everything.
    """
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


def test_the_row_slack_is_one_nanometre():
    """One unit of the model's own quantum, and no wider.

    A Y comes off the artwork through a rotation and a frame translation, so two
    holes the designer drew on one line can land a nanometre apart; that is the
    whole of what this bucket exists to absorb. Every wider value is a distance
    an artifact prints. One micron is the case to hold in mind: an Excellon file
    at three decimal places writes 18.000 and 18.001 for two holes a micron
    apart, so a micron-wide bucket would have the drawing dimension one row
    where the machine drills two — the cross-artifact disagreement the whole
    pipeline is arranged to prevent.
    """
    assert ROW_SLACK_NM == 1
    assert type(ROW_SLACK_NM) is int
