"""Each cited ISO constant, checked against the clause it came from.

The standards are held in ``docs/iso/``. A test here failing means a number was
transcribed wrongly, not that a drawing looks wrong.
"""

from __future__ import annotations

import pytest

from aidrill.emitters.drawing.build import iso_frame_items, pens_for
from aidrill.emitters.drawing.layout import Layout
from aidrill.emitters.drawing.scene import Line, Polygon, Rect, Text
from aidrill.emitters.drawing.sheet import (
    A4_PORTRAIT,
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
    FrameStyle,
    Sheet,
    grid_divisions,
)
from aidrill.model import DrillData


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


@pytest.mark.parametrize("count", [0, 1])
def test_an_undivided_extent_is_one_field_rather_than_a_pair_of_corners(count):
    """4.4 divides between two corner fields, which needs two fields to divide.

    Below that there is nothing to divide: the extent is the field. The naive
    arithmetic would answer a count of one with *two* fields of 130 mm.
    """
    assert grid_divisions(210.0, count) == (210.0,)


def test_two_fields_are_two_corners_with_nothing_between_them():
    """The first count that does divide, and the boundary the guard sits on.

    No tabulated sheet asks for two, so this is the case that says where the
    guard stops: at two the extent is halved between the corner fields, and
    the remainder rule has no interior field to take 50 mm from.
    """
    assert grid_divisions(210.0, 2) == (105.0, 105.0)


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


# --- ISO 5457 sheet furniture ---------------------------------------------


def iso_layout(sheet: Sheet = A4_PORTRAIT) -> Layout:
    return Layout.for_sheet(sheet, DrillData(), scale=1.0, frame=FrameStyle.ISO_5457)


def test_the_frame_rectangle_is_the_tabulated_drawing_space():
    """4.2, cross-checked against Table 1 by the box the sheet reports."""
    layout = iso_layout()
    items = iso_frame_items(layout, pens_for(GROUP_0_7, FrameStyle.ISO_5457))

    frame = next(i for i in items if isinstance(i, Rect) and i.cls == "iso-frame")

    assert (frame.x, frame.y) == (FILING_BORDER, PLAIN_BORDER)
    assert (frame.width, frame.height) == (180.0, 277.0)
    assert frame.stroke.width == FRAME_WIDTH


def test_there_are_exactly_four_centring_marks_on_the_axes_of_symmetry():
    """4.3: at the ends of the two axes of symmetry of the trimmed sheet."""
    layout = iso_layout()
    marks = [
        item
        for item in iso_frame_items(layout, pens_for(GROUP_0_7, FrameStyle.ISO_5457))
        if isinstance(item, Line) and item.cls == "centring-mark"
    ]

    assert len(marks) == 4
    assert all(mark.stroke.width == CENTRING_MARK_WIDTH for mark in marks)

    half_width, half_height = 210.0 / 2.0, 297.0 / 2.0
    # ``Line`` has no ordering (nor should it gain one just for this test), so
    # this only needs the two groups, not a particular order within them.
    vertical = [m for m in marks if m.x1 == m.x2]
    horizontal = [m for m in marks if m.y1 == m.y2]
    assert len(vertical) == 2 and len(horizontal) == 2
    assert all(mark.x1 == half_width for mark in vertical)
    assert all(mark.y1 == half_height for mark in horizontal)


def test_a_centring_mark_runs_from_the_trimmed_edge_past_the_frame():
    """4.3: every mark starts at the trimmed edge and runs inward, past its own
    frame edge, by the overshoot. The left edge's border is ``FILING_BORDER``
    (20 mm), not ``PLAIN_BORDER`` like the other three, so a test that assumed
    one border width for every edge would be wrong exactly where it matters.
    """
    layout = iso_layout()
    sheet = layout.sheet
    marks = [
        item
        for item in iso_frame_items(layout, pens_for(GROUP_0_7, FrameStyle.ISO_5457))
        if isinstance(item, Line) and item.cls == "centring-mark"
    ]
    top = next(m for m in marks if m.x1 == m.x2 and min(m.y1, m.y2) == 0.0)
    bottom = next(m for m in marks if m.x1 == m.x2 and max(m.y1, m.y2) == sheet.height)
    left = next(m for m in marks if m.y1 == m.y2 and min(m.x1, m.x2) == 0.0)
    right = next(m for m in marks if m.y1 == m.y2 and max(m.x1, m.x2) == sheet.width)

    # From the trimmed edge (0) to 10 mm inside the frame, which is at y = 10.
    assert max(top.y1, top.y2) == PLAIN_BORDER + CENTRING_MARK_OVERSHOOT
    assert min(bottom.y1, bottom.y2) == sheet.height - PLAIN_BORDER - CENTRING_MARK_OVERSHOOT
    assert max(left.x1, left.x2) == FILING_BORDER + CENTRING_MARK_OVERSHOOT
    assert min(right.x1, right.x2) == sheet.width - PLAIN_BORDER - CENTRING_MARK_OVERSHOOT


def test_trimming_marks_are_two_overlapping_rectangles_at_each_edge():
    """4.5: four edges, two rectangles each, crossed so the pair actually overlaps."""
    layout = iso_layout()
    marks = [
        item
        for item in iso_frame_items(layout, pens_for(GROUP_0_7, FrameStyle.ISO_5457))
        if isinstance(item, Polygon) and item.cls == "trim-mark"
    ]

    assert len(marks) == 8
    sheet = layout.sheet
    boxes: list[tuple[float, float, float, float]] = []
    for mark in marks:
        assert len(mark.points) == 4
        xs = {round(x, 6) for x, _ in mark.points}
        ys = {round(y, 6) for _, y in mark.points}
        sides = sorted((max(xs) - min(xs), max(ys) - min(ys)))
        assert sides == [TRIM_MARK_SHORT, TRIM_MARK_LONG]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))

    # Each pair straddles the corner it marks rather than sharing an anchor, so
    # the pairs are found by the sheet corner they touch — one per corner, four
    # in all. Grouping by a common minimum instead would pass for marks that all
    # point the same way, which is the arrangement this checks against.
    corners: dict[tuple[float, float], list[tuple[float, float, float, float]]] = {}
    for corner_x, corner_y in (
        (0.0, 0.0),
        (sheet.width, 0.0),
        (0.0, sheet.height),
        (sheet.width, sheet.height),
    ):
        corners[(corner_x, corner_y)] = [
            box
            for box in boxes
            if corner_x in (box[0], box[2]) and corner_y in (box[1], box[3])
        ]
    assert len(corners) == 4
    assert sum(len(pair) for pair in corners.values()) == 8
    for pair in corners.values():
        assert len(pair) == 2
        (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = pair
        overlap_w = min(ax1, bx1) - max(ax0, bx0)
        overlap_h = min(ay1, by1) - max(ay0, by0)
        # e.g. at (0, 0) the boxes are [0,10]x[0,5] and [0,5]x[0,10], sharing
        # [0,5]x[0,5] — genuinely overlapping, not merely touching an edge.
        assert overlap_w == TRIM_MARK_SHORT
        assert overlap_h == TRIM_MARK_SHORT


def test_the_size_designation_sits_in_the_bottom_border_at_the_right_corner():
    """3.1: 'placed in the bottom border at the right corner'."""
    from aidrill.emitters.drawing.scene import Text

    layout = iso_layout()
    label = next(
        item
        for item in iso_frame_items(layout, pens_for(GROUP_0_7, FrameStyle.ISO_5457))
        if isinstance(item, Text) and item.cls == "size-designation"
    )

    assert label.content == "A4"
    assert label.x > 210.0 / 2.0        # right half
    assert label.y > 297.0 - PLAIN_BORDER  # below the frame, in the border


# --- ISO 5457 grid reference system ----------------------------------------


def grid_text(sheet: Sheet) -> list[Text]:
    from aidrill.emitters.drawing.build import grid_reference_items

    return [item for item in grid_reference_items(sheet) if isinstance(item, Text)]


def test_letters_run_down_the_side_and_numerals_across_the_top():
    """4.4: letters from the top downwards, numerals from left to right."""
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    labels = grid_text(A3_LANDSCAPE)
    letters = [t for t in labels if t.content.isalpha()]
    numerals = [t for t in labels if t.content.isdigit()]

    # A3: 8 across, 6 down, each appearing on both sides of the sheet.
    assert len(numerals) == 8 * 2
    assert len(letters) == 6 * 2

    down = sorted({t.content for t in letters})
    assert down == ["A", "B", "C", "D", "E", "F"]
    assert sorted({int(t.content) for t in numerals}) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_the_first_letter_is_at_the_top_and_the_last_at_the_bottom():
    """Y runs down the sheet, so A has the smallest Y."""
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    letters = [t for t in grid_text(A3_LANDSCAPE) if t.content.isalpha()]
    a_positions = [t.y for t in letters if t.content == "A"]
    f_positions = [t.y for t in letters if t.content == "F"]

    assert max(a_positions) < min(f_positions)


def test_the_first_numeral_is_at_the_left_and_the_last_at_the_right():
    """4.4: 'from left to right', so 1 has the smallest X and 8 the largest."""
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    numerals = [t for t in grid_text(A3_LANDSCAPE) if t.content.isdigit()]
    first_positions = [t.x for t in numerals if t.content == "1"]
    last_positions = [t.x for t in numerals if t.content == "8"]

    assert max(first_positions) < min(last_positions)


def test_a4_carries_its_references_only_at_the_top_and_the_right():
    """4.4: 'For the size A4, they are located only at the top and the right side'."""
    from aidrill.emitters.drawing.sheet import A4_PORTRAIT

    labels = grid_text(A4_PORTRAIT)
    numerals = [t for t in labels if t.content.isdigit()]
    letters = [t for t in labels if t.content.isalpha()]

    # 4 across and 6 down, each appearing once rather than on both sides.
    assert len(numerals) == 4
    assert len(letters) == 6
    assert all(t.y < 297.0 / 2.0 for t in numerals)      # top border only
    assert all(t.x > 210.0 / 2.0 for t in letters)       # right border only


def test_grid_characters_are_three_and_a_half_millimetres():
    """4.4: 'The size of letters and characters is 3,5 mm'."""
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    assert all(t.size == GRID_CHARACTER_SIZE for t in grid_text(A3_LANDSCAPE))


def test_grid_lines_are_drawn_narrow():
    """4.4: 'shall be executed with continuous lines of 0,35 mm width'."""
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.scene import Line
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    lines = [i for i in grid_reference_items(A3_LANDSCAPE) if isinstance(i, Line)]

    assert lines
    assert all(line.stroke.width == GRID_LINE_WIDTH for line in lines)


def test_every_grid_reference_band_is_the_same_depth():
    """4.4's band sits against the frame, so all four are one depth.

    4.2 widens the left border to 20 mm "including the frame ... used as a
    filing margin", and that margin lies outside the band. Measuring the band
    from the trimmed edge instead would draw the left one at twice the depth of
    the other three, which is visible on the page.
    """
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.scene import Line
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    # Field divisions only. The band's own outer edge runs the other way, along
    # the band rather than across it, so measuring it here would report the
    # sheet's height as a band depth.
    lines = [
        i
        for i in grid_reference_items(A3_LANDSCAPE)
        if isinstance(i, Line) and i.cls == "grid-line"
    ]
    horizontal = [line for line in lines if line.y1 == line.y2]
    vertical = [line for line in lines if line.x1 == line.x2]
    width, height = A3_LANDSCAPE.width, A3_LANDSCAPE.height

    left = [line for line in horizontal if min(line.x1, line.x2) < width / 2.0]
    right = [line for line in horizontal if min(line.x1, line.x2) > width / 2.0]
    top = [line for line in vertical if min(line.y1, line.y2) < height / 2.0]
    bottom = [line for line in vertical if min(line.y1, line.y2) > height / 2.0]
    assert left and right and top and bottom

    for band in (left, right):
        assert all(abs(line.x2 - line.x1) == PLAIN_BORDER for line in band)
    for band in (top, bottom):
        assert all(abs(line.y2 - line.y1) == PLAIN_BORDER for line in band)

    # The left band is inset by the filing margin rather than being deeper.
    assert all(min(line.x1, line.x2) == FILING_BORDER - PLAIN_BORDER for line in left)
    assert all(max(line.x1, line.x2) == FILING_BORDER for line in left)
    assert all(max(line.x1, line.x2) == width for line in right)


def test_a_grid_letter_sits_at_the_centre_of_its_own_band():
    """A label centred on the trimmed edge instead would sit in the filing margin."""
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.scene import Text
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    labels = [i for i in grid_reference_items(A3_LANDSCAPE) if isinstance(i, Text)]
    letters = [t for t in labels if t.content.isalpha()]
    left = sorted({t.x for t in letters if t.x < A3_LANDSCAPE.width / 2.0})

    assert left == [FILING_BORDER - PLAIN_BORDER / 2.0]


@pytest.mark.parametrize(
    ("across", "down"),
    # Each count on its own, and both together: a sheet lettered down one edge
    # and numbered nowhere across is not half a reference system, it is none.
    [(0, 0), (8, 0), (0, 6)],
)
def test_a_sheet_with_no_tabulated_fields_carries_no_reference_system(across, down):
    """Table 2 tabulates the counts, and the SVG sheets are not in Table 2."""
    from aidrill.emitters.drawing.build import grid_reference_items

    plain = Sheet("A3", 420.0, 297.0, fields_across=across, fields_down=down)

    assert grid_reference_items(plain) == []


def test_the_svg_sheets_are_not_lettered_because_they_are_not_iso_sheets():
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE_PLAIN, A4_LANDSCAPE

    for sheet in (A4_LANDSCAPE, A3_LANDSCAPE_PLAIN):
        assert sheet.grid_fields == (0, 0)
        assert grid_reference_items(sheet) == []


def test_letters_never_use_i_or_o_even_on_the_largest_sheet():
    """A0 needs 16 letters, which is where a naive alphabet would reach I."""
    from aidrill.emitters.drawing.sheet import A0_LANDSCAPE

    used = {t.content for t in grid_text(A0_LANDSCAPE) if t.content.isalpha()}

    assert len(used) == 16
    assert "I" not in used and "O" not in used
    assert "J" in used  # the letter that takes I's place


# --- ISO 7200 title block ---------------------------------------------------


def test_every_mandatory_iso_7200_field_is_present_even_when_empty():
    """Tables 1-3. A blank mandatory field is a stated gap, not an omission."""
    from aidrill.emitters.drawing.build import SheetText
    from aidrill.emitters.drawing.content import title_fields

    layout = iso_layout()
    fields = title_fields(DrillData(), SheetText(), layout)
    mandatory = {f.name for f in fields if f.mandatory}

    assert mandatory == {
        "LEGAL OWNER",       # 5.1.2
        "IDENT NO",          # 5.1.3
        "DATE OF ISSUE",     # 5.1.5
        "SHEET",             # 5.1.6
        "TITLE",             # 5.2.2
        "APPROVED",          # 5.3.4
        "CREATOR",           # 5.3.5
        "DOC TYPE",          # 5.3.6
    }


def test_a_field_aidrill_cannot_derive_renders_as_an_em_dash():
    """Date of issue, approver and creator have no source in artwork."""
    from aidrill.emitters.drawing.build import SheetText
    from aidrill.emitters.drawing.content import title_fields

    fields = {f.name: f.value for f in title_fields(DrillData(), SheetText(), iso_layout())}

    assert fields["DATE OF ISSUE"] == "—"
    assert fields["APPROVED"] == "—"
    assert fields["CREATOR"] == "—"


def test_supplied_values_reach_their_fields():
    from aidrill.emitters.drawing.build import SheetText
    from aidrill.emitters.drawing.content import title_fields

    text = SheetText(title="TAR PANEL", drawing_no="AI-0001", company="ARTIFACT",
                     issue_date="2026-08-16", approved_by="P VAKHNIVSKYI", creator="AIDRILL")
    fields = {f.name: f.value for f in title_fields(DrillData(), text, iso_layout())}

    assert fields["TITLE"] == "TAR PANEL"
    assert fields["IDENT NO"] == "AI-0001"
    assert fields["LEGAL OWNER"] == "ARTIFACT"
    assert fields["DATE OF ISSUE"] == "2026-08-16"
    assert fields["APPROVED"] == "P VAKHNIVSKYI"
    assert fields["CREATOR"] == "AIDRILL"
    assert fields["DOC TYPE"] == "DRILL DRAWING"
    assert fields["SHEET"] == "1 / 1"


def test_a_value_longer_than_its_recommended_length_is_truncated():
    """Tables 1-3 give character counts; the field limit binds before the box does."""
    from aidrill.emitters.drawing.build import SheetText
    from aidrill.emitters.drawing.content import title_fields

    text = SheetText(drawing_no="X" * 40, title="Y" * 40, approved_by="Z" * 40)  # 5.1.3 recommends 16
    fields = {f.name: f for f in title_fields(DrillData(), text, iso_layout())}

    assert len(fields["IDENT NO"].value) <= fields["IDENT NO"].limit == 16
    assert len(fields["TITLE"].value) <= fields["TITLE"].limit == 25
    assert len(fields["APPROVED"].value) <= fields["APPROVED"].limit == 20
    # A field the tables give no count for keeps its value whole.
    assert fields["UNITS"].limit == 0


def test_the_block_is_one_hundred_and_eighty_wide_whatever_the_sheet():
    """ISO 7200 6: the same title block on every paper size."""
    from aidrill.emitters.drawing.sheet import A0_LANDSCAPE, A3_LANDSCAPE

    for sheet in (A4_PORTRAIT, A3_LANDSCAPE, A0_LANDSCAPE):
        layout = iso_layout(sheet)
        x0, _, x1, _ = layout.title_block
        assert x1 - x0 == pytest.approx(TITLE_BLOCK_WIDTH)


def test_the_block_sits_in_the_bottom_right_of_the_drawing_space():
    """5457 4.1: bottom right for A0-A3; the lower part for A4."""
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    for sheet in (A4_PORTRAIT, A3_LANDSCAPE):
        layout = iso_layout(sheet)
        space_x0, _, space_x1, space_y1 = sheet.space
        x0, _, x1, y1 = layout.title_block
        assert x1 == pytest.approx(space_x1)
        assert y1 == pytest.approx(space_y1)
        assert x0 >= space_x0
    # On A4 the block is the full drawing-space width, which is why 180 was chosen.
    assert iso_layout(A4_PORTRAIT).title_block[0] == pytest.approx(A4_PORTRAIT.space[0])


def test_the_block_is_ruled_into_cells_that_each_carry_a_label_and_a_value():
    """A field is a labelled box: the label says which claim the value makes."""
    from aidrill.emitters.drawing.build import SheetText, build_scene
    from aidrill.emitters.drawing.content import title_fields
    from aidrill.emitters.drawing.scene import Group, Text

    layout = iso_layout()
    items = build_scene(layout, DrillData(), SheetText()).items
    block = next(i for i in items if isinstance(i, Group) and i.cls == "title-block-group")
    labels = [i.content for i in block.items if isinstance(i, Text) and i.cls == "tb-label"]
    values = [i for i in block.items if isinstance(i, Text) and i.cls == "tb-value"]

    assert labels == [field.name for field in title_fields(DrillData(), SheetText(), layout)]
    assert len(values) == len(labels)


def test_no_rule_in_the_block_is_a_line_of_no_length():
    """A rule that starts where it ends is ink that draws nothing."""
    from aidrill.emitters.drawing.build import SheetText, build_scene
    from aidrill.emitters.drawing.scene import Group, Line

    items = build_scene(iso_layout(), DrillData(), SheetText()).items
    block = next(i for i in items if isinstance(i, Group) and i.cls == "title-block-group")
    rules = [i for i in block.items if isinstance(i, Line) and i.cls == "tb-rule"]

    assert rules
    assert all((rule.x1, rule.y1) != (rule.x2, rule.y2) for rule in rules)
    # One rule per interior boundary, drawn once rather than once per field.
    assert len(rules) == len(set((r.x1, r.y1, r.x2, r.y2) for r in rules))


def test_a_value_of_exactly_its_recommended_length_is_left_alone():
    """The count is a length the field admits, so the boundary is inclusive."""
    from aidrill.emitters.drawing.build import SheetText
    from aidrill.emitters.drawing.content import title_fields

    def ident(text: SheetText) -> str:
        return next(f for f in title_fields(DrillData(), text, iso_layout())
                    if f.name == "IDENT NO").value

    assert ident(SheetText(drawing_no="X" * 16)) == "X" * 16
    # One over, and the ellipsis is inside the count rather than added to it.
    assert ident(SheetText(drawing_no="X" * 17)) == "X" * 15 + "…"
    assert len(ident(SheetText(drawing_no="X" * 17))) == 16


def test_the_reference_ticks_and_letters_land_on_the_same_edges():
    """4.4 references A4 at the top and the right; both marks must agree.

    Ticks and labels are drawn from separate loops, so nothing but this stops
    one edge being ruled while the letters naming its fields sit on another —
    a sheet whose zone references cannot be read at all.
    """
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.scene import Line, Text
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE, A4_PORTRAIT

    for sheet in (A4_PORTRAIT, A3_LANDSCAPE):
        items = grid_reference_items(sheet)
        ticks = [i for i in items if isinstance(i, Line) and i.cls == "grid-line"]
        labels = [i for i in items if isinstance(i, Text)]
        half_w, half_h = sheet.width / 2.0, sheet.height / 2.0

        ruled = {
            "top": any(t.x1 == t.x2 and min(t.y1, t.y2) < half_h for t in ticks),
            "bottom": any(t.x1 == t.x2 and min(t.y1, t.y2) > half_h for t in ticks),
            "left": any(t.y1 == t.y2 and min(t.x1, t.x2) < half_w for t in ticks),
            "right": any(t.y1 == t.y2 and min(t.x1, t.x2) > half_w for t in ticks),
        }
        lettered = {
            "top": any(t.y < half_h and t.content.isdigit() for t in labels),
            "bottom": any(t.y > half_h and t.content.isdigit() for t in labels),
            "left": any(t.x < half_w and t.content.isalpha() for t in labels),
            "right": any(t.x > half_w and t.content.isalpha() for t in labels),
        }
        assert ruled == lettered, f"{sheet.name}: ruled {ruled} but lettered {lettered}"

    # And the edges are the ones the clause names, not merely a matching pair.
    a4 = grid_reference_items(A4_PORTRAIT)
    a4_labels = [i for i in a4 if isinstance(i, Text)]
    assert all(t.y < A4_PORTRAIT.height / 2.0 for t in a4_labels if t.content.isdigit())
    assert all(t.x > A4_PORTRAIT.width / 2.0 for t in a4_labels if t.content.isalpha())


def test_the_filing_edge_band_is_bounded_where_the_trimmed_edge_is_not_its_edge():
    """The band stops at the filing margin, so something has to say where.

    On three edges the trimmed edge bounds the band. On the filing edge the
    band starts 10 mm in, and without its own line the margin and the band read
    as one 20 mm strip that the field divisions only half cross.
    """
    from aidrill.emitters.drawing.build import grid_reference_items
    from aidrill.emitters.drawing.scene import Line
    from aidrill.emitters.drawing.sheet import A3_LANDSCAPE

    edges = [
        i
        for i in grid_reference_items(A3_LANDSCAPE)
        if isinstance(i, Line) and i.cls == "grid-edge"
    ]

    # Exactly one: the filing edge. The other three bands reach the trimmed edge.
    assert len(edges) == 1
    (edge,) = edges
    assert edge.x1 == edge.x2 == FILING_BORDER - PLAIN_BORDER
    assert min(edge.y1, edge.y2) == 0.0
    assert max(edge.y1, edge.y2) == A3_LANDSCAPE.height
