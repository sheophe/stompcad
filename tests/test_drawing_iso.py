"""Each cited ISO constant, checked against the clause it came from.

The standards are held in ``docs/iso/``. A test here failing means a number was
transcribed wrongly, not that a drawing looks wrong.
"""

from __future__ import annotations

import pytest

from aidrill.emitters.drawing.sheet import (
    CENTRING_MARK_OVERSHOOT,
    CENTRING_MARK_WIDTH,
    FILING_BORDER,
    FRAME_WIDTH,
    GRID_CHARACTER_SIZE,
    GRID_FIELD_LENGTH,
    GRID_LETTERS,
    GRID_LINE_WIDTH,
    GROUP_0_7,
    ISO_5457_CANDIDATES,
    LINE_GROUPS,
    PLAIN_BORDER,
    TITLE_BLOCK_WIDTH,
    TRIM_MARK_LONG,
    TRIM_MARK_SHORT,
    grid_divisions,
)


def test_borders_are_twenty_on_the_filing_edge_and_ten_elsewhere():
    """ISO 5457:1999 4.2."""
    assert FILING_BORDER == 20.0
    assert PLAIN_BORDER == 10.0


def test_table_1_and_clause_4_2_agree_for_every_sheet():
    """The tabulated drawing space must equal the trimmed size less the borders.

    Table 1 and 4.2 are independent statements. Requiring them to agree catches a
    transcription slip in any of the twenty tabulated numbers.
    """
    for sheet in ISO_5457_CANDIDATES:
        assert sheet.width - sheet.space_width == FILING_BORDER + PLAIN_BORDER
        assert sheet.height - sheet.space_height == PLAIN_BORDER + PLAIN_BORDER


def test_the_frame_is_drawn_at_zero_point_seven():
    """4.2: 'executed with continuous lines of 0,7 mm width'."""
    assert FRAME_WIDTH == 0.7


def test_centring_marks_are_zero_point_seven_and_reach_ten_past_the_frame():
    """4.3: 0,7 mm, starting at the grid reference border, 10 mm beyond the frame."""
    assert CENTRING_MARK_WIDTH == 0.7
    assert CENTRING_MARK_OVERSHOOT == 10.0


def test_grid_letters_skip_i_and_o():
    """4.4: 'capital letters (I and O shall not be used)'."""
    assert "I" not in GRID_LETTERS
    assert "O" not in GRID_LETTERS
    assert GRID_LETTERS.startswith("ABCDEFGH")
    assert len(GRID_LETTERS) == 24


def test_grid_lines_and_characters_are_the_cited_sizes():
    """4.4: characters 3,5 mm; grid reference lines 0,35 mm; fields 50 mm."""
    assert GRID_CHARACTER_SIZE == 3.5
    assert GRID_LINE_WIDTH == 0.35
    assert GRID_FIELD_LENGTH == 50.0


@pytest.mark.parametrize(
    ("name", "extent", "count", "expected"),
    [
        # 4.4: fields are 50 mm from the axes of symmetry; the remainder is
        # added to the fields at the corners, so end fields may be larger or
        # smaller than 50. Both directions appear here on purpose.
        ("A4 horizontal", 210.0, 4, (55.0, 50.0, 50.0, 55.0)),
        ("A4 vertical", 297.0, 6, (48.5, 50.0, 50.0, 50.0, 50.0, 48.5)),
        ("A3 horizontal", 420.0, 8, (60.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 60.0)),
        ("A0 vertical", 841.0, 16, None),
    ],
)
def test_grid_divisions_put_the_remainder_in_the_corner_fields(name, extent, count, expected):
    """4.4: 'the differences resulting from the division are added to the corners'."""
    divisions = grid_divisions(extent, count)

    assert len(divisions) == count
    assert sum(divisions) == pytest.approx(extent)
    if expected is not None:
        assert divisions == pytest.approx(expected)
    # Interior fields are always exactly the cited length.
    assert all(field == pytest.approx(GRID_FIELD_LENGTH) for field in divisions[1:-1])


def test_a0_end_fields_are_larger_than_fifty_and_a4_end_fields_are_smaller():
    """The two directions the remainder can go. A clamp to 50 fails both."""
    assert grid_divisions(841.0, 16)[0] == pytest.approx(70.5)
    assert grid_divisions(297.0, 6)[0] == pytest.approx(48.5)


def test_trimming_marks_are_two_overlapping_ten_by_five_rectangles():
    """4.5."""
    assert (TRIM_MARK_LONG, TRIM_MARK_SHORT) == (10.0, 5.0)


def test_the_title_block_is_one_hundred_and_eighty_wide_on_every_size():
    """ISO 7200:2004 6: 'The same title block is used for all paper sizes'."""
    assert TITLE_BLOCK_WIDTH == 180.0
    # It is exactly the A4 drawing-space width, which is why 180 was chosen.
    a4 = ISO_5457_CANDIDATES[0]
    assert TITLE_BLOCK_WIDTH == a4.space_width


def test_line_groups_are_named_by_the_wide_width_and_halve_it():
    """ISO 128-24:1999 5 and Table 2: two widths in a 1:2 proportion."""
    assert LINE_GROUPS["0.35"] == (0.35, 0.18)
    assert LINE_GROUPS["0.5"] == (0.5, 0.25)
    assert LINE_GROUPS["0.7"] == (0.7, 0.35)
    # 0,35 and 0,7 are different rows. Confusing them is the mistake this catches.
    assert LINE_GROUPS["0.35"] != LINE_GROUPS["0.7"]


def test_the_chosen_group_matches_the_widths_iso_5457_independently_mandates():
    """5457 4.2 wants 0,7 for the frame and 4.4 wants 0,35 for grid lines.

    That pair is exactly line group 0,7, so the drawing and the sheet furniture
    are one system rather than two.
    """
    assert (GROUP_0_7.wide, GROUP_0_7.narrow) == (FRAME_WIDTH, GRID_LINE_WIDTH)
