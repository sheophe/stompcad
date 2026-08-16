"""The sheet solver, run in both directions."""

from __future__ import annotations

import pytest

from aidrill.emitters.drawing.layout import Layout, choose_sheet, content_half_extents
from aidrill.emitters.drawing.sheet import (
    A0_LANDSCAPE,
    A3_LANDSCAPE,
    A4_LANDSCAPE,
    A4_PORTRAIT,
    ISO_5457_CANDIDATES,
    FrameStyle,
)
from aidrill.model import ReferenceOutline
from aidrill.units import Nanometre
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
    """A4's drawing space is 180 wide; 300 mm of panel cannot be drawn 1:1 on it."""
    layout = choose_sheet(panel(300_000_000, 200_000_000), ISO_5457_CANDIDATES,
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

    assert layout.scale in (1.0, 2.0)
    assert layout.fits


def test_a_fitted_scale_is_rounded_down_to_a_readable_one():
    """A title block says 1:2, never 1:2.37, and rounding down cannot overflow."""
    from aidrill.emitters.drawing.layout import PREFERRED_SCALES, preferred_scale

    assert preferred_scale(2.4) == 2.0
    assert preferred_scale(0.9) == 0.5
    assert all(preferred_scale(value) <= value for value in (0.3, 1.7, 7.9, 23.0))
    assert preferred_scale(0.001) not in PREFERRED_SCALES  # below the ladder, kept raw


def test_a_degenerate_scale_request_falls_back_to_one_to_one():
    from aidrill.emitters.drawing.layout import preferred_scale

    assert preferred_scale(0.0) == 1.0
    assert preferred_scale(float("inf")) == 20.0
    assert preferred_scale(float("nan")) == 1.0


# --- shared ---------------------------------------------------------------


def test_an_empty_panel_still_has_a_drawable_extent():
    """A 5 mm floor, so a panel with nothing on it does not divide by zero."""
    from aidrill.model import DrillData

    assert content_half_extents(DrillData()) == (5.0, 5.0)


def test_extents_include_each_hole_radius_not_just_its_centre():
    """A hole at the edge is half a diameter wider than its centre says."""
    data = make_data(at(50_000_000, 0, 10_000_000, index=1))

    half_width, _ = content_half_extents(data)

    assert half_width == pytest.approx(55.0)


def test_the_scale_label_reads_as_an_engineer_writes_it():
    layout = Layout.for_sheet(A4_PORTRAIT, panel(100_000_000, 50_000_000),
                              scale=1.0, frame=FrameStyle.ISO_5457)
    assert layout.scale_label == "1:1"

    half = Layout.for_sheet(A4_PORTRAIT, panel(100_000_000, 50_000_000), scale=0.5)
    assert half.scale_label == "1:2"

    twice = Layout.for_sheet(A4_PORTRAIT, panel(10_000_000, 5_000_000), scale=2.0)
    assert twice.scale_label == "2:1"
