"""Sheet geometry and the ISO 5457 candidate ladder."""

from __future__ import annotations

from stompdrill.emitters.drawing.sheet import (
    A0_LANDSCAPE,
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    A4_PORTRAIT,
    ISO_5457_CANDIDATES,
    FrameStyle,
    Sheet,
)


def test_the_candidate_ladder_is_five_sheets_in_ascending_area():
    """ISO 5457 4.1 leaves one legal orientation per size, so there is no choice."""
    names = [sheet.name for sheet in ISO_5457_CANDIDATES]
    assert names == ["A4", "A3", "A2", "A1", "A0"]

    areas = [sheet.width * sheet.height for sheet in ISO_5457_CANDIDATES]
    assert areas == sorted(areas)


def test_a4_is_portrait_and_every_larger_sheet_is_landscape():
    """4.1: only vertical is allowed for A4, only horizontal for A0 to A3."""
    a4, *larger = ISO_5457_CANDIDATES
    assert not a4.is_landscape
    assert all(sheet.is_landscape for sheet in larger)


def test_a_standard_sheet_reports_the_tabulated_drawing_space():
    """Table 1 tabulates the space; it is a lookup, not a margin calculation."""
    assert (A4_PORTRAIT.width, A4_PORTRAIT.height) == (210.0, 297.0)
    assert (A4_PORTRAIT.space_width, A4_PORTRAIT.space_height) == (180.0, 277.0)
    assert (A3_LANDSCAPE.width, A3_LANDSCAPE.height) == (420.0, 297.0)
    assert (A3_LANDSCAPE.space_width, A3_LANDSCAPE.space_height) == (390.0, 277.0)


def test_the_drawing_space_box_is_offset_by_the_filing_margin():
    """4.2: 20 mm on the left including the frame, 10 mm on the other three."""
    x0, y0, x1, y1 = A4_PORTRAIT.space

    assert (x0, y0) == (20.0, 10.0)
    assert (x1, y1) == (200.0, 287.0)
    assert (x1 - x0, y1 - y0) == (180.0, 277.0)


def test_a_sheet_without_a_tabulated_space_falls_back_to_its_margin():
    """A custom sheet is still drawable; it just is not an ISO one."""
    custom = Sheet("custom", 100.0, 80.0)

    assert custom.space_width is None
    assert custom.margin == 4.0  # min(10, min(100, 80) * 0.05)
    assert custom.space == (4.0, 4.0, 96.0, 76.0)


def test_the_legacy_a4_landscape_sheet_still_exists_for_the_svg_emitter():
    """The SVG sheet keeps its own furniture and its own default."""
    assert (A4_LANDSCAPE.width, A4_LANDSCAPE.height) == (297.0, 210.0)
    assert A4_LANDSCAPE not in ISO_5457_CANDIDATES


def test_grid_field_counts_come_from_table_2_not_from_dividing_by_fifty():
    """4.4 Table 2 fixes the count; 50 mm is the field length, not the divisor."""
    # A4 portrait: long side is vertical.
    assert A4_PORTRAIT.grid_fields == (4, 6)
    # A3 landscape: long side is horizontal.
    assert A3_LANDSCAPE.grid_fields == (8, 6)
    assert A0_LANDSCAPE.grid_fields == (24, 16)


def test_frame_styles_are_the_two_the_emitters_use():
    assert {style.value for style in FrameStyle} == {"plain", "iso-5457"}
