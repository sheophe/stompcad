"""The unit concerns that are stompdrill's own.

``Micron`` is the grid pitch and nothing else — a statement about this
package's quantisation policy, not about length, which is why it did not
travel to ``stompmodel`` with the lengths. ``mm_from_pt`` converts PDF user
space and belongs beside the parser that reads it. See ADR-0009.
"""

from __future__ import annotations

from typing import NewType

from stompmodel.units import Millimetre, Nanometre

__all__ = [
    "Micron",
    "NM_PER_MICRON",
    "mm_from_pt",
    "nm_from_micron",
]

#: The grid pitch, which is a whole number of microns and never finer.
Micron = NewType("Micron", int)

#: Whole nanometres in one micron.
NM_PER_MICRON: int = 1_000

#: PDF user space is 1/72 inch; one inch is exactly 25.4 millimetres.
_MM_PER_INCH: float = 25.4
_PT_PER_INCH: int = 72


def mm_from_pt(points: float) -> Millimetre:
    """Convert PDF user-space points to an unquantised millimetre measurement."""
    return Millimetre(points * _MM_PER_INCH / _PT_PER_INCH)


def nm_from_micron(microns: Micron) -> Nanometre:
    """Widen a grid pitch to the canonical unit."""
    return Nanometre(microns * NM_PER_MICRON)
