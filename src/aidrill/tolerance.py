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

__all__ = ["within"]


def within(a: int, b: int, tolerance: int) -> bool:
    """True when ``a`` and ``b`` are within ``tolerance``, boundary inclusive.

    Inclusive is the right default: a user who writes ``--grid-warn 0.05``
    means a hole that moved exactly 0.05 mm to stay quiet. A number an operator
    typed is a number they meant, and excluding its own boundary makes the flag
    mean something a hair tighter than it says.
    """
    return abs(a - b) <= tolerance
