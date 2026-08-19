"""The sheet solver, run in both directions."""

from __future__ import annotations

import pytest

from stompdrill.emitters.drawing.layout import Layout, choose_sheet, content_half_extents
from stompdrill.emitters.drawing.sheet import (
    A0_LANDSCAPE,
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    A4_PORTRAIT,
    ISO_5457_CANDIDATES,
    FrameStyle,
)
from stompdrill.model import ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import at, make_data


def outline(width_nm: int, height_nm: int) -> ReferenceOutline:
    return ReferenceOutline.from_measurement(Nanometre(width_nm), Nanometre(height_nm))


def panel(width_nm: int, height_nm: int):
    """A panel of a given outline with one hole, so extents come from the outline."""
    return make_data(at(0, 0, index=1), reference=outline(width_nm, height_nm))


# --- the PDF direction: scale fixed, sheet unknown -----------------------


def test_a_1590b_panel_takes_the_first_candidate():
    """112.40 x 60.50 fits A4 portrait's 180 x 277 drawing space with room over."""
    layout = choose_sheet(panel(112_400_000, 60_500_000), ISO_5457_CANDIDATES,
                          frame=FrameStyle.ISO_5457)

    assert layout.sheet is A4_PORTRAIT
    assert layout.scale == 1.0
    assert layout.fits


def test_a_panel_too_wide_for_a4_grows_to_a3():
    """A4's drawing space is 180 wide; 300 mm of panel cannot be drawn 1:1 on it.

    Wide and not tall, so it is the width that rejects A4: A3 is the same 277 mm
    of drawing space high, and the title block takes 46 mm of that on both.
    """
    layout = choose_sheet(panel(300_000_000, 120_000_000), ISO_5457_CANDIDATES,
                          frame=FrameStyle.ISO_5457)

    assert layout.sheet is A3_LANDSCAPE
    assert layout.scale == 1.0


def test_the_chosen_sheet_is_the_smallest_that_fits():
    """ISO 5457 3.1. Every earlier candidate must genuinely not fit."""
    data = panel(300_000_000, 200_000_000)
    chosen = choose_sheet(data, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)

    index = ISO_5457_CANDIDATES.index(chosen.sheet)
    for earlier in ISO_5457_CANDIDATES[:index]:
        rejected = Layout.for_sheet(earlier, data, scale=1.0, frame=FrameStyle.ISO_5457)
        assert not rejected.fits


def test_choosing_from_no_candidates_is_a_programming_error():
    """A caller that passes no sheets has a bug; hand back an exception, not None."""
    with pytest.raises(ValueError, match="candidate"):
        choose_sheet(panel(100_000_000, 50_000_000), (), frame=FrameStyle.ISO_5457)


def test_content_past_a0_clamps_to_the_last_candidate():
    """The ladder ends; elongated sizes are a non-goal, so A0 is the answer."""
    layout = choose_sheet(panel(2_000_000_000, 1_500_000_000), ISO_5457_CANDIDATES,
                          frame=FrameStyle.ISO_5457)

    assert layout.sheet is A0_LANDSCAPE
    assert layout.scale == 1.0
    assert not layout.fits  # the caller stamps the sheet; see Task 11


def test_a_fixed_scale_is_never_reduced_to_make_content_fit():
    """1:1 is a fabrication guarantee, so overflow is reported, not scaled away."""
    layout = Layout.for_sheet(A4_PORTRAIT, panel(2_000_000_000, 1_500_000_000),
                              scale=1.0, frame=FrameStyle.ISO_5457)

    assert layout.scale == 1.0
    assert not layout.fits


# --- the SVG direction: sheet fixed, scale unknown -----------------------


def test_a_sheet_without_a_scale_fits_the_content_to_it():
    """The SVG emitter's behaviour, unchanged: solve for scale on a fixed sheet."""
    layout = Layout.for_sheet(A4_LANDSCAPE, panel(112_400_000, 60_500_000), scale=None)

    # A4 landscape's working area comfortably holds this panel at 1:1, so the
    # raw fitted ratio rounds down no further than the ladder's own 1.0 rung.
    assert layout.scale == 1.0
    assert layout.fits


def test_a_fitted_scale_is_rounded_down_to_a_readable_one():
    """A title block says 1:2, never 1:2.37, and rounding down cannot overflow."""
    from stompdrill.emitters.drawing.layout import PREFERRED_SCALES, preferred_scale

    assert preferred_scale(2.4) == 2.0
    assert preferred_scale(0.9) == 0.5
    assert all(preferred_scale(value) <= value for value in (0.3, 1.7, 7.9, 23.0))
    assert preferred_scale(0.001) not in PREFERRED_SCALES  # below the ladder, kept raw
    # A ratio that lands exactly on a rung keeps that rung. Rounding *down* from
    # it would draw a panel that fits at 1:1 at half size, on a sheet with the
    # room for it — and 1:1 is the rung a printed template is read from.
    assert all(preferred_scale(rung) == rung for rung in PREFERRED_SCALES)


def test_a_degenerate_scale_request_falls_back_to_one_to_one():
    from stompdrill.emitters.drawing.layout import preferred_scale

    assert preferred_scale(0.0) == 1.0
    assert preferred_scale(float("inf")) == 20.0
    assert preferred_scale(float("nan")) == 1.0


# --- shared ---------------------------------------------------------------


def test_an_empty_panel_still_has_a_drawable_extent():
    """A 5 mm floor, so a panel with nothing on it does not divide by zero."""
    from stompdrill.model import DrillData

    assert content_half_extents(DrillData()) == (5.0, 5.0)


def test_extents_include_each_hole_radius_not_just_its_centre():
    """A hole at the edge is half a diameter wider than its centre says."""
    data = make_data(at(50_000_000, 0, 10_000_000, index=1))

    half_width, _ = content_half_extents(data)

    assert half_width == pytest.approx(55.0)


def test_for_sheet_keeps_the_frame_style_it_was_given():
    """The frame decides which furniture a sheet carries, so it must stick."""
    data = panel(100_000_000, 50_000_000)

    plain = Layout.for_sheet(A4_PORTRAIT, data, scale=1.0)
    assert plain.frame is FrameStyle.PLAIN

    iso = Layout.for_sheet(A4_PORTRAIT, data, scale=1.0, frame=FrameStyle.ISO_5457)
    assert iso.frame is FrameStyle.ISO_5457


def test_the_scale_label_reads_as_an_engineer_writes_it():
    layout = Layout.for_sheet(A4_PORTRAIT, panel(100_000_000, 50_000_000),
                              scale=1.0, frame=FrameStyle.ISO_5457)
    assert layout.scale_label == "1:1"

    half = Layout.for_sheet(A4_PORTRAIT, panel(100_000_000, 50_000_000), scale=0.5)
    assert half.scale_label == "1:2"

    twice = Layout.for_sheet(A4_PORTRAIT, panel(10_000_000, 5_000_000), scale=2.0)
    assert twice.scale_label == "2:1"


# --- the box the ISO drawing occupies -------------------------------------


def rows_panel(count: int, *, height_nm: int = 60_000_000):
    """A panel of ``count`` hole rows, so the chain stack is ``count`` deep.

    Each row is stepped 0.2 mm along X so no two share a pattern of stations.
    Rows drilled alike share one chain, so a column of identical rows would
    stack one deep however many rows it had, and stack nothing here.
    """
    holes = tuple(
        at(index * 200_000, (index - count // 2) * 2_000_000, index=count - index)
        for index in range(count)
    )
    return make_data(*holes, reference=outline(80_000_000, height_nm))


def test_a_panel_the_iso_furniture_leaves_no_room_for_climbs_to_the_next_sheet():
    """The ISO furniture is ruled inside the drawing space, so the box the
    drawing occupies is what it has to fit into. Measured against the whole
    tabulated space instead, this panel is judged to fit A4 and is then drawn
    across the title block that occupies the foot of that space.
    """
    tall = panel(100_000_000, 150_000_000)

    a4 = Layout.for_sheet(A4_PORTRAIT, tall, scale=1.0, frame=FrameStyle.ISO_5457)
    assert a4.needed_height <= a4.border[3] - a4.border[1], "the whole space would take it"
    assert a4.needed_height > a4.area[3] - a4.area[1], "the drawing box does not"
    assert not a4.fits

    chosen = choose_sheet(tall, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)
    assert chosen.sheet is A3_LANDSCAPE
    # On the sheet it climbed to, the drawn content clears the title block.
    assert chosen.content[3] <= chosen.title_block[1]


def test_a_panel_of_many_rows_is_not_judged_to_fit_a_sheet_its_chain_stack_overruns():
    """The stack of row chains is clamped to half the box the drawing occupies,
    so that box has to be the one the demand is then tested against. Capped
    against one box and tested against a wider one, a stack that wants 390 mm
    of chains reports fitting 277 mm of paper.
    """
    from stompdrill.emitters.drawing.layout import BOTTOM_BASE, ROW_PITCH, TOP_ALLOWANCE

    rows = 24
    data = rows_panel(rows)
    assert len(data.rows()) == rows, "the fixture has to stack that many chains"

    a4 = Layout.for_sheet(A4_PORTRAIT, data, scale=1.0, frame=FrameStyle.ISO_5457)
    assert not a4.fits

    chosen = choose_sheet(data, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)
    box_h = chosen.area[3] - chosen.area[1]
    assert chosen.needed_height <= box_h
    # What the demand reserved for the chains, read back out of the demand.
    reserved = chosen.needed_height - (60.0 * chosen.scale + TOP_ALLOWANCE)
    assert reserved == pytest.approx(min(BOTTOM_BASE + ROW_PITCH * rows, box_h / 2.0))


def test_rows_drilled_to_one_pattern_reserve_one_chain_between_them():
    """The stack reserves per chain, not per row.

    Twelve rows drilled alike are one chain, so the drawing keeps the height
    eleven further bands would have taken from it — and a panel is no longer
    driven onto larger paper by rows whose dimensions it never draws.
    """
    from stompdrill.emitters.drawing.layout import BOTTOM_BASE, ROW_PITCH, TOP_ALLOWANCE

    count = 12
    alike = make_data(
        *(
            at(sign * 20_000_000, (index - count // 2) * 2_000_000, index=index * 2 + step + 1)
            for index in range(count)
            for step, sign in enumerate((-1, 1))
        ),
        reference=outline(80_000_000, 60_000_000),
    )
    assert len(alike.rows()) == count, "the fixture has to be that many rows"

    layout = Layout.for_sheet(A4_PORTRAIT, alike, scale=1.0, frame=FrameStyle.ISO_5457)
    reserved = layout.needed_height - (60.0 * layout.scale + TOP_ALLOWANCE)

    assert reserved == pytest.approx(BOTTOM_BASE + ROW_PITCH), "one chain's band"
    assert reserved < BOTTOM_BASE + ROW_PITCH * count, "not one band per row"


def test_the_plain_sheet_is_still_measured_against_the_whole_drawing_space():
    """``PLAIN`` rules its schedule and notes inside the space and has always
    been measured against the whole of it; the SVG sheet depends on that.
    """
    data = panel(170_000_000, 60_000_000)
    plain = Layout.for_sheet(A4_LANDSCAPE, data, scale=1.0)

    assert plain.needed_width > plain.area[2] - plain.area[0]
    assert plain.fits


def test_the_sheet_a_panel_takes_does_not_depend_on_how_many_diagnostics_it_has():
    """A panel that accumulated warnings did not get bigger.

    The ISO notes band is a fixed depth and states a count for the notes it
    cannot show, exactly as the schedule and the chain stack do, so the paper a
    panel needs is a fact about the panel rather than about its findings.
    """
    from stompdrill.model import Diagnostic

    data = panel(112_400_000, 60_500_000)
    noisy = data.with_diagnostics(
        *(Diagnostic.warning("off-grid", f"hole {n} moved 0.120 mm to the grid")
          for n in range(1, 21))
    )

    quiet = choose_sheet(data, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)
    loud = choose_sheet(noisy, ISO_5457_CANDIDATES, frame=FrameStyle.ISO_5457)

    assert quiet.sheet is A4_PORTRAIT
    assert loud.sheet is quiet.sheet
    assert loud.notes == quiet.notes
    assert loud.area == quiet.area
