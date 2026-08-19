"""The unit conversions that stay in stompdrill: the grid pitch and PDF points."""

from __future__ import annotations

from stompdrill.units import NM_PER_MICRON, Micron, mm_from_pt, nm_from_micron


def test_one_inch_of_pdf_user_space_is_25_4_millimetres() -> None:
    assert mm_from_pt(72.0) == 25.4


def test_a_single_point_keeps_full_float_precision() -> None:
    """A change of unit, and deliberately not a change of representation:
    one point is 25.4/72 mm and stays every digit of it."""
    assert mm_from_pt(1.0) == 25.4 / 72.0
    assert type(mm_from_pt(1.0)) is float


def test_a_grid_pitch_widens_to_the_canonical_unit() -> None:
    assert nm_from_micron(Micron(250)) == 250 * NM_PER_MICRON
    assert nm_from_micron(Micron(250)) == 250_000
