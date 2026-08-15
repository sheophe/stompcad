"""The unit boundary: points and millimetres in, integer nanometres out."""

from __future__ import annotations

from aidrill.units import NM_PER_MM, format_nm, mm_from_nm, nm_from_mm, nm_from_pt


class TestTheReturnIsAnInteger:
    """``int``, not merely something equal to one.

    Numeric equality cannot see this: ``Decimal("250000") == 250000`` is True, so
    dropping the ``int()`` from both converters left every other test in this file
    green while the module's whole contract -- *integer* nanometres -- had gone.
    Task 2's model guards are ``type(x) is int`` precisely so a ``Decimal`` cannot
    reach a coordinate; these two assertions are what stop one being handed over.
    """

    def test_a_converted_millimetre_is_an_int(self) -> None:
        assert type(nm_from_mm(0.25)) is int

    def test_a_converted_point_is_an_int(self) -> None:
        assert type(nm_from_pt(72.0)) is int


class TestExactness:
    def test_a_sixty_fourth_of_an_inch_is_exact(self) -> None:
        """The reason this module is nanometres and not microns."""
        assert nm_from_mm(25.4 / 64) == 396_875

    def test_the_metric_step_and_the_kicad_grid_are_exact(self) -> None:
        assert nm_from_mm(0.05) == 50_000
        assert nm_from_mm(0.25) == 250_000

    def test_a_point_converts_through_one_rule(self) -> None:
        assert nm_from_pt(72.0) == 25_400_000  # 72 pt is one inch


class TestRounding:
    def test_rounding_is_half_up_not_bankers(self) -> None:
        """Python's round() is half-to-even: round(0.5) is 0 and round(1.5) is 2.

        A length is not a statistic, and a rule that depends on the parity of the
        digit above it is one nobody can predict at the bench.

        The last case is a tie arriving the other way in, and pins the second
        half of the rule with it: a content stream states ``50.00094``, which is
        17 639 220.5 nm, and the nearest double is a hair *under* that. Rounding
        the decimal the file states gives 221; rounding the float's exact binary
        value -- ``Decimal(points)`` rather than ``Decimal(str(points))`` --
        gives 220, having decided the tie on an error the artwork never had.
        """
        assert nm_from_mm(0.0000005) == 1  # 0.5 nm rounds up
        assert nm_from_mm(0.0000015) == 2  # not 2 by luck: half-to-even also gives 2
        assert nm_from_mm(0.0000025) == 3  # half-to-even would give 2
        assert nm_from_pt(50.00094) == 17_639_221  # the same rule, on the way in from a PDF

    def test_a_negative_tie_goes_away_from_zero_too(self) -> None:
        """The rule is *away from zero*, which is two claims, and the positive
        half proves nothing about the negative one. A converter that is half-up
        above zero and half-to-even below it returns 0 here, and the panel's
        left-hand holes then round differently from its right-hand ones."""
        assert nm_from_mm(-0.0000005) == -1
        assert nm_from_mm(-0.0000025) == -3

    def test_printing_ties_the_same_way_as_converting(self) -> None:
        """``format_nm`` shares ``_round_half_up``, and this is what says so.
        The model holds 2 500 000, and the printed value has to be the nearest
        millimetre *by the rule that built it*. A formatter tying to even would
        print ``2`` -- and, since ``format_nm`` is the shared output boundary,
        print it everywhere at once, so no artifact contradicts another. That is
        the harm: the number on the page was reached by arithmetic the stored
        value never went through, and nothing downstream can notice."""
        assert format_nm(2_500_000, decimals=0) == "3"
        assert format_nm(-2_500_000, decimals=0) == "-3"


class TestBackOut:
    def test_a_whole_nanometre_returns_to_the_millimetre_it_came_from(self) -> None:
        assert mm_from_nm(396_875) == 0.396875
        assert mm_from_nm(-40_000_000) == -40.0
        assert NM_PER_MM == 1_000_000

    def test_a_formatted_value_is_millimetres_at_the_asked_precision(self) -> None:
        """Nanometres are the model's unit; the operator still reads millimetres."""
        assert format_nm(-40_000_000) == "-40.000"
        assert format_nm(5_159_375) == "5.159"
        assert format_nm(5_159_375, decimals=4) == "5.1594"


class TestPrinting:
    def test_a_value_that_prints_as_zero_never_prints_as_minus_zero(self) -> None:
        """A hole at -400 nm printed ``X0.000`` in the drill file and ``-0.00``
        in the drawing's schedule: two artifacts describing the same hole and
        disagreeing in print."""
        assert format_nm(-400) == "0.000"
