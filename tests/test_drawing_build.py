"""The pens a sheet is drawn with, and the ISO 128-24 distinctions they carry."""

from __future__ import annotations

from aidrill.emitters.drawing.build import CENTRELINE_DASHES, SheetText, build_scene, pens_for
from aidrill.emitters.drawing.layout import Layout
from aidrill.emitters.drawing.scene import FEINT, INK, Group, Item, Line, Stroke, Text
from aidrill.emitters.drawing.sheet import A3_LANDSCAPE, GROUP_0_7, FrameStyle, LineGroup
from aidrill.model import DrillData, ReferenceOutline
from aidrill.units import Nanometre
from tests.conftest import at


def _panel() -> DrillData:
    return DrillData(
        holes=(at(0, 0, index=4),),
        reference=ReferenceOutline.from_measurement(Nanometre(60_000_000), Nanometre(40_000_000)),
    )


def _lines(scene_items: tuple[Item, ...], group: str, cls: str) -> list[Line]:
    """Every line of one class inside the named top-level group."""
    found = next(i for i in scene_items if isinstance(i, Group) and i.cls == group)
    return [i for i in found.items if isinstance(i, Line) and i.cls == cls]


def test_the_plain_sheet_keeps_the_widths_it_was_always_drawn_with():
    """``PLAIN`` is the SVG sheet, whose rendered output this must not move."""
    pens = pens_for(GROUP_0_7, FrameStyle.PLAIN)

    assert pens.outline == Stroke(0.4, INK)
    assert pens.dimension == Stroke(0.2, INK)
    assert pens.centreline == Stroke(0.25, FEINT, (6.0, 1.5, 1.0, 1.5))
    assert pens.frame == Stroke(0.5, INK)
    assert pens.feint == Stroke(0.15, FEINT)


def test_the_iso_sheet_takes_both_widths_from_the_group_it_was_handed():
    """Every width comes from the group, not from a constant that happens to match.

    ``GROUP_0_7.narrow`` and ISO 5457's grid reference line are both 0,35 by
    coincidence of two standards. The group is what ``pens_for`` reads.
    """
    seven = pens_for(GROUP_0_7, FrameStyle.ISO_5457)
    assert seven.outline.width == GROUP_0_7.wide
    assert seven.dimension.width == GROUP_0_7.narrow
    assert seven.centreline.width == GROUP_0_7.narrow
    assert seven.frame.width == GROUP_0_7.wide
    assert seven.feint.width == GROUP_0_7.narrow

    # A second group, so none of the above can be passing on a constant.
    half = pens_for(LineGroup(0.5, 0.25), FrameStyle.ISO_5457)
    assert half.outline.width == 0.5
    assert half.dimension.width == 0.25
    assert half.centreline.width == 0.25
    assert half.frame.width == 0.5
    assert half.feint.width == 0.25
    assert half.feint.colour == FEINT


def test_the_iso_centreline_is_long_dashed_dotted_and_drawn_in_ink():
    """04.1.1 is a line of the drawing, so it is inked, not a receding grey.

    No emitter renders an ISO sheet yet, so neither the colour nor the pattern
    has any output to be caught in. They are pinned here or nowhere.
    """
    centreline = pens_for(GROUP_0_7, FrameStyle.ISO_5457).centreline

    assert centreline.colour == INK
    assert centreline.dashes == CENTRELINE_DASHES
    # The constant itself, or the assertion above holds for any pattern at all.
    # Long dash, gap, dot, gap — the proportions ISO 128-24 gives for 04.1.
    assert CENTRELINE_DASHES == (12.0, 3.0, 1.0, 3.0)

    assert pens_for(LineGroup(0.5, 0.25), FrameStyle.ISO_5457).centreline.dashes == (
        CENTRELINE_DASHES
    ), "the pattern is the standard's, so a narrower group does not change it"


def test_a_hole_s_centre_mark_is_not_the_pen_the_panel_s_axes_are_drawn_with():
    """ISO 128-24 Table 1 separates 01.1.7 short centre lines from 04.1.1.

    The first is continuous narrow, the second long-dashed dotted, so under the
    ISO frame the two must differ. Under ``PLAIN`` they keep the widths the SVG
    sheet has always used, which is why that sheet is unaffected.
    """
    data = _panel()
    for style, mark_width in ((FrameStyle.ISO_5457, GROUP_0_7.narrow), (FrameStyle.PLAIN, 0.2)):
        layout = Layout.for_sheet(A3_LANDSCAPE, data, scale=1.0, frame=style)
        items = build_scene(layout, data, SheetText()).items

        (axis, _) = _lines(items, "centrelines", "centreline")
        (mark, _) = _lines(items, "holes", "centre-mark")

        assert mark.stroke.width == mark_width
        assert mark.stroke.dashes == (), "a short centre line is continuous"
        assert axis.stroke.dashes, "a centre line of symmetry is long-dashed dotted"


def test_the_overflow_marker_states_the_layout_s_own_scale_not_a_pdf_literal():
    """The PDF sheet is always 1:1, but the same marker also serves the SVG
    sheet, which a caller can draw at any explicit scale. A panel too large
    for its sheet even at 20:1 must be reported at 20:1, not at a hardcoded
    1:1 — a drawing that misstates its own scale is worse than a plain one.
    """
    data = DrillData(
        holes=(at(0, 0, index=1),),
        reference=ReferenceOutline.from_measurement(
            Nanometre(200_000_000), Nanometre(150_000_000)
        ),
    )
    layout = Layout.for_sheet(A3_LANDSCAPE, data, scale=20.0, frame=FrameStyle.PLAIN)
    assert not layout.fits, "the test needs an overflowing layout to exercise the marker"

    items = build_scene(layout, data, SheetText()).items
    notes = next(i for i in items if isinstance(i, Group) and i.cls == "notes")
    marker = next(
        i
        for i in notes.items
        if isinstance(i, Text) and i.cls == "note note-overflow" and "CONTENT EXCEEDS" in i.content
    )

    assert marker.content.startswith("SCALE 20:1")
    assert "SCALE 1:1" not in marker.content
