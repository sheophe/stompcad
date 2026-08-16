"""Convert lengths at the boundary of the whole-nanometre model.

Millimetre conversions use ``Decimal(str(value))`` and half-up rounding. Exact
scaled measurements remain decimal until a quantiser selects an answer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "NM_PER_MM",
    "mm_from_pt",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]

#: Whole nanometres in one millimetre.
NM_PER_MM: int = 1_000_000

#: PDF user space is 1/72 inch; one inch is exactly 25.4 millimetres.
_MM_PER_INCH: float = 25.4
_PT_PER_INCH: int = 72

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, with ties away from zero."""
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def mm_from_pt(points: float) -> float:
    """Convert PDF user-space points to unquantised millimetres."""
    return points * _MM_PER_INCH / _PT_PER_INCH


def nm_from_mm(mm: float) -> int:
    """Convert millimetres to whole nanometres, with ties away from zero."""
    return int(_round_half_up(Decimal(str(mm)) * NM_PER_MM))


def scaled_nm(mm: float) -> Decimal:
    """Scale a measurement exactly without selecting a nanometre.

    Quantisers compare this value directly with their answer sets so a
    preliminary rounding cannot manufacture a midpoint tie. See ADR-0003.
    """
    return Decimal(str(mm)) * NM_PER_MM


def mm_from_nm(nm: int) -> float:
    """Convert whole nanometres to millimetres as a float."""
    return nm / NM_PER_MM


def format_nm(nm: int, decimals: int = 3) -> str:
    """Format whole nanometres as millimetres, normalising negative zero."""
    value = _round_half_up(Decimal(nm) / NM_PER_MM, Decimal(1).scaleb(-decimals))
    if value == 0:
        value = abs(value)
    return str(value)
