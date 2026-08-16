"""The unit boundary: one length, one representation, one rounding rule.

Every quantised length inside `aidrill` is an exact integer number of
nanometres. Points arrive from the PDF and millimetres arrive from the
operator's command line; every change of unit happens through this module and
nowhere else, so a conversion that is wrong is wrong in exactly one place.

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
``decimal.ROUND_HALF_UP``, spelled once here so ``nm_from_mm`` and ``format_nm``
cannot drift apart.

**This is the boundary's rule and not the pipeline's.** ``SnapPositions`` ties
half-to-*even*, deliberately, and the two are not in competition because they
answer different questions. Here the question is which nanometre a measurement
*is*, and a measurement carries no meaning in its last digit's parity. There the
question is which grid point a hole should *move to*, where a consistent bias
walks a whole panel one way and half-to-even does not. A tie there is also
reportable -- ``ReviewGridTies`` names any hole a parity rule placed, because a
panel that ties at all may have been drawn on a different grid than the one
declared -- where a tie here is simply resolved and never mentioned, there being
nothing about a measurement for an operator to reconsider. Do not "unify" the
two rules; unifying them moves every tied hole on every panel.

**``Decimal(str(mm))``, not ``Decimal(mm)``.** The second is exact about the
wrong thing: 0.05 is 0.05000000000000000277... in binary, and converting that
faithfully before quantising launders the float error into the integer instead
of ending it at the boundary.
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

#: The whole point of the unit: a millimetre is a whole number of nanometres,
#: and so is every drill size, grid pitch and catalogue dimension in play.
NM_PER_MM: int = 1_000_000

#: An inch is 25.4 mm by definition, and PDF user space is 1/72 inch. Kept as
#: the two factors rather than folded into the ratio 25.4/72, so the conversion
#: below reads as the definition it is.
_MM_PER_INCH: float = 25.4
_PT_PER_INCH: int = 72

_WHOLE = Decimal(1)


def _round_half_up(value: Decimal, exponent: Decimal = _WHOLE) -> Decimal:
    """Quantise ``value`` onto ``exponent``, ties away from zero.

    The single site of the module's rounding rule: `nm_from_mm` and `format_nm`
    tie-break the same way because they both come through here, rather than each
    spelling a mode that could drift apart.
    """
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def mm_from_pt(points: float) -> float:
    """Convert PDF user-space points to millimetres.

    The way in from the artwork, and a change of unit rather than a change of
    representation: 72 pt is an inch by definition, so this is the same length
    written differently and there is nothing here to decide. Hence a float, and
    hence no visit to the rounding rule above.

    Quantising here instead would be a rounding the artwork never asked for,
    placed before the phase that knows what a length has to land on -- a drill
    size, a grid pitch, a catalogue footprint. Two roundings in series, and the
    order of the two would matter.
    """
    return points * _MM_PER_INCH / _PT_PER_INCH


def nm_from_mm(mm: float) -> int:
    """Convert millimetres to whole nanometres.

    The way in from the operator: ``--grid 0.25`` is millimetres because the
    KiCad grid is quoted in millimetres and that is what the operator thinks in.
    """
    return int(_round_half_up(Decimal(str(mm)) * NM_PER_MM))


def scaled_nm(mm: float) -> Decimal:
    """The measurement in nanometres, exactly, without quantising it.

    A quantiser that rounds the measurement to whole nanometres *before*
    choosing which grid point or drill size is nearest can choose wrongly by a
    full grid pitch. ``0.1250004`` mm is 125 000.4 nm exactly; its nearest
    point on a 250 000 nm grid is 250 000. But `nm_from_mm` first gives
    125 000, which is an exact tie, and half-even then picks 0 -- the two
    spellings of the same measurement emit ``X0.250`` and ``X0.000``.
    Diameters fail the same way: 5.0250004 mm is nearer the 5 050 000 nm table
    entry, but the rounded copy sits dead centre on 5 025 000 and the
    tie-break picks 5 000 000.

    The mechanism is not that the pre-rounding is too coarse -- half a
    nanometre is 250 000x finer than the grid -- it *manufactures a tie the
    measurement did not have*, and the tie-break then resolves a fabricated
    ambiguity instead of the real one. `scaled_nm` exists so a quantiser can
    compare the measurement against an answer set without ever quantising the
    measurement itself; only the quotient against that answer set gets
    rounded.

    ``Decimal(str(mm))`` and not ``Decimal(mm)``: ``str`` of a float is its
    shortest round-tripping decimal, which is the same basis `nm_from_mm`
    already uses, and it avoids preserving irrelevant binary-expansion digits.
    """
    return Decimal(str(mm)) * NM_PER_MM


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
