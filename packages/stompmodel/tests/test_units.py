"""The unit boundary: millimetres in, integer nanometres out."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from stompmodel.units import (
    NM_PER_MM,
    Nanometre,
    _check_nanometres,
    format_nm,
    mm_from_nm,
    nm_from_mm,
    scaled_nm,
)


class TestTheReturnIsAnInteger:
    """Conversion returns ``int``, not a numerically equal ``Decimal``."""

    def test_a_converted_millimetre_is_an_int(self) -> None:
        assert type(nm_from_mm(0.25)) is int


class TestExactness:
    def test_a_sixty_fourth_of_an_inch_is_exact(self) -> None:
        """The reason this module is nanometres and not microns."""
        assert nm_from_mm(25.4 / 64) == 396_875

    def test_the_metric_step_and_the_kicad_grid_are_exact(self) -> None:
        assert nm_from_mm(0.05) == 50_000
        assert nm_from_mm(0.25) == 250_000


class TestRounding:
    def test_rounding_is_half_up_not_bankers(self) -> None:
        """Conversion ties round away from zero, unlike Python's half-to-even."""
        assert nm_from_mm(0.0000005) == 1  # 0.5 nm rounds up
        assert nm_from_mm(0.0000015) == 2  # not 2 by luck: half-to-even also gives 2
        assert nm_from_mm(0.0000025) == 3  # half-to-even would give 2

    def test_a_negative_tie_goes_away_from_zero_too(self) -> None:
        """The rule is *away from zero*, which is two claims, and the positive
        half proves nothing about the negative one. A converter that is half-up
        above zero and half-to-even below it returns 0 here, and the panel's
        left-hand holes then round differently from its right-hand ones."""
        assert nm_from_mm(-0.0000005) == -1
        assert nm_from_mm(-0.0000025) == -3

    def test_printing_ties_the_same_way_as_converting(self) -> None:
        """Printing ties the same way as converting."""
        assert format_nm(Nanometre(2_500_000), decimals=0) == "3"
        assert format_nm(Nanometre(-2_500_000), decimals=0) == "-3"


class TestBackOut:
    def test_a_whole_nanometre_returns_to_the_millimetre_it_came_from(self) -> None:
        assert mm_from_nm(Nanometre(396_875)) == 0.396875
        assert mm_from_nm(Nanometre(-40_000_000)) == -40.0
        assert NM_PER_MM == 1_000_000

    def test_a_formatted_value_is_millimetres_at_the_asked_precision(self) -> None:
        """Nanometres are the model's unit; the operator still reads millimetres."""
        assert format_nm(Nanometre(-40_000_000)) == "-40.000"
        assert format_nm(Nanometre(5_159_375)) == "5.159"
        assert format_nm(Nanometre(5_159_375), decimals=4) == "5.1594"


class TestPrinting:
    def test_a_value_that_prints_as_zero_never_prints_as_minus_zero(self) -> None:
        """A negative value rounding to zero formats unsigned so artefacts agree."""
        assert format_nm(Nanometre(-400)) == "0.000"


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


class TestTheNanometreGuard:
    """What keeps a nominal length whole, checked where it is defined."""

    def test_a_float_is_not_a_length(self) -> None:
        """Rounding belongs at the unit boundary, so a float never reaches a
        nominal field: one that did would print a coordinate no drill can hit."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            _check_nanometres("Owner", x_nm=7_000_000.5)

    def test_a_bool_is_not_a_length(self) -> None:
        """``isinstance(True, int)`` is true, which is why the guard compares
        the type exactly. ``True`` would otherwise be a hole one nanometre out."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            _check_nanometres("Owner", x_nm=True)

    def test_the_refusal_names_the_owner_and_the_field(self) -> None:
        """One guard serves every value object, so the message is the only
        thing that says which field went wrong."""
        with pytest.raises(TypeError, match=r"Owner\.x_nm"):
            _check_nanometres("Owner", x_nm=7_000_000.5)

    def test_whole_nanometres_pass_including_zero_and_negatives(self) -> None:
        _check_nanometres("Owner", x_nm=7_000_000, y_nm=0, z_nm=-40_000_000)
