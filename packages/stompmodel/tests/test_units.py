"""The unit boundary: millimetres in, integer nanometres out."""

from __future__ import annotations

import decimal
from decimal import Decimal

import pytest

from stompmodel import units
from stompmodel.units import (
    NM_PER_MM,
    Nanometre,
    check_millimetres,
    check_nanometres,
    format_nm,
    mm_from_nm,
    nm_from_mm,
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


class TestTheNanometreGuard:
    """What keeps a nominal length whole, checked where it is defined."""

    def test_the_nanometre_guard_is_exported(self) -> None:
        """``stompdrill`` applies this guard from several places outside the
        model, the same reason ``check_millimetres`` is public; a shared rule
        renamed private would break every one of those callers with nothing
        saying so."""
        assert "check_nanometres" in units.__all__

    def test_a_float_is_not_a_length(self) -> None:
        """Rounding belongs at the unit boundary, so a float never reaches a
        nominal field: one that did would print a coordinate no drill can hit."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            check_nanometres("Owner", x_nm=7_000_000.5)

    def test_a_bool_is_not_a_length(self) -> None:
        """``isinstance(True, int)`` is true, which is why the guard compares
        the type exactly. ``True`` would otherwise be a hole one nanometre out."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            check_nanometres("Owner", x_nm=True)

    def test_a_str_is_not_a_length(self) -> None:
        """A digit string is not the integer it looks like."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            check_nanometres("Owner", x_nm="7000000")

    def test_a_decimal_is_not_a_length(self) -> None:
        """``Decimal`` is the model's own scaling type, and still not an
        ``int``: a canonical length has already crossed the unit boundary."""
        with pytest.raises(TypeError, match="whole number of nanometres"):
            check_nanometres("Owner", x_nm=Decimal(7_000_000))

    def test_the_refusal_names_the_owner_and_the_field(self) -> None:
        """One guard serves every value object, so the message is the only
        thing that says which field went wrong."""
        with pytest.raises(TypeError, match=r"Owner\.x_nm"):
            check_nanometres("Owner", x_nm=7_000_000.5)

    def test_whole_nanometres_pass_including_zero_and_negatives(self) -> None:
        check_nanometres("Owner", x_nm=7_000_000, y_nm=0, z_nm=-40_000_000)


class TestTheMillimetreGuardIsPartOfTheSharedSurface:
    """``stompdrill``'s ``RawDrillData`` applies this guard from outside.

    A cross-package caller of a private name is a contract nothing records,
    so the export is the contract.
    """

    def test_the_millimetre_guard_is_exported(self) -> None:
        assert "check_millimetres" in units.__all__

    def test_an_int_is_not_a_measurement(self) -> None:
        """A source reports floats; an int here is a value that skipped one."""
        with pytest.raises(TypeError, match="finite number of millimetres"):
            check_millimetres("Owner", x=7)

    def test_an_infinity_is_not_a_measurement(self) -> None:
        with pytest.raises(TypeError, match="finite number of millimetres"):
            check_millimetres("Owner", x=float("inf"))

    def test_finite_floats_pass(self) -> None:
        check_millimetres("Owner", x=7.0, y=0.0, z=-40.5)


def test_a_length_no_panel_could_have_raises_rather_than_rounding():
    """The documented precondition, made falsifiable.

    Guarding this is declined on purpose: a panel is physically bounded, and a
    limit invented here would be a number to argue about. The test fails if
    someone adds one, or turns the refusal into a silent answer.
    """
    assert nm_from_mm(1e21) == 10**27

    with pytest.raises(decimal.InvalidOperation):
        nm_from_mm(1e22)
