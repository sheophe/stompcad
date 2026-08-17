"""The pens a sheet is drawn with, and the ISO 128-24 distinctions they carry."""

from __future__ import annotations

import pytest

from aidrill.emitters.drawing.build import (
    CENTRELINE_DASHES,
    SheetText,
    balloon_overhang,
    build_scene,
    pens_for,
)
from aidrill.emitters.drawing.layout import (
    CHAIN_STANDOFF,
    LEVEL_CHAIN_LABEL,
    MAX_BALLOON_OVERHANG,
    RIGHT_ALLOWANCE,
    Layout,
)
from aidrill.emitters.drawing.scene import (
    FEINT,
    INK,
    Circle,
    Group,
    Item,
    Line,
    Polygon,
    Stroke,
    Text,
)
from aidrill.emitters.drawing.sheet import A3_LANDSCAPE, GROUP_0_7, FrameStyle, LineGroup
from aidrill.model import DrillData, Hole, ReferenceOutline
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


def test_the_overall_dimension_lines_span_the_outline_they_label():
    """The number and the span are one claim, and only the number is read.

    A dimension line drawn over two thirds of the panel still prints 60.000, so
    nothing about the label catches it: the line has to be measured against the
    outline it dimensions.
    """
    data = _panel()
    layout = Layout.for_sheet(A3_LANDSCAPE, data, scale=1.0, frame=FrameStyle.PLAIN)
    items = build_scene(layout, data, SheetText()).items

    dimensions = next(i for i in items if isinstance(i, Group) and i.cls == "dimensions")
    overall = next(
        i for i in dimensions.items if isinstance(i, Group) and i.cls == "dim-overall-group"
    )
    lines = [i for i in overall.items if isinstance(i, Line) and i.cls == "dim-line"]
    horizontal = next(line for line in lines if line.y1 == line.y2)
    vertical = next(line for line in lines if line.x1 == line.x2)

    # 60 x 40 mm at 1:1, centred: the ends are the outline's own edges.
    assert (horizontal.x1, horizontal.x2) == (
        layout.point(-30.0, 0.0)[0],
        layout.point(30.0, 0.0)[0],
    )
    assert (vertical.y1, vertical.y2) == (
        layout.point(0.0, 20.0)[1],
        layout.point(0.0, -20.0)[1],
    )


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


# ---------------------------------------------------------------------------
# the chain of row levels
# ---------------------------------------------------------------------------


def _levelled(*holes: Hole, height_nm: int = 40_000_000) -> DrillData:
    """A 60 mm panel of the given height, carrying the holes it was handed."""
    return DrillData(
        holes=holes,
        reference=ReferenceOutline.from_measurement(Nanometre(60_000_000), Nanometre(height_nm)),
    )


def _scene(data: DrillData, scale: float = 1.0) -> tuple[Layout, tuple[Item, ...]]:
    layout = Layout.for_sheet(A3_LANDSCAPE, data, scale=scale, frame=FrameStyle.PLAIN)
    return layout, build_scene(layout, data, SheetText()).items


def _dimensions(items: tuple[Item, ...]) -> tuple[Item, ...]:
    return next(i for i in items if isinstance(i, Group) and i.cls == "dimensions").items


def _level_chain(items: tuple[Item, ...]) -> Group | None:
    return next(
        (i for i in _dimensions(items) if isinstance(i, Group) and i.cls == "dim-chain-y"), None
    )


def _levels(items: tuple[Item, ...]) -> list[str]:
    chain = _level_chain(items)
    assert chain is not None, "the panel was expected to carry a chain of levels"
    return [i.content for i in chain.items if isinstance(i, Text) and i.cls == "dim-text"]


def _chain_x(items: tuple[Item, ...]) -> float:
    chain = _level_chain(items)
    assert chain is not None, "the panel was expected to carry a chain of levels"
    lines = [i for i in chain.items if isinstance(i, Line) and i.cls == "dim-line"]
    assert lines and all(line.x1 == line.x2 == lines[0].x1 for line in lines)
    return lines[0].x1


def _balloon_reach(items: tuple[Item, ...]) -> float:
    """The rightmost ink any balloon puts on the sheet."""
    holes = next(i for i in items if isinstance(i, Group) and i.cls == "holes")
    return max(i.cx + i.r for i in holes.items if isinstance(i, Circle) and i.cls == "balloon")


def test_the_level_chain_states_every_row_and_both_outline_edges():
    """The Y the row chains never state: each row's own height up the panel."""
    _, items = _scene(_levelled(at(0, 10_000_000, index=1), at(20_000_000, -15_000_000, index=2)))

    # 40 mm tall, so the edges are ±20 and the stations run -20, -15, 10, 20.
    assert _levels(items) == ["5.000", "25.000", "10.000"]


def test_the_level_chain_extends_every_station_it_dimensions():
    """Four stations, four extension lines, each at its own station's height."""
    layout, items = _scene(_levelled(at(0, 10_000_000, index=1), at(0, -15_000_000, index=2)))
    chain = _level_chain(items)
    assert chain is not None

    extensions = [i for i in chain.items if isinstance(i, Line) and i.cls == "extension"]
    assert sorted(line.y1 for line in extensions) == sorted(
        layout.point(0.0, y)[1] for y in (-20.0, -15.0, 10.0, 20.0)
    )
    assert all(line.y1 == line.y2 for line in extensions), "a level's extension runs flat"


def test_a_level_s_extension_leaves_the_first_hole_on_its_row():
    """A row chain's extension leaves the hole it dimensions, so a level's does.

    It leaves the *first* hole rather than the last, so that on its way out to
    the chain it passes through every hole on the row and the reader can see
    which holes the level was measured to. Leaving the outline instead would
    draw the same line whatever the row held.
    """
    layout, items = _scene(
        _levelled(
            at(-10_000_000, 10_000_000, index=1),
            at(25_000_000, 10_000_000, index=2),
            at(5_000_000, -15_000_000, index=3),
            at(20_000_000, -15_000_000, index=4),
        )
    )
    chain = _level_chain(items)
    assert chain is not None
    starts = {
        round(line.y1, 6): line.x1
        for line in chain.items
        if isinstance(line, Line) and line.cls == "extension"
    }

    def leaves(y: float) -> float:
        return starts[round(layout.point(0.0, y)[1], 6)]

    assert leaves(10.0) == pytest.approx(layout.point(-10.0, 0.0)[0]), "not the row's last"
    assert leaves(-15.0) == pytest.approx(layout.point(5.0, 0.0)[0]), "not the row's last"
    # The outline's own edges carry no hole, so they leave the outline. They are
    # the panel's top and bottom, so a line drawn across would sit on the
    # outline itself; it starts at the corner the chain stands beyond instead.
    assert leaves(20.0) == pytest.approx(layout.point(30.0, 0.0)[0])
    assert leaves(-20.0) == pytest.approx(layout.point(30.0, 0.0)[0])


def test_an_edge_station_leaves_the_outline_and_not_the_content_extent():
    """A hole hanging over the edge widens the content but not the panel.

    The station is the outline's own edge, so that is where its extension line
    starts; leaving the content extent would begin the line out in space beside
    a panel the drawing says is 60 mm wide.
    """
    layout, items = _scene(_levelled(at(32_000_000, 0, index=1)))
    chain = _level_chain(items)
    assert chain is not None

    outline_x = layout.point(30.0, 0.0)[0]
    content_x = layout.point(layout.half_width, 0.0)[0]
    assert content_x > outline_x, "this fixture needs the hole to hang over the edge"

    top = min(
        (line for line in chain.items if isinstance(line, Line) and line.cls == "extension"),
        key=lambda line: line.y1,
    )
    assert top.x1 == pytest.approx(outline_x)


def test_the_level_chain_is_absent_when_the_panel_has_no_holes():
    """Two stations would restate the height the overall dimension already gives."""
    _, items = _scene(_levelled())

    assert _level_chain(items) is None


@pytest.mark.parametrize("scale", [1.0, 0.5, 4.0])
def test_the_level_chain_measures_stations_not_scaled_sheet_coordinates(scale: float):
    """The subtraction is the stations', so the printed value survives the scale."""
    _, items = _scene(_levelled(at(0, 10_000_000, index=1)), scale)

    assert _levels(items) == ["30.000", "10.000"]


def test_two_holes_on_one_level_are_one_station():
    """Rows group by exact Y, so a shared level is dimensioned once, not twice."""
    _, items = _scene(
        _levelled(at(-10_000_000, 10_000_000, index=1), at(10_000_000, 10_000_000, index=2))
    )

    assert _levels(items) == ["30.000", "10.000"]


def test_a_row_level_on_the_outline_edge_is_not_a_second_station():
    """Exact nanometre equality collapses the hole's level into the edge's."""
    _, items = _scene(_levelled(at(0, 20_000_000, index=1)))

    assert _levels(items) == ["40.000"], "one span edge to edge, not a zero beside it"


def _row_chains(items: tuple[Item, ...]) -> list[Group]:
    return [i for i in _dimensions(items) if isinstance(i, Group) and i.cls == "dim-chain"]


def _corners() -> DrillData:
    """Four holes at the corners of a rectangle: two rows, one pattern of X."""
    return _levelled(
        at(-25_000_000, 15_000_000, index=1),
        at(25_000_000, 15_000_000, index=2),
        at(-25_000_000, -15_000_000, index=3),
        at(25_000_000, -15_000_000, index=4),
        height_nm=50_000_000,
    )


def test_two_rows_drilled_to_one_pattern_share_one_chain():
    """Drawn twice it states the same distances twice.

    The second chain takes a second band of the sheet to say nothing the first
    has not, so the panel's drawing grows without its dimensions gaining a fact.
    """
    data = _corners()
    _, items = _scene(data)
    chains = _row_chains(items)

    assert len(data.rows()) == 2, "the fixture has to be two rows"
    assert len(chains) == 1
    assert [t.content for t in chains[0].items if isinstance(t, Text)] == [
        "5.000",
        "50.000",
        "5.000",
    ]


def test_rows_of_different_patterns_keep_a_chain_each():
    """Only an identical pattern is a repeat; a different one is a fact."""
    data = _levelled(
        at(-25_000_000, 15_000_000, index=1),
        at(25_000_000, 15_000_000, index=2),
        at(-10_000_000, -15_000_000, index=3),
        height_nm=50_000_000,
    )
    _, items = _scene(data)

    assert len(_row_chains(items)) == 2


def test_the_stack_places_a_chain_by_the_lowest_row_it_serves():
    """Chains stack away from the panel as the rows they dimension do.

    A chain serving two rows is placed by the lower of them. Placed by the
    upper it would be filed behind a chain whose rows are entirely above its
    own, and the two would reach past each other to their stations.
    """
    _, items = _scene(
        _levelled(
            at(-25_000_000, 20_000_000, index=1),
            at(25_000_000, 20_000_000, index=2),
            at(-10_000_000, 0, index=3),
            at(-25_000_000, -20_000_000, index=4),
            at(25_000_000, -20_000_000, index=5),
            height_nm=50_000_000,
        )
    )
    chains = _row_chains(items)
    assert len(chains) == 2, "the outer rows share a pattern, the middle one differs"

    def labels(chain: Group) -> list[str]:
        return [i.content for i in chain.items if isinstance(i, Text)]

    def dim_y(chain: Group) -> float:
        return next(i for i in chain.items if isinstance(i, Line) and i.cls == "dim-line").y1

    # The shared chain reaches down to -20, below the middle row, so it is the
    # one nearest the panel however high its other row sits.
    assert labels(chains[0]) == ["5.000", "50.000", "5.000"]
    assert labels(chains[1]) == ["20.000", "40.000"]
    assert dim_y(chains[0]) < dim_y(chains[1]), "drawn in the order they stack outwards"


def test_a_shared_chain_s_extensions_leave_the_highest_row_it_serves():
    """Eager, as the chain of levels is.

    On the way down the line passes through every row's holes at that station,
    so the reader can see which rows the one chain was drawn for.
    """
    layout, items = _scene(_corners())
    (chain,) = _row_chains(items)

    extensions = [i for i in chain.items if isinstance(i, Line) and i.cls == "extension"]
    assert extensions
    assert all(line.y1 == pytest.approx(layout.point(0.0, 15.0)[1]) for line in extensions), (
        "not the lower row it also serves"
    )


def test_both_chains_stand_off_the_panel_by_the_same_distance():
    """Below and beside are one system, so they stand off alike.

    Two literals that happened to agree would let one drift from the other and
    leave the sheet's dimensions ruled at two different distances out.
    """
    layout, items = _scene(_levelled(at(0, 10_000_000, index=1)))
    row = next(i for i in _dimensions(items) if isinstance(i, Group) and i.cls == "dim-chain")
    below = next(i for i in row.items if isinstance(i, Line) and i.cls == "dim-line")

    content_bottom = layout.point(0.0, -layout.half_height)[1]
    content_right = layout.point(layout.half_width, 0.0)[0]

    assert below.y1 - content_bottom == pytest.approx(_chain_x(items) - content_right)


def test_a_level_s_arrowheads_sit_on_its_stations_and_point_outward():
    """The tip is on the station and the tail lies inside the span it measures.

    Reversed, the pair reads as a distance measured from nothing — and nothing
    about the printed value catches it, because the value is a subtraction.
    """
    _, items = _scene(_levelled(at(0, 20_000_000, index=1)))
    chain = _level_chain(items)
    assert chain is not None

    line = next(i for i in chain.items if isinstance(i, Line) and i.cls == "dim-line")
    heads = [i for i in chain.items if isinstance(i, Polygon) and i.cls == "arrow"]
    assert len(heads) == 2, "one span, so one arrowhead at each of its two ends"

    span = sorted((line.y1, line.y2))
    middle = sum(span) / 2.0
    for head in heads:
        (_, tip_y), *tail = head.points
        assert tip_y in span, "a tip belongs on a station, not along the line"
        assert all(abs(y - middle) < abs(tip_y - middle) for _, y in tail)


def test_the_level_chain_hugs_the_panel_when_the_balloons_stay_inside_it():
    """Most panels keep every balloon within the outline.

    The chain stands outboard of the balloons, so on such a panel it must stand
    off the outline itself — reserving the worst case would leave it floating in
    a gap nothing occupies.
    """
    layout, items = _scene(_levelled(at(0, 10_000_000, index=1)))
    content_right = layout.point(layout.half_width, 0.0)[0]

    assert _balloon_reach(items) < content_right, "this fixture needs its balloon inside"
    assert _chain_x(items) == pytest.approx(content_right + CHAIN_STANDOFF)


def test_the_level_chain_clears_a_balloon_that_escapes_the_outline():
    """A hole hard against the right edge throws its balloon past the panel."""
    layout, items = _scene(_levelled(at(26_500_000, 0, index=1)))
    reach = _balloon_reach(items)

    assert reach > layout.point(layout.half_width, 0.0)[0], "this fixture needs it outside"
    assert _chain_x(items) == pytest.approx(reach + CHAIN_STANDOFF)


@pytest.mark.parametrize(
    "hole",
    [
        pytest.param(at(0, 0, index=1), id="centred"),
        pytest.param(at(26_500_000, 0, index=1), id="against-the-edge"),
        # Small enough that the drawn radius is the floor rather than the hole,
        # which is the case the bound is at its widest for.
        pytest.param(at(29_999_500, 0, 1_000, index=1), id="floored-radius"),
    ],
)
@pytest.mark.parametrize("scale", [1.0, 0.25, 2.0])
def test_the_level_chain_and_its_label_stay_inside_the_right_allowance(hole: Hole, scale: float):
    """Placement is measured, but the width budget is the scale-free bound.

    ``RIGHT_ALLOWANCE`` is reserved before the scale is known, so it cannot be
    the measured overhang. The two agree only while the measurement stays under
    the bound the reservation is built from, which is what this checks.
    """
    layout, items = _scene(_levelled(hole), scale)
    content_right = layout.point(layout.half_width, 0.0)[0]

    assert balloon_overhang(layout, _levelled(hole)) <= MAX_BALLOON_OVERHANG
    assert _chain_x(items) + LEVEL_CHAIN_LABEL <= content_right + RIGHT_ALLOWANCE


def test_the_balloon_overhang_never_reports_a_balloon_pulled_inside_the_panel():
    """It answers how far past the outline the balloons reach, not how far short."""
    data = _levelled(at(0, 0, index=1))
    layout, _ = _scene(data)

    assert balloon_overhang(layout, data) == 0.0
