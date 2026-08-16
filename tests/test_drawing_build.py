"""The pens a sheet is drawn with, and the ISO 128-24 distinctions they carry."""

from __future__ import annotations

from aidrill.emitters.drawing.build import SheetText, build_scene, pens_for
from aidrill.emitters.drawing.layout import Layout
from aidrill.emitters.drawing.scene import FEINT, INK, Group, Item, Line, Stroke
from aidrill.emitters.drawing.sheet import (
    A3_LANDSCAPE,
    GRID_LINE_WIDTH,
    GROUP_0_7,
    FrameStyle,
    LineGroup,
)
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
    """A second group, so the first assertion cannot be passing on a constant."""
    seven = pens_for(GROUP_0_7, FrameStyle.ISO_5457)
    assert (seven.outline.width, seven.dimension.width) == (0.7, GRID_LINE_WIDTH)
    assert seven.frame.width == 0.7

    half = pens_for(LineGroup(0.5, 0.25), FrameStyle.ISO_5457)
    assert (half.outline.width, half.dimension.width) == (0.5, 0.25)
    assert half.centreline.dashes and half.feint.colour == FEINT


def test_a_hole_s_centre_mark_is_not_the_pen_the_panel_s_axes_are_drawn_with():
    """ISO 128-24 Table 1 separates 01.1.7 short centre lines from 04.1.1.

    The first is continuous narrow, the second long-dashed dotted, so under the
    ISO frame the two must differ. Under ``PLAIN`` they keep the widths the SVG
    sheet has always used, which is why that sheet is unaffected.
    """
    data = _panel()
    for style, mark_width in ((FrameStyle.ISO_5457, GRID_LINE_WIDTH), (FrameStyle.PLAIN, 0.2)):
        layout = Layout.for_sheet(A3_LANDSCAPE, data, scale=1.0, frame=style)
        items = build_scene(layout, data, SheetText()).items

        (axis, _) = _lines(items, "centrelines", "centreline")
        (mark, _) = _lines(items, "holes", "centre-mark")

        assert mark.stroke.width == mark_width
        assert mark.stroke.dashes == (), "a short centre line is continuous"
        assert axis.stroke.dashes, "a centre line of symmetry is long-dashed dotted"
