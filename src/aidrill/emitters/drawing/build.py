"""Resolve a layout and a panel into the marks that describe them.

Every decision about what appears on the sheet is here; a backend only chooses
how to write a ``Line``. Coordinates are sheet millimetres with Y running down,
which is what ``Layout.point`` returns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from ...model import DrillData, Severity
from ...units import Nanometre, format_nm, mm_from_nm
from .content import (
    POSITION_DECIMALS,
    TITLE_BLOCK_COLUMNS,
    TITLE_CELL_PADDING,
    TITLE_LABEL_FONT,
    TITLE_VALUE_FONT,
    SheetText,
    allot,
    capacity,
    enclosure_note,
    fit_font,
    fits,
    flagged_holes,
    grid_note,
    is_flagged,
    note_lines,
    schedule_rows,
    title_cell_width,
    title_fields,
    tool_summary,
)
from .layout import ROW_PITCH, TITLE_MIN_FONT, Layout
from .scene import FEINT, INK, RED, Circle, Group, Item, Line, Polygon, Rect, Scene, Stroke, Text
from .sheet import (
    CENTRING_MARK_OVERSHOOT,
    CENTRING_MARK_WIDTH,
    FILING_BORDER,
    GRID_CHARACTER_SIZE,
    GRID_LETTERS,
    GRID_LINE_WIDTH,
    GROUP_0_7,
    PLAIN_BORDER,
    TRIM_MARK_LONG,
    TRIM_MARK_SHORT,
    FrameStyle,
    LineGroup,
    Sheet,
    grid_divisions,
)

# ``SheetText`` is defined in ``content`` and re-exported here: ``build`` imports
# ``content``, so defining it in this module would make that import a cycle.
__all__ = [
    "SheetText",
    "build_scene",
    "Pens",
    "pens_for",
    "CENTRELINE_DASHES",
    "FURNITURE",
    "DUP_RING",
    "arrow",
    "iso_frame_items",
    "grid_reference_items",
]


@dataclass(frozen=True, slots=True)
class Pens:
    """The strokes one sheet is drawn with, in ISO 128-24 terms."""

    #: 01.2 continuous wide: visible edges and outlines.
    outline: Stroke
    #: 01.1 continuous narrow: dimension, extension and leader lines.
    dimension: Stroke
    #: 04.1 long-dashed dotted narrow: centre lines and lines of symmetry.
    centreline: Stroke
    #: 4.2 of ISO 5457, which asks for the wide width by name.
    frame: Stroke
    #: 01.1 narrow again, for extension lines that should recede.
    feint: Stroke


#: ISO 128-24 gives the proportions of a long-dashed dotted line rather than
#: absolute lengths. These are the conventional ones for this group.
CENTRELINE_DASHES: tuple[float, ...] = (12.0, 3.0, 1.0, 3.0)

#: A third width, between the wide outline and the narrow dimension pen, for the
#: sheet's own furniture: the boxes it rules, the origin mark and a balloon's
#: edge. Not a member of ``Pens``, because none of it is a line ISO 128-24 names.
FURNITURE = Stroke(0.3, INK)

#: A duplicate is ringed rather than merely coloured, so that the finding
#: survives a monochrome print of the sheet.
DUP_RING = Stroke(0.3, RED, (1.2, 1.2))


def pens_for(group: LineGroup, style: FrameStyle) -> Pens:
    """Build the sheet's strokes from a line group.

    ``PLAIN`` is a sheet with no standard frame, so its widths are chosen by eye
    and stated here; only ``ISO_5457`` has a group to take them from.
    """
    if style is FrameStyle.PLAIN:
        return Pens(
            outline=Stroke(0.4, INK),
            dimension=Stroke(0.2, INK),
            centreline=Stroke(0.25, FEINT, (6.0, 1.5, 1.0, 1.5)),
            frame=Stroke(0.5, INK),
            feint=Stroke(0.15, FEINT),
        )
    return Pens(
        outline=Stroke(group.wide, INK),
        dimension=Stroke(group.narrow, INK),
        centreline=Stroke(group.narrow, INK, CENTRELINE_DASHES),
        frame=Stroke(group.wide, INK),
        feint=Stroke(group.narrow, FEINT),
    )


def arrow(x: float, y: float, dx: float, dy: float) -> Polygon:
    """A closed filled arrowhead at (x, y) pointing along the unit vector.

    Always inked: a dimension line is 01.1 whatever it measures, and a
    diagnostic is carried by the schedule row and the notes, never by the
    colour of an arrowhead.
    """
    length, half = 2.2, 0.7
    tail_x, tail_y = x + dx * length, y + dy * length
    px, py = -dy * half, dx * half
    return Polygon(
        ((x, y), (tail_x + px, tail_y + py), (tail_x - px, tail_y - py)),
        INK,
        cls="arrow",
    )


def build_scene(layout: Layout, data: DrillData, options: SheetText) -> Scene:
    """Resolve everything the sheet shows, in draw order."""
    pens = pens_for(GROUP_0_7, layout.frame)
    items: list[Item] = []
    items += _build_frame(layout, pens)
    items += _build_outlines(layout, data, pens)
    items += _build_centrelines(layout, pens)
    items += _build_holes(layout, data, pens)
    items += _build_dimensions(layout, data, pens)
    items += _build_schedule(layout, data, pens)
    items += _build_title_block(layout, data, pens, options)
    items += _build_notes(layout, data)
    return Scene(layout.sheet, tuple(items))


# ---------------------------------------------------------------------------
# frame and outlines
# ---------------------------------------------------------------------------


def _build_frame(layout: Layout, pens: Pens) -> list[Item]:
    """One border for a plain sheet; the full ISO 5457 furniture otherwise."""
    if layout.frame is FrameStyle.ISO_5457:
        return iso_frame_items(layout, pens)
    x0, y0, x1, y1 = layout.border
    return [Rect(x0, y0, x1 - x0, y1 - y0, pens.frame, cls="border")]


def iso_frame_items(layout: Layout, pens: Pens) -> list[Item]:
    """The ISO 5457 sheet furniture: frame, centring marks, trimming marks.

    Everything here is measured on the trimmed sheet, which is the sheet's own
    extent; the frame is the tabulated drawing space inside it.
    """
    sheet = layout.sheet
    x0, y0, x1, y1 = sheet.space
    items: list[Item] = [
        Rect(x0, y0, x1 - x0, y1 - y0, pens.frame, cls="iso-frame"),
    ]
    items += _centring_marks(sheet, x0, y0, x1, y1)
    items += _trim_marks(sheet)
    items += grid_reference_items(sheet)
    items.append(
        Text(
            sheet.width - PLAIN_BORDER,
            sheet.height - PLAIN_BORDER / 3.0,
            sheet.name,
            2.5,
            anchor="end",
            cls="size-designation",
        )
    )
    return items


def _centring_marks(sheet: Sheet, x0: float, y0: float, x1: float, y1: float) -> list[Item]:
    """4.3: on both axes of symmetry, from the trimmed edge past the frame."""
    pen = Stroke(CENTRING_MARK_WIDTH, INK)
    mid_x, mid_y = sheet.width / 2.0, sheet.height / 2.0
    reach = CENTRING_MARK_OVERSHOOT
    return [
        Line(mid_x, 0.0, mid_x, y0 + reach, pen, cls="centring-mark"),
        Line(mid_x, sheet.height, mid_x, y1 - reach, pen, cls="centring-mark"),
        Line(0.0, mid_y, x0 + reach, mid_y, pen, cls="centring-mark"),
        Line(sheet.width, mid_y, x1 - reach, mid_y, pen, cls="centring-mark"),
    ]


def _trim_marks(sheet: Sheet) -> list[Item]:
    """4.5: two overlapping 10 x 5 rectangles in the border at each edge.

    Each pair straddles the corner it marks, so the L it forms opens away from
    the sheet and a guillotine set to either arm cuts to the same point.
    """
    marks: list[Item] = []
    for corner_x, corner_y in (
        (0.0, 0.0),
        (sheet.width, 0.0),
        (0.0, sheet.height),
        (sheet.width, sheet.height),
    ):
        for width, height in ((TRIM_MARK_LONG, TRIM_MARK_SHORT), (TRIM_MARK_SHORT, TRIM_MARK_LONG)):
            # Both arms run inwards from the corner, whichever corner it is.
            x = corner_x if corner_x == 0.0 else corner_x - width
            y = corner_y if corner_y == 0.0 else corner_y - height
            marks.append(_filled_box(x, y, width, height))
    return marks


def _filled_box(x: float, y: float, width: float, height: float) -> Polygon:
    return Polygon(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
        INK,
        cls="trim-mark",
    )


def grid_reference_items(sheet: Sheet) -> list[Item]:
    """4.4: fields lettered down and numbered across, in the border band.

    A4 carries its references at the top and the right only; every larger sheet
    carries them on both sides. Field boundaries come from ``grid_divisions``,
    which puts the division's remainder in the corner fields.
    """
    across, down = sheet.grid_fields
    if not across or not down:
        return []
    both_sides = sheet.name != "A4"
    items: list[Item] = []
    items += _grid_axis(sheet, across, horizontal=True, both_sides=both_sides)
    items += _grid_axis(sheet, down, horizontal=False, both_sides=both_sides)
    return items


def _grid_axis(sheet: Sheet, count: int, *, horizontal: bool, both_sides: bool) -> list[Item]:
    extent = sheet.width if horizontal else sheet.height
    other = sheet.height if horizontal else sheet.width
    pen = Stroke(GRID_LINE_WIDTH, INK)
    items: list[Item] = []

    edges = [0.0]
    for field in grid_divisions(extent, count):
        edges.append(edges[-1] + field)

    #: The band the characters sit in, measured inwards from the frame rather
    # than outwards from the trimmed edge. 4.2 widens the left edge to 20 mm
    # "including the frame ... used as a filing margin", and that margin lies
    # outside the grid reference border, so every band is the same depth and
    # the left one simply starts 10 mm further in.
    near = PLAIN_BORDER if horizontal else FILING_BORDER
    near_edge = near - PLAIN_BORDER
    far = other - PLAIN_BORDER
    for boundary in edges[1:-1]:
        if horizontal:
            items.append(Line(boundary, near_edge, boundary, near, pen, cls="grid-line"))
            if both_sides:
                items.append(Line(boundary, far, boundary, other, pen, cls="grid-line"))
        else:
            items.append(Line(near_edge, boundary, near, boundary, pen, cls="grid-line"))
            if both_sides:
                items.append(Line(far, boundary, other, boundary, pen, cls="grid-line"))

    for index in range(count):
        centre = (edges[index] + edges[index + 1]) / 2.0
        # Numerals run left to right; letters run from the top downwards.
        label = str(index + 1) if horizontal else GRID_LETTERS[index]
        if horizontal:
            items.append(_grid_label(centre, near - PLAIN_BORDER / 2.0, label))
            if both_sides:
                items.append(_grid_label(centre, other - PLAIN_BORDER / 2.0, label))
        else:
            # A4's letters are on the right; a larger sheet has them on both.
            if both_sides:
                items.append(_grid_label(near - PLAIN_BORDER / 2.0, centre, label))
            items.append(_grid_label(other - PLAIN_BORDER / 2.0, centre, label))
    return items


def _grid_label(x: float, y: float, content: str) -> Text:
    return Text(
        x,
        y + GRID_CHARACTER_SIZE / 3.0,
        content,
        GRID_CHARACTER_SIZE,
        anchor="middle",
        cls="grid-label",
    )


def _build_outlines(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    """Build one panel outline; enclosure identity belongs in the title block."""
    drawn: list[Item] = []
    if data.reference is not None:
        drawn.append(
            _rounded(
                layout,
                mm_from_nm(data.reference.width_nm),
                mm_from_nm(data.reference.height_nm),
                cls="outline",
                stroke=pens.outline,
            )
        )
    return [Group("outlines", tuple(drawn))]


def _rounded(layout: Layout, width: float, height: float, *, cls: str, stroke: Stroke) -> Rect:
    """Place a rounded rectangle from model-millimetre layout geometry."""
    x, y = layout.point(-width / 2.0, height / 2.0)
    radius = min(3.0, width / 4.0, height / 4.0) * layout.scale
    return Rect(
        x,
        y,
        layout.length(width),
        layout.length(height),
        stroke,
        radius=radius,
        cls=cls,
    )


# ---------------------------------------------------------------------------
# centrelines
# ---------------------------------------------------------------------------


def _build_centrelines(layout: Layout, pens: Pens) -> list[Item]:
    over = 4.0
    left, top = layout.point(-layout.half_width, layout.half_height)
    right, bottom = layout.point(layout.half_width, -layout.half_height)
    ox, oy = layout.point(0.0, 0.0)

    drawn: list[Item] = [
        Line(
            max(layout.area[0], left - over),
            oy,
            min(layout.area[2], right + over),
            oy,
            pens.centreline,
            cls="centreline",
        ),
        Line(
            ox,
            max(layout.area[1], top - over),
            ox,
            min(layout.area[3], bottom + over),
            pens.centreline,
            cls="centreline",
        ),
        Circle(ox, oy, 1.6, FURNITURE, cls="origin"),
    ]
    for dx, dy in ((2.6, 0.0), (0.0, 2.6)):
        drawn.append(Line(ox - dx, oy - dy, ox + dx, oy + dy, FURNITURE, cls="origin"))
    drawn.append(Text(ox + 3.0, oy + 4.0, "0,0", 2.2, cls="origin-label"))
    return [Group("centrelines", tuple(drawn))]


# ---------------------------------------------------------------------------
# holes
# ---------------------------------------------------------------------------


def _build_holes(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    drawn: list[Item] = []
    flagged = flagged_holes(data.diagnostics)

    for hole in data.holes:
        cx, cy = layout.point(mm_from_nm(hole.x_nm), mm_from_nm(hole.y_nm))
        radius = max(0.4, layout.length(mm_from_nm(hole.diameter_nm)) / 2.0)
        is_dup = is_flagged(hole, flagged)
        colour = RED if is_dup else INK

        drawn.append(
            Circle(
                cx,
                cy,
                radius,
                Stroke(pens.outline.width, colour),
                cls="hole dup" if is_dup else "hole",
            )
        )
        if is_dup:
            drawn.append(Circle(cx, cy, radius + 1.6, DUP_RING, cls="dup-ring"))

        arm = radius + 1.2
        # ISO 128-24 Table 1 keeps 01.1.7 short centre lines continuous and
        # narrow, which is not the 04.1.1 long-dashed dotted pen the panel's own
        # axes are drawn with. A hole's mark is the first of the two.
        mark = Stroke(pens.dimension.width, colour)
        for dx, dy in ((arm, 0.0), (0.0, arm)):
            drawn.append(Line(cx - dx, cy - dy, cx + dx, cy + dy, mark, cls="centre-mark"))

        drawn += _balloon(cx, cy, radius, hole.index, pens)

    return [Group("holes", tuple(drawn))]


def _balloon(cx: float, cy: float, radius: float, number: int, pens: Pens) -> list[Item]:
    """Place a balloon carrying stable ``Hole.index``, never tuple position."""
    unit = math.sqrt(0.5)
    reach = radius + 7.0
    bx = cx + unit * reach
    by = cy - unit * reach
    return [
        Line(
            cx + unit * radius,
            cy - unit * radius,
            bx - unit * 3.0,
            by + unit * 3.0,
            pens.dimension,
            cls="leader",
        ),
        Circle(bx, by, 3.0, FURNITURE, fill="#ffffff", cls="balloon"),
        Text(bx, by + 0.9, str(number), 2.6, anchor="middle", cls="balloon-no"),
    ]


# ---------------------------------------------------------------------------
# dimensions
# ---------------------------------------------------------------------------


def _build_dimensions(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    if not data.holes and data.reference is None:
        return []
    drawn = _build_row_chains(layout, data, pens) + _build_overall(layout, data, pens)
    return [Group("dimensions", tuple(drawn))]


def _build_row_chains(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    """Build as many Y-row chains as fit, then state the omitted count."""
    rows = data.rows()
    content_bottom = layout.point(0.0, -layout.half_height)[1]
    # A station is a *length*: it is subtracted from its neighbour and the
    # difference is printed, so it stays an exact nanometre all the way to
    # ``format_nm``. The floor mirrors ``DrillData.with_origin``'s, and for
    # its reason — an outline of an odd number of nanometres has no exact
    # half, and half a nanometre is three decimal places below anything this
    # sheet prints, where a float edge would be a quantity the drill file and
    # the drawing could round differently.
    edge_nm = Nanometre(data.reference.width_nm // 2) if data.reference is not None else None

    top = content_bottom + 8.0
    # The extension lines overshoot the dimension line by 1.5, so that is
    # the lowest ink a chain puts on the sheet.
    room = int((layout.area[3] - 1.5 - top) / ROW_PITCH) + 1
    # Bottom row first, which is the order they stack away from the panel.
    ordered = list(reversed(rows))
    count, omitted = allot(len(ordered), room)

    drawn: list[Item] = []
    if omitted:
        drawn.append(
            Text(
                layout.area[0] + 2.0,
                top + ROW_PITCH * count,
                fits(
                    f"… {omitted} further row dimensions not shown",
                    2.2,
                    layout.area[2] - layout.area[0] - 4.0,
                ),
                2.2,
                colour=RED,
                cls="dim-overflow",
            )
        )

    for level, (row_y_nm, holes) in enumerate(ordered[:count]):
        stations_nm = [hole.x_nm for hole in holes]
        if edge_nm is not None:
            stations_nm = [Nanometre(-edge_nm), *stations_nm, edge_nm]
        # Stations are integer nanometres, so exact equality alone identifies
        # duplicate dimension stations, including an edge-aligned hole.
        stations_nm = sorted(set(stations_nm))
        if len(stations_nm) < 2:
            continue

        chain: list[Item] = []
        dim_y = content_bottom + 8.0 + ROW_PITCH * level

        for x_nm in stations_nm:
            sx, sy = layout.point(mm_from_nm(x_nm), mm_from_nm(row_y_nm))
            chain.append(Line(sx, sy, sx, dim_y + 1.5, pens.feint, cls="extension"))

        for start_nm, end_nm in pairwise(stations_nm):
            x1 = layout.point(mm_from_nm(start_nm), 0.0)[0]
            x2 = layout.point(mm_from_nm(end_nm), 0.0)[0]
            chain.append(Line(x1, dim_y, x2, dim_y, pens.dimension, cls="dim-line"))
            chain.append(arrow(x1, dim_y, 1.0, 0.0))
            chain.append(arrow(x2, dim_y, -1.0, 0.0))
            # The subtraction is the two stations', not the two sheet
            # coordinates': ``x1`` and ``x2`` have been through the scale.
            label = format_nm(Nanometre(end_nm - start_nm), POSITION_DECIMALS)
            chain.append(
                Text(
                    (x1 + x2) / 2.0,
                    dim_y - 1.2,
                    fits(label, 2.2, abs(x2 - x1) + 6.0),
                    2.2,
                    anchor="middle",
                    cls="dim-text",
                )
            )

        drawn.append(Group("dim-chain", tuple(chain)))

    return drawn


def _build_overall(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    if data.reference is not None:
        width_nm, height_nm = data.reference.width_nm, data.reference.height_nm
    else:
        # No outline, so the holes are the extent. There is always at least one:
        # ``_build_dimensions`` returns before this on a panel with neither.
        xs = [hole.x_nm for hole in data.holes]
        ys = [hole.y_nm for hole in data.holes]
        width_nm = Nanometre(max(xs) - min(xs))
        height_nm = Nanometre(max(ys) - min(ys))
    if width_nm <= 0 and height_nm <= 0:
        return []

    drawn: list[Item] = []

    if width_nm > 0:
        half = mm_from_nm(width_nm) / 2.0
        left = layout.point(-half, 0.0)[0]
        right = layout.point(half, 0.0)[0]
        top = layout.point(0.0, layout.half_height)[1]
        dim_y = top - 10.0
        for x in (left, right):
            drawn.append(Line(x, top, x, dim_y - 1.5, pens.feint, cls="extension"))
        drawn.append(Line(left, dim_y, right, dim_y, pens.dimension, cls="dim-line"))
        drawn.append(arrow(left, dim_y, 1.0, 0.0))
        drawn.append(arrow(right, dim_y, -1.0, 0.0))
        drawn.append(
            Text(
                (left + right) / 2.0,
                dim_y - 1.4,
                format_nm(width_nm, POSITION_DECIMALS),
                2.4,
                anchor="middle",
                cls="dim-overall",
            )
        )

    if height_nm > 0:
        half = mm_from_nm(height_nm) / 2.0
        top = layout.point(0.0, half)[1]
        bottom = layout.point(0.0, -half)[1]
        left = layout.point(-layout.half_width, 0.0)[0]
        dim_x = left - 10.0
        for y in (top, bottom):
            drawn.append(Line(left, y, dim_x - 1.5, y, pens.feint, cls="extension"))
        drawn.append(Line(dim_x, top, dim_x, bottom, pens.dimension, cls="dim-line"))
        drawn.append(arrow(dim_x, top, 0.0, 1.0))
        drawn.append(arrow(dim_x, bottom, 0.0, -1.0))
        # Rotated, or it runs straight off the left-hand edge of the sheet.
        drawn.append(
            Text(
                dim_x - 1.4,
                (top + bottom) / 2.0,
                format_nm(height_nm, POSITION_DECIMALS),
                2.4,
                anchor="middle",
                rotate=-90.0,
                cls="dim-overall",
            )
        )

    return [Group("dim-overall-group", tuple(drawn))]


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------


def _build_schedule(layout: Layout, data: DrillData, pens: Pens) -> list[Item]:
    x0, y0, x1, y1 = layout.schedule
    drawn: list[Item] = [
        Rect(x0, y0, x1 - x0, y1 - y0, FURNITURE, cls="schedule-box")
    ]
    width = x1 - x0
    drawn.append(
        Text(x0 + 2.0, y0 + 4.6, "HOLE SCHEDULE", 3.2, weight="bold", cls="schedule-title")
    )

    rows = schedule_rows(data)
    tools = tool_summary(data)

    # The hole list and tool summary share the box. Capacity includes both
    # lists and their structural lines within the available height.
    summary_lines = len(tools)
    available = (y1 - y0) - 8.0
    needed = len(rows) + 2 + summary_lines + 1
    pitch = min(4.6, available / max(1, needed))
    shown = rows
    listed = tools
    overflow = 0
    tool_overflow = 0
    if pitch < 1.6:
        pitch = 1.6
        # Three lines are spoken for before either list starts: the column
        # heading, the rule under it and the rule above the summary.
        body = max(0, int(available / pitch) - 3)
        # The summary is allotted first, because it is the sheet's copy of
        # the drill file's tool table and a machinist sets the machine up
        # from it — but never more than half the box, or a panel of many
        # sizes would list its bits and none of its holes.
        room_for_tools = min(summary_lines, max(1, body // 2))
        kept_tools, tool_overflow = allot(summary_lines, room_for_tools)
        listed = tools[:kept_tools]
        kept_holes, overflow = allot(len(rows), max(0, body - room_for_tools))
        shown = rows[:kept_holes]
    font = max(1.1, min(2.6, pitch * 0.62))

    columns = (
        (x0 + 2.0 + width * 0.06, "middle"),
        (x0 + 2.0 + width * 0.30, "end"),
        (x0 + 2.0 + width * 0.50, "end"),
        (x0 + 2.0 + width * 0.72, "end"),
        (x0 + 2.0 + width * 0.88, "middle"),
    )
    cell_w = width * 0.2

    y = y0 + 8.0 + pitch
    for (cx, anchor), heading in zip(
        columns,
        # No "mm" in the heading: the cells below carry their own units,
        # and a fractional standard spells this column ``⌀9/32"``.
        ("NO.", "X", "Y", "⌀", "TOOL"),
    ):
        drawn.append(Text(cx, y, heading, font, anchor=anchor, weight="bold", cls="sched-head"))
    drawn.append(
        Line(
            x0 + 1.5,
            y + pitch * 0.35,
            x1 - 1.5,
            y + pitch * 0.35,
            pens.dimension,
            cls="sched-rule",
        )
    )

    for row in shown:
        y += pitch
        colour = RED if row.flagged else INK
        cells = (
            # The hole's own id, not its place in the tuple — see ``_balloon``.
            # NO. is the column a diagnostic is joined on.
            (str(row.number), "sched-no"),
            (row.x, "sched-x"),
            (row.y, "sched-y"),
            (row.diameter, "sched-dia"),
            (row.tool, "sched-tool"),
        )
        cell_items: list[Item] = [
            Text(cx, y, fits(value, font, cell_w), font, anchor=anchor, colour=colour, cls=cls)
            for (cx, anchor), (value, cls) in zip(columns, cells)
        ]
        drawn.append(Group("sched-row", tuple(cell_items)))

    if overflow:
        y += pitch
        drawn.append(
            Text(
                x0 + 2.0,
                y,
                fits(f"… {overflow} further holes not listed", font, width - 4.0),
                font,
                colour=RED,
                cls="sched-overflow",
            )
        )

    y += pitch * 0.6
    drawn.append(Line(x0 + 1.5, y, x1 - 1.5, y, pens.dimension, cls="sched-rule"))
    for line in listed:
        y += pitch
        drawn.append(
            Text(
                x0 + 2.0,
                y,
                fits(
                    f"{line.tool}  {line.diameter}  QTY {line.quantity}",
                    font,
                    width - 4.0,
                ),
                font,
                cls="sched-summary",
            )
        )
    if tool_overflow:
        y += pitch
        # Tool overflow names the omitted quantity separately from hole rows.
        drawn.append(
            Text(
                x0 + 2.0,
                y,
                fits(f"… {tool_overflow} further tools not listed", font, width - 4.0),
                font,
                colour=RED,
                cls="sched-tool-overflow",
            )
        )

    return [Group("schedule", tuple(drawn))]


# ---------------------------------------------------------------------------
# title block
# ---------------------------------------------------------------------------


def _build_title_block(
    layout: Layout, data: DrillData, pens: Pens, options: SheetText
) -> list[Item]:
    """Rule ISO 7200's field grid; the plain sheet keeps its list of lines.

    A field is a labelled cell, so a mandatory field with no value still shows
    its label over an em dash rather than leaving the reader to guess.
    """
    if layout.frame is not FrameStyle.ISO_5457:
        return _plain_title_block(layout, data, pens, options)

    x0, y0, x1, y1 = layout.title_block
    fields = title_fields(data, options, layout)
    drawn: list[Item] = [Rect(x0, y0, x1 - x0, y1 - y0, pens.frame, cls="title-block")]

    columns = TITLE_BLOCK_COLUMNS
    rows = math.ceil(len(fields) / columns)
    cell_w = title_cell_width(layout)
    cell_h = (y1 - y0) / rows
    for row in range(1, rows):
        y = y0 + row * cell_h
        drawn.append(Line(x0, y, x1, y, pens.dimension, cls="tb-rule"))
    for column in range(1, columns):
        x = x0 + column * cell_w
        drawn.append(Line(x, y0, x, y1, pens.dimension, cls="tb-rule"))

    room = cell_w - 2 * TITLE_CELL_PADDING
    for index, field in enumerate(fields):
        cx = x0 + (index % columns) * cell_w + TITLE_CELL_PADDING
        cy = y0 + (index // columns) * cell_h
        # The label sits above its value, feint, so the block reads as values
        # with their claims attached rather than as a page of headings.
        drawn.append(
            Text(cx, cy + TITLE_LABEL_FONT + 0.8, field.name, TITLE_LABEL_FONT,
                 colour=FEINT, cls="tb-label")
        )
        drawn.append(
            Text(cx, cy + cell_h - TITLE_CELL_PADDING,
                 fits(field.value, TITLE_VALUE_FONT, room), TITLE_VALUE_FONT,
                 weight="bold" if field.name == "TITLE" else "normal", cls="tb-value")
        )

    return [Group("title-block-group", tuple(drawn))]


def _plain_title_block(
    layout: Layout, data: DrillData, pens: Pens, options: SheetText
) -> list[Item]:
    x0, y0, x1, y1 = layout.title_block
    width = x1 - x0
    drawn: list[Item] = [Rect(x0, y0, width, y1 - y0, pens.frame, cls="title-block")]

    inner = width - 4.0
    company_font = fit_font(options.company, inner, 4.4, 2.2)
    drawn.append(
        Text(
            x0 + 2.0,
            y0 + 5.4,
            fits(options.company, company_font, inner),
            company_font,
            weight="bold",
            cls="tb-company",
        )
    )
    drawn.append(Line(x0, y0 + 7.4, x1, y0 + 7.4, FURNITURE, cls="tb-rule"))

    lines = [
        f"TITLE  {options.title or 'PANEL DRILL DRAWING'}",
        f"DRG No  {options.drawing_no or '—'}",
        enclosure_note(data, capacity(inner, TITLE_MIN_FONT)),
        f"SHEET 1 OF 1   SIZE {layout.sheet.name}",
        f"UNITS mm   SCALE {layout.scale_label}",
        f"{grid_note(data)}   HOLES {len(data.holes)}",
        "THIRD ANGLE PROJECTION — DO NOT SCALE FROM DRAWING",
        f"SOURCE  {data.source.path or '—'}",
        (
            f"LAYERS  drill={data.source.drill_layer or '—'} "
            f"ref={data.source.reference_layer or '—'}"
        ),
    ]
    step = min(4.2, max(2.4, (y1 - (y0 + 9.0) - 1.5) / len(lines)))
    font = max(TITLE_MIN_FONT, min(2.8, step * 0.62))
    y = y0 + 8.0
    for line in lines:
        y += step
        # Shrink the line before chopping it. Every line here is a claim the
        # sheet makes, and a claim that does not fit is worth a smaller font
        # rather than an ellipsis: ``designator`` elides the series so that
        # a four-candidate footprint fits, and adding ``ROTATED`` to the same
        # line took two of the four away again.
        size = fit_font(line, inner, font, TITLE_MIN_FONT)
        drawn.append(Text(x0 + 2.0, y, fits(line, size, inner), size, cls="tb"))

    return [Group("title-block-group", tuple(drawn))]


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------


def _overflow_marker(layout: Layout) -> list[Item]:
    """Say so when the content outran the largest sheet, rather than shrinking it.

    Drawn one line below the "NOTES" title, on the title's own baseline offset
    doubled, so it takes its own line rather than sitting under the heading.
    """
    if layout.fits:
        return []
    x0, y0, x1, _ = layout.notes
    # The PDF sheet is always 1:1, but this marker also serves the SVG sheet,
    # which can be drawn at any explicit scale — so it names the scale the
    # layout actually holds, the same source the title block's SCALE line
    # reads, rather than assuming the PDF's own convention.
    required = (
        f"SCALE {layout.scale_label} — CONTENT EXCEEDS {layout.sheet.name}; "
        f"{layout.needed_width:.3f} × {layout.needed_height:.3f} mm REQUIRED"
    )
    return [
        Text(
            x0 + 2.5,
            y0 + layout.note_font * 1.6 * 2.0,
            fits(required, layout.note_font, x1 - x0 - 5.0),
            layout.note_font,
            colour=RED,
            cls="note note-overflow",
        )
    ]


def _build_notes(layout: Layout, data: DrillData) -> list[Item]:
    x0, y0, x1, y1 = layout.notes
    drawn: list[Item] = [Rect(x0, y0, x1 - x0, y1 - y0, FURNITURE, cls="notes-box")]
    font = layout.note_font
    drawn.append(
        Text(x0 + 2.0, y0 + font * 1.6, "NOTES", font * 1.15, weight="bold", cls="notes-title")
    )
    overflow = _overflow_marker(layout)
    drawn += overflow

    notes = note_lines(data)
    width = x1 - x0 - 5.0
    limit = y1 - 1.0
    # The overflow marker, when present, has already claimed the line right
    # below the title, so the numbered notes start one line further down.
    y = y0 + font * 1.6 * (2.0 if overflow else 1.0)
    for index, note in enumerate(notes):
        y += font * 1.6
        if y > limit:
            break
        remaining = len(notes) - index
        if remaining > 1 and y + font * 1.6 > limit:
            # Last line that fits, and more to come. Spend it saying so: a
            # note that disappears without trace is worse than one that is
            # visibly missing — a dropped off-grid warning means the
            # operator never learns a hole moved. The schedule does the
            # same a few functions up.
            drawn.append(
                Text(
                    x0 + 2.5,
                    y,
                    fits(f"… {remaining} further notes not listed", font, width),
                    font,
                    colour=RED,
                    cls="note note-overflow",
                )
            )
            break
        classification = {
            Severity.WARNING: "note note-warning",
            Severity.ERROR: "note note-error",
        }.get(note.severity, "note note-info")
        # ``colour`` and the class say the same thing twice on purpose: a
        # stylesheet's ``text{fill:…}`` rule outranks a presentation attribute,
        # so a backend that only had the class would render the note black.
        colour = RED if note.severity in (Severity.WARNING, Severity.ERROR) else INK
        drawn.append(
            Text(x0 + 2.5, y, fits(note.text, font, width), font, colour=colour, cls=classification)
        )

    return [Group("notes", tuple(drawn))]
