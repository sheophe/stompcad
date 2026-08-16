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
    note = content.enclosure_note(DrillData().with_enclosure(match), 59)

    assert "CANDIDATES" in note
    assert "MORE" in note


def test_allot_reserves_a_line_for_the_omission_marker():
    """Fitting exactly means no marker; one too many costs a line to say so."""
    assert content.allot(5, 5) == (5, 0)
    assert content.allot(6, 5) == (4, 2)


def test_fits_truncates_with_an_ellipsis_rather_than_clipping_silently():
    assert content.fits("SHORT", 2.0, 100.0) == "SHORT"
    truncated = content.fits("A VERY LONG TITLE INDEED", 2.0, 10.0)
    assert truncated.endswith("…")
    assert len(truncated) < len("A VERY LONG TITLE INDEED")


def test_a_flagged_hole_is_matched_by_identity_and_by_code():
    """Diagnostics are joined on code and hole_index, never on geometry."""
    duplicate = Diagnostic.warning(
        content.DUP_CODE, "two coincident holes", data=(("hole_index", 12),)
    )
    other = Diagnostic.warning("off-grid", "moved", data=(("hole_index", 5),))

    flagged = content.flagged_holes((duplicate, other))

    assert content.is_flagged(at(0, 0, index=12), flagged)
    assert not content.is_flagged(at(0, 0, index=5), flagged)


def test_notes_fall_back_to_saying_there_were_none():
    """A blank notes box would read as an unrendered box."""
    (note,) = content.note_lines(DrillData())

    assert note.severity is Severity.INFO
    assert "No diagnostics" in note.text
