"""Branded length units and the conversions between them.

``Millimetre`` is what a measurement is; ``Nanometre`` is what a model holds.
Arithmetic drops the brand, so a scaled value is re-wrapped at the point it
becomes a length again. Millimetre conversions use ``Decimal(str(value))``
and half-up rounding. See ADR-0004.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import NewType

__all__ = [
    "Nanometre",
    "Millimetre",
    "NM_PER_MM",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]

#: The canonical model unit. Every nominal length is one of these.
Nanometre = NewType("Nanometre", int)

#: An unquantised measurement, as a source reports it.
Millimetre = NewType("Millimetre", float)

#: Whole nanometres in one millimetre.
NM_PER_MM: int = 1_000_000

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, with ties away from zero."""
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def nm_from_mm(mm: float) -> Nanometre:
    """Convert millimetres to whole nanometres, with ties away from zero."""
    return Nanometre(int(_round_half_up(Decimal(str(mm)) * NM_PER_MM)))


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
