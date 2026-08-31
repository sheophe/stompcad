"""The unit concerns that are stompdrill's own."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from stompdrill.units import scaled_nm
from stompmodel.units import nm_from_mm


def test_scaled_nm_lives_in_stompdrill_not_the_leaf() -> None:
    """ADR-0009's Micron test: a statement of this package's quantisation
    policy stays here, however unit-adjacent it looks."""
    import stompmodel.units
    from stompdrill.units import scaled_nm

    assert scaled_nm(1.5) == Decimal("1500000")
    assert not hasattr(stompmodel.units, "scaled_nm")


def test_scaled_nm_scales_exactly_not_through_binary_float() -> None:
    """0.1 mm has no exact binary representation; the Decimal path must not
    inherit its error, which is the whole reason this helper exists."""
    from stompdrill.units import scaled_nm

    assert scaled_nm(0.1) == Decimal("100000")


def _nearest_multiple_of(quantity: Decimal, pitch_nm: int) -> int:
    """Round ``quantity`` (a nanometre count, possibly fractional) onto the
    nearest whole multiple of ``pitch_nm``, ties half-to-even -- the tie rule
    a grid quantiser uses, per `SnapPositions`. Shared by both helpers below
    so the only difference between them is *what* they round: the exact
    scaled measurement, or a copy already rounded to a nanometre."""
    steps = (quantity / pitch_nm).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    return int(steps) * pitch_nm


def _nearest_multiple_exact(mm: float, pitch_nm: int) -> int:
    """What a quantiser gets right: compare the measurement, never rounded,
    against the answer set, and round only the quotient."""
    return _nearest_multiple_of(scaled_nm(mm), pitch_nm)


def _nearest_multiple_via_pre_rounded_nm(mm: float, pitch_nm: int) -> int:
    """Pre-round to nanometres before comparison, manufacturing possible ties."""
    return _nearest_multiple_of(Decimal(nm_from_mm(mm)), pitch_nm)


class TestScaledNm:
    """Scale measurements exactly before comparing them with answer sets."""

    def test_it_returns_the_exact_scaled_value_unrounded(self) -> None:
        assert scaled_nm(0.1250004) == Decimal("125000.4")
        assert type(scaled_nm(0.1250004)) is Decimal

    def test_a_position_that_pre_rounding_would_manufacture_a_tie_for(self) -> None:
        """0.1250004 mm is 125 000.4 nm exactly, nearer 250 000 than 0 on a
        250 000 nm grid. `nm_from_mm` first gives the exact tie 125 000, which
        half-to-even resolves to 0 -- the two spellings of one measurement
        emit ``X0.250`` and ``X0.000``."""
        assert _nearest_multiple_exact(0.1250004, 250_000) == 250_000
        assert _nearest_multiple_via_pre_rounded_nm(0.1250004, 250_000) == 0

    def test_a_diameter_that_pre_rounding_would_manufacture_a_tie_for(self) -> None:
        """5.0250004 mm is nearer the 5 050 000 nm table entry, but the
        nm-rounded copy sits dead centre on 5 025 000 and the tie-break picks
        5 000 000."""
        assert _nearest_multiple_exact(5.0250004, 50_000) == 5_050_000
        assert _nearest_multiple_via_pre_rounded_nm(5.0250004, 50_000) == 5_000_000
