"""Branded length units, the conversions between them, and the guards that keep a length whole.

``Millimetre`` is what a measurement is; ``Nanometre`` is what a model holds.
Arithmetic drops the brand, so a scaled value is re-wrapped at the point it
becomes a length again. Millimetre conversions use ``Decimal(str(value))``
and half-up rounding. The guards refuse the other unit outright, because a
length that crossed no boundary is the defect they exist to catch. See
ADR-0004.
"""

from __future__ import annotations

import math
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
    "check_millimetres",
    "check_nanometres",
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
    """Convert millimetres to whole nanometres, with ties away from zero.

    Precondition: a physically bounded panel length. Around 1e22 mm the exact
    decimal scaling exceeds the context's precision and raises
    ``decimal.InvalidOperation``. Unguarded on purpose: a bound invented here
    would be one more number to argue about than the physics already fixes.
    """
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


def check_nanometres(owner: str, **lengths: object) -> None:
    """Refuse anything but a plain ``int`` for a length.

    Exact type checks reject booleans as well as floats; conversion and rounding
    belong at the unit boundary. Public for the same reason
    ``check_millimetres`` is: several `stompdrill` quantisers and stages apply
    this guard outside the model, and a shared rule renamed private would break
    every one of those callers with no ``__all__``, ruff or mypy saying so.
    """
    for name, value in lengths.items():
        if type(value) is not int:
            raise TypeError(
                f"{owner}.{name} must be a whole number of nanometres, not {value!r}"
            )


def check_millimetres(owner: str, **lengths: object) -> None:
    """Refuse anything but a finite ``float`` for a measurement.

    Exact type checks reject integers and booleans; ``math.isfinite`` rejects
    infinities and NaNs before they can invalidate comparisons. Public because
    ``stompdrill``'s pre-canonical ``RawDrillData`` is this guard applied
    outside the model, and a shared guard renamed under a private name would
    break that caller with no ``__all__``, ruff or mypy saying so.
    """
    for name, value in lengths.items():
        if type(value) is not float or not math.isfinite(value):
            raise TypeError(
                f"{owner}.{name} must be a finite number of millimetres, not {value!r}"
            )
