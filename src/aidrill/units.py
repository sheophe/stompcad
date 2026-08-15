"""The unit boundary: one length, one representation, one rounding rule.

Every length inside `aidrill` is an exact integer number of nanometres. Points
arrive from the PDF and millimetres arrive from the operator's command line;
both cross into the model through this module and nowhere else, so a conversion
that is wrong is wrong in exactly one place.

**Nanometres, not microns.** The fractional drill standard settles it. A 64th of
an inch is 127/320 mm, which is 396.875 microns -- not a whole one -- and
396 875 nanometres exactly. 56 of the 64 fractional sizes are not whole microns,
so microns would round the answer set itself and reintroduce "is 396.875 the
same bit as 397?", which is the question a fixed unit exists to abolish. In
nanometres 25.4 mm is 25 400 000 and the 64 divides out.

**At this boundary, ties go away from zero.** Python's builtin ``round`` is
half-to-even: ``round(0.5)`` is 0 and ``round(2.5)`` is 2. A measurement is not
a statistic, and a rule that depends on the parity of the digit above it is one
nobody can predict at the bench. It is also not the rule the domain uses --
Hammond publish a 60.50 mm part as 61, where the builtin would say 60, so a
checker written with it sees one axis of one part disagree and reads bad data
rather than a rounding mode (``docs/parts/README.md``). Hence
``decimal.ROUND_HALF_UP``, spelled once here so ``nm_from_pt``, ``nm_from_mm``
and ``format_nm`` cannot drift apart.

**This is the boundary's rule and not the pipeline's.** ``SnapPositions`` ties
half-to-*even*, deliberately, and the two are not in competition because they
answer different questions. Here the question is which nanometre a measurement
*is*, and a measurement carries no meaning in its last digit's parity. There the
question is which grid point a hole should *move to*, where a consistent bias
walks a whole panel one way and half-to-even does not. Snapping additionally
warns when at least half the holes land on a tie, because a panel that ties that
often was drawn on a different grid than the one declared -- a signal this
boundary has no equivalent of. Do not "unify" the two rules; unifying them moves
every tied hole on every panel.

**``Decimal(str(mm))``, not ``Decimal(mm)``.** The second is exact about the
wrong thing: 0.05 is 0.05000000000000000277... in binary, and converting that
faithfully before quantising launders the float error into the integer instead
of ending it at the boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "NM_PER_MM",
    "nm_from_pt",
    "nm_from_mm",
    "mm_from_nm",
    "format_nm",
]

#: The whole point of the unit: a millimetre is a whole number of nanometres,
#: and so is every drill size, grid pitch and catalogue dimension in play.
NM_PER_MM: int = 1_000_000

#: An inch is 25.4 mm by definition, so it is exact in nanometres too, and PDF
#: user space is 1/72 inch. Kept as integers rather than the float ratio 72/25.4
#: so that the point conversion is one exact rational, rounded once at the end.
_NM_PER_INCH: int = 25_400_000
_PT_PER_INCH: int = 72

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, ties away from zero.

    The single site of the module's rounding rule: `nm_from_pt`, `nm_from_mm`
    and `format_nm` all tie-break the same way because they all come through
    here, rather than each spelling a mode that could drift apart.
    """
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def nm_from_pt(points: float) -> int:
    """Convert PDF user-space points to whole nanometres.

    The way in from the artwork. `geometry` fits Beziers in floating-point
    points because that maths is genuinely fractional; the result crosses into
    the model here, once, at construction -- converting earlier would round each
    of a circle's four anchors separately and compound the error.
    """
    return int(_round_half_up(Decimal(str(points)) * _NM_PER_INCH / _PT_PER_INCH))


def nm_from_mm(mm: float) -> int:
    """Convert millimetres to whole nanometres.

    The way in from the operator: ``--grid 0.25`` is millimetres because the
    KiCad grid is quoted in millimetres and that is what the operator thinks in.
    """
    return int(_round_half_up(Decimal(str(mm)) * NM_PER_MM))


def mm_from_nm(nm: int) -> float:
    """Convert whole nanometres back to millimetres, as a float.

    For the callers that genuinely want one -- drawing geometry scaled onto a
    sheet -- and not for printing, which goes through `format_nm` so that no
    length is ever rendered from a number the model does not hold.
    """
    return nm / NM_PER_MM


def format_nm(nm: int, decimals: int = 3) -> str:
    """Print a nanometre length as millimetres, normalising negative zero away.

    The way out. Arithmetic never happens in floating point on the way: the
    integer is scaled and quantised as a `Decimal`, so what is printed is a
    rendering of the stored value and not a second, slightly different one.

    Negative zero is normalised because only one of the printers used to do it:
    a hole at -0.0004 mm printed ``X0.000`` in the drill file and ``-0.00`` in
    the drawing's schedule -- two artifacts describing the same hole and
    disagreeing in print.
    """
    value = _round_half_up(Decimal(nm) / NM_PER_MM, Decimal(1).scaleb(-decimals))
    if value == 0:
        value = abs(value)
    return str(value)
