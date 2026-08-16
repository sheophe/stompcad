"""Branded length units and the conversions between them.

``Millimetre`` is what a source measures; ``Nanometre`` is what the model holds;
``Micron`` is the grid pitch and nothing else. Arithmetic drops the brand, so a
scaled value must be re-wrapped at the point it becomes a length again.
Millimetre conversions use ``Decimal(str(value))`` and half-up rounding. See
ADR-0004.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NewType

__all__ = [
    "Nanometre",
    "Micron",
    "Millimetre",
    "NM_PER_MM",
    "NM_PER_MICRON",
    "nm_from_micron",
    "micron_from_mm",
    "mm_from_pt",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]

#: The canonical model unit. Every nominal length is one of these.
Nanometre = NewType("Nanometre", int)

#: The grid pitch, which is a whole number of microns and never finer.
Micron = NewType("Micron", int)

#: An unquantised measurement, as a source reports it.
Millimetre = NewType("Millimetre", float)

#: Whole nanometres in one millimetre.
NM_PER_MM: int = 1_000_000

#: Whole nanometres in one micron.
NM_PER_MICRON: int = 1_000

#: PDF user space is 1/72 inch; one inch is exactly 25.4 millimetres.
_MM_PER_INCH: float = 25.4
_PT_PER_INCH: int = 72

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, with ties away from zero."""
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def mm_from_pt(points: float) -> Millimetre:
    """Convert PDF user-space points to an unquantised millimetre measurement."""
    return Millimetre(points * _MM_PER_INCH / _PT_PER_INCH)


def nm_from_mm(mm: float) -> Nanometre:
    """Convert millimetres to whole nanometres, with ties away from zero."""
    return Nanometre(int(_round_half_up(Decimal(str(mm)) * NM_PER_MM)))


def micron_from_mm(mm: float) -> Micron:
    """Convert millimetres to whole microns, with ties away from zero."""
    return Micron(int(_round_half_up(Decimal(str(mm)) * NM_PER_MM / NM_PER_MICRON)))


def nm_from_micron(microns: Micron) -> Nanometre:
    """Widen a grid pitch to the canonical unit."""
    return Nanometre(microns * NM_PER_MICRON)


def scaled_nm(mm: float) -> Decimal:
    """Scale a measurement exactly without selecting a nanometre.

    Quantisers compare this value directly with their answer sets so a
    preliminary rounding cannot manufacture a midpoint tie. See ADR-0003.
    """
    return Decimal(str(mm)) * NM_PER_MM


def mm_from_nm(nm: Nanometre) -> Millimetre:
    """Convert whole nanometres to a millimetre value."""
    return Millimetre(nm / NM_PER_MM)


def format_nm(nm: Nanometre, decimals: int = 3) -> str:
    """Format whole nanometres as millimetres, normalising negative zero."""
    value = _round_half_up(Decimal(nm) / NM_PER_MM, Decimal(1).scaleb(-decimals))
    if value == 0:
        value = abs(value)
    return str(value)
