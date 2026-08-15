"""One place for float comparison.

Five modules were independently declaring their own ``_SLACK = 1e-9`` with
near-identical comments, and a sixth (``CheckReferenceSize``) had none at all
and therefore rejected a value the user had typed exactly: with a 0.1 tolerance,
``60.1 - 60.0 == 0.10000000000000142``. Boundary behaviour is a decision, and a
decision made in six places is six decisions.
"""

from __future__ import annotations

__all__ = ["SLACK", "within", "ROW_SLACK"]

#: Absorbs binary-representation error in user-supplied millimetre values.
#: Chosen well below any physically meaningful dimension.
SLACK: float = 1e-9

#: Bucketing tolerance for "these holes are on the same row".
ROW_SLACK: float = 1e-6


def within(a: float, b: float, tolerance: float) -> bool:
    """True when ``a`` and ``b`` are within ``tolerance``, boundary inclusive.

    Inclusive is the right default: a user who writes ``--grid-warn 0.05``
    means a hole that moved exactly 0.05 mm to stay quiet. A number an operator
    typed is a number they meant, and excluding its own boundary makes the flag
    mean something a hair tighter than it says.
    """
    return abs(a - b) <= tolerance + SLACK
