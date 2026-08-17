"""Facts the sheet states, independent of any backend."""

from __future__ import annotations

from aidrill.emitters.drawing import content
from aidrill.model import Diagnostic, DrillData, EnclosureMatch, Severity, StageRun
from tests.conftest import at, make_data


def test_the_schedule_names_holes_by_identity_not_by_position():
    """A row's NO. is Hole.index, which is why fixtures use out-of-order ids."""
    data = make_data(at(20_000_000, 0, index=9), at(-20_000_000, 0, index=4))

    rows = content.schedule_rows(data)

    assert [row.number for row in rows] == [9, 4]
    assert [row.x for row in rows] == ["20.000", "-20.000"]


def test_a_negative_zero_coordinate_prints_without_its_sign():
    """format_nm normalises it, so the drawing and the drill file agree."""
    data = make_data(at(-400, 0, index=1))

    assert content.schedule_rows(data)[0].x == "0.000"


def test_the_grid_note_says_so_when_no_pitch_was_recorded():
    """A missing record and an unusable one get the same honest answer."""
    assert content.grid_note(DrillData()) == "GRID NOT RECORDED"

    tabled = DrillData().with_processing(
        StageRun(content.SNAP_STAGE, ((content.GRID_PARAMETER, (250_000, 500_000)),))
    )
    assert content.grid_note(tabled) == "GRID NOT RECORDED"


def test_the_grid_note_reports_a_recorded_pitch_in_millimetres():
    data = DrillData().with_processing(
        StageRun(content.SNAP_STAGE, ((content.GRID_PARAMETER, 250_000),))
    )

    assert content.grid_note(data) == "GRID 0.250 mm"


def test_an_unidentified_enclosure_is_stated_rather_than_omitted():
    assert content.enclosure_note(DrillData(), 80) == "ENCLOSURE NOT IDENTIFIED"


def test_candidate_lists_end_in_a_counted_marker_when_they_do_not_fit():
    """An omitted candidate is counted, never silently dropped."""
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=112_400_000,
        width_nm=60_500_000,
        candidates=("1590B", "1590B2", "1590BS", "1590BX"),
        selected_part=None,
        rotated=False,
    )
    # Narrow enough that even the bare candidate list, with no family and no
    # footprint ahead of it, cannot list all four without a counted marker.
    note = content.enclosure_note(DrillData().with_enclosure(match), 24)

    assert "CANDIDATES" in note
    assert "+3 MORE" in note


def test_the_note_sheds_the_footprint_before_the_part_designator():
    """A cell too narrow for the full claim still names the part: the
    footprint is already dimensioned on the drawing and is the cheaper loss."""
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=112_400_000,
        width_nm=60_500_000,
        candidates=("1590B", "1590B2"),
        selected_part="1590B",
        rotated=False,
    )
    data = DrillData().with_enclosure(match)
    full = content.enclosure_note(data, 200)
    assert full == "HAMMOND 1590  112.40 × 60.50 mm  PART 1590B"

    note = content.enclosure_note(data, 35)

    assert note == "HAMMOND 1590  PART 1590B"
    assert "1590B" in note


def test_the_note_sheds_the_family_before_the_candidate_list():
    """Naming which parts a panel might be is worth more than naming the
    family it belongs to, once even the family-only head overflows."""
    match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=112_400_000,
        width_nm=60_500_000,
        candidates=("1590B", "1590B2", "1590BS"),
        selected_part=None,
        rotated=False,
    )
    note = content.enclosure_note(DrillData().with_enclosure(match), 35)

    assert note == "CANDIDATES B / B2 / BS"


def test_allot_reserves_a_line_for_the_omission_marker():
    """Fitting exactly means no marker; one too many costs a line to say so."""
    assert content.allot(5, 5) == (5, 0)
    assert content.allot(6, 5) == (4, 2)


def test_fits_truncates_with_an_ellipsis_rather_than_clipping_silently():
    assert content.fits("SHORT", 2.0, 100.0) == "SHORT"
    truncated = content.fits("A VERY LONG TITLE INDEED", 2.0, 10.0)
    assert truncated.endswith("…")
    assert len(truncated) < len("A VERY LONG TITLE INDEED")


def test_fits_gives_back_what_it_can_when_the_box_holds_no_ellipsis():
    """A cell one character wide has no room for the … that says it was cut.

    The truncation rule is shared by both backends, so a box this narrow is a
    call any layout can make: it answers with the characters that fit rather
    than with an ellipsis that would be the whole of the cell's content.
    """
    assert content.fits("PANEL", 2.6, 1.0) == "P"
    # A size of zero leaves capacity for nothing, and nothing is what it returns.
    assert content.fits("PANEL", 0.0, 10.0) == ""
    # Two characters is where the ellipsis becomes affordable again.
    assert content.fits("PANEL", 2.6, 3.3) == "P…"


def test_a_flagged_hole_is_matched_by_code_and_by_location():
    """Diagnostics are joined on code and exact location, never by identity."""
    duplicate = Diagnostic.warning(
        content.DUP_CODE, "two coincident holes", location_nm=(1_000_000, 2_000_000)
    )
    other = Diagnostic.warning("off-grid", "moved", location_nm=(3_000_000, 4_000_000))

    flagged = content.flagged_holes((duplicate, other))

    assert content.is_flagged(at(1_000_000, 2_000_000, index=12), flagged)
    assert not content.is_flagged(at(3_000_000, 4_000_000, index=5), flagged)


def _mixed_diameter_panel() -> DrillData:
    """Two diameters with different hole counts, out-of-order identities.

    Different counts mean a test that swapped the two quantities would fail;
    out-of-order indices mean a test that read tuple position instead of
    identity would fail too.
    """
    return make_data(
        at(10_000_000, 0, 3_000_000, index=5),
        at(20_000_000, 0, 3_000_000, index=1),
        at(30_000_000, 0, 7_000_000, index=8),
        at(40_000_000, 0, 7_000_000, index=3),
        at(50_000_000, 0, 7_000_000, index=6),
    )


def test_tool_numbers_are_one_based_and_ascend_by_diameter():
    data = _mixed_diameter_panel()

    assert [line.tool for line in content.tool_summary(data)] == ["T1", "T2"]
    assert [f"T{n}" for n in data.tools().values()] == ["T1", "T2"]


def test_tool_quantities_count_holes_of_that_diameter_not_a_swapped_pair():
    """The 3 mm bit drills two holes, the 7 mm bit drills three — distinct counts
    so a summary that swapped them would be caught."""
    data = _mixed_diameter_panel()

    assert [line.quantity for line in content.tool_summary(data)] == [2, 3]


def test_the_tool_summary_spells_diameters_the_way_the_schedule_does():
    """The summary and the schedule must not disagree about how a bit is spelled."""
    data = _mixed_diameter_panel()
    label = content.diameter_label(data)

    assert [line.diameter for line in content.tool_summary(data)] == [
        label(3_000_000),
        label(7_000_000),
    ]


def test_a_panel_with_no_holes_has_an_empty_tool_summary():
    assert content.tool_summary(DrillData()) == ()


def test_notes_fall_back_to_saying_there_were_none():
    """A blank notes box would read as an unrendered box."""
    (note,) = content.note_lines(DrillData())

    assert note.severity is Severity.INFO
    assert "No diagnostics" in note.text
