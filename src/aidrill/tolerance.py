"""One place for "are these two lengths the same length?".

The body is a single comparison, and it has a module to itself because the
``<=`` in it is a decision rather than a spelling. Six call sites asking the
question their own way are six decisions, and the sixth is the one that excludes
a number the operator typed: ``--grid-warn 0.05`` on a hole that moved exactly
0.05 mm has one right answer, and it should not depend on which module is
asking.

Lengths are whole nanometres (``aidrill.units``), so the comparison is exact.
There is no representation error left for an epsilon to absorb, and a ``within``
that widened every tolerance by even a nanometre would answer a question nobody
asked — a small lie of exactly the kind an integer model exists to remove. The
boundary is therefore the only thing this module decides, which is why there is
a test sitting on it, one nanometre inside it and one nanometre outside it.
"""

from __future__ import annotations

__all__ = ["within", "ROW_SLACK_NM"]

#: Bucketing tolerance for "these holes are on the same row": one nanometre,
#: the model's own quantum and the narrowest slack there is. It absorbs the
#: nanometre two holes drawn on one line can differ by after a rotation and a
#: frame translation, and nothing else — every wider value is a distance an
#: artifact prints. A micron is the case worth naming rather than assuming: an
#: Excellon file at three decimal places writes 18.000 and 18.001 for two holes
#: a micron apart, so a micron-wide bucket would have the drawing dimension one
#: row where the machine drills two.
ROW_SLACK_NM: int = 1


def within(a: int, b: int, tolerance: int) -> bool:
    """True when ``a`` and ``b`` are within ``tolerance``, boundary inclusive.

    Inclusive is the right default: a user who writes ``--grid-warn 0.05``
    means a hole that moved exactly 0.05 mm to stay quiet. A number an operator
    typed is a number they meant, and excluding its own boundary makes the flag
    mean something a hair tighter than it says.
    """
    return abs(a - b) <= tolerance
