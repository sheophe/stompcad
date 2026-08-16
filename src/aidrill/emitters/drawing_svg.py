"""Render ``DrillData`` as a standalone SVG engineering drawing.

The sheet contains the outline, holes, dimensions, schedule, title data and
diagnostic notes; it does not render source artwork or recompute pipeline facts.
Model lengths remain integer nanometres until formatting, while layout uses
sheet millimetres. Capacity limits use explicit counted omission markers.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import pairwise
from typing import ClassVar

from ..model import DrillData, Severity
from ..units import Nanometre, format_nm, mm_from_nm
from .base import register_emitter
from .drawing.content import (
    POSITION_DECIMALS,
    allot,
    capacity,
    diameter_label,
    enclosure_note,
    fit_font,
    fits,
    flagged_holes,
    grid_note,
    is_flagged,
    note_lines,
)
from .drawing.layout import (
    ROW_PITCH as _ROW_PITCH,
)
from .drawing.layout import (
    TITLE_MIN_FONT as _TITLE_MIN_FONT,
)
from .drawing.layout import (
    Layout,
)
from .drawing.sheet import A3_LANDSCAPE_PLAIN as A3_LANDSCAPE
from .drawing.sheet import A4_LANDSCAPE, Sheet

__all__ = [
    "Sheet",
    "A4_LANDSCAPE",
    "A3_LANDSCAPE",
    "A4_PORTRAIT",
    "DrawingOptions",
    "Layout",
    "DrawingSvgEmitter",
]

SVG_NS = "http://www.w3.org/2000/svg"

INK = "#111111"
RED = "#c00000"
FEINT = "#8a8a8a"

A4_PORTRAIT = Sheet("A4", 210.0, 297.0)


@dataclass(frozen=True, slots=True)
class DrawingOptions:
    """Options specific to the drawing emitter."""

    sheet: Sheet = A4_LANDSCAPE
    scale: float | None = None
    title: str = ""
    drawing_no: str = ""
    company: str = "ARTIFACT INSTRUMENTS"


def _fmt(value: float | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


# ---------------------------------------------------------------------------
# emitter
# ---------------------------------------------------------------------------


@register_emitter
class DrawingSvgEmitter:
    """Render a standalone, millimetre-user-unit SVG engineering drawing."""

    name: ClassVar[str] = "drawing-svg"
    media_type: ClassVar[str] = "image/svg+xml"
    extension: ClassVar[str] = ".svg"

    def __init__(self, options: DrawingOptions | None = None) -> None:
        self.options = options or DrawingOptions()

    # -- public ----------------------------------------------------------
    def emit(self, data: DrillData) -> str:
        layout = self.layout(data)
        # The namespace is declared as a plain attribute rather than through
        # ElementTree's ``default_namespace``: that option rejects unqualified
        # attribute names, and every SVG attribute here is unqualified.
        root = ET.Element(
            "svg",
            {
                "xmlns": SVG_NS,
                "width": f"{_fmt(layout.sheet.width)}mm",
                "height": f"{_fmt(layout.sheet.height)}mm",
                "viewBox": f"0 0 {_fmt(layout.sheet.width)} {_fmt(layout.sheet.height)}",
                "version": "1.1",
            },
        )
        _sub(root, "title").text = self._sheet_title(data)
        _sub(root, "style", type="text/css").text = _STYLESHEET

        self._draw_frame(root, layout)
        self._draw_outlines(root, layout, data)
        self._draw_centrelines(root, layout, data)
        self._draw_holes(root, layout, data)
        self._draw_dimensions(root, layout, data)
        self._draw_schedule(root, layout, data)
        self._draw_title_block(root, layout, data)
        self._draw_notes(root, layout, data)

        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"

    def layout(self, data: DrillData) -> Layout:
        """Compute the sheet layout for ``data``. Pure; no drawing happens."""
        return Layout.for_sheet(self.options.sheet, data, scale=self.options.scale)

    def _sheet_title(self, data: DrillData) -> str:
        return self.options.title or data.source.path or "DRILL DRAWING"

    # -- frame -----------------------------------------------------------
    def _draw_frame(self, root: ET.Element, layout: Layout) -> None:
        x0, y0, x1, y1 = layout.border
        _sub(
            root,
            "rect",
            **{"class": "border"},
            x=x0,
            y=y0,
            width=x1 - x0,
            height=y1 - y0,
            fill="none",
            stroke=INK,
            stroke_width=0.5,
        )

    # -- outlines --------------------------------------------------------
    def _draw_outlines(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        """Draw one panel outline; enclosure identity belongs in the title block."""
        group = _sub(root, "g", **{"class": "outlines"})
        if data.reference is not None:
            self._rounded(
                group,
                layout,
                mm_from_nm(data.reference.width_nm),
                mm_from_nm(data.reference.height_nm),
                cls="outline",
                stroke=INK,
                stroke_width=0.4,
            )

    def _rounded(
        self,
        parent: ET.Element,
        layout: Layout,
        width: float,
        height: float,
        *,
        cls: str,
        stroke: str,
        stroke_width: float = 0.4,
    ) -> None:
        """Draw a rounded rectangle from model-millimetre layout geometry."""
        x, y = layout.point(-width / 2.0, height / 2.0)
        radius = min(3.0, width / 4.0, height / 4.0) * layout.scale
        _sub(
            parent,
            "rect",
            **{"class": cls},
            x=x,
            y=y,
            width=layout.length(width),
            height=layout.length(height),
            rx=radius,
            ry=radius,
            fill="none",
            stroke=stroke,
            stroke_width=stroke_width,
        )

    # -- centrelines -----------------------------------------------------
    def _draw_centrelines(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        group = _sub(root, "g", **{"class": "centrelines"})
        over = 4.0
        left, top = layout.point(-layout.half_width, layout.half_height)
        right, bottom = layout.point(layout.half_width, -layout.half_height)
        ox, oy = layout.point(0.0, 0.0)
        chain = "6 1.5 1 1.5"

        _sub(
            group,
            "line",
            **{"class": "centreline"},
            x1=max(layout.area[0], left - over),
            y1=oy,
            x2=min(layout.area[2], right + over),
            y2=oy,
            stroke=FEINT,
            stroke_width=0.25,
            stroke_dasharray=chain,
        )
        _sub(
            group,
            "line",
            **{"class": "centreline"},
            x1=ox,
            y1=max(layout.area[1], top - over),
            x2=ox,
            y2=min(layout.area[3], bottom + over),
            stroke=FEINT,
            stroke_width=0.25,
            stroke_dasharray=chain,
        )

        _sub(
            group,
            "circle",
            **{"class": "origin"},
            cx=ox,
            cy=oy,
            r=1.6,
            fill="none",
            stroke=INK,
            stroke_width=0.3,
        )
        for dx, dy in ((2.6, 0.0), (0.0, 2.6)):
            _sub(
                group,
                "line",
                **{"class": "origin"},
                x1=ox - dx,
                y1=oy - dy,
                x2=ox + dx,
                y2=oy + dy,
                stroke=INK,
                stroke_width=0.3,
            )
        _text(
            group,
            ox + 3.0,
            oy + 4.0,
            "0,0",
            2.2,
            cls="origin-label",
        )

    # -- holes -----------------------------------------------------------
    def _draw_holes(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        group = _sub(root, "g", **{"class": "holes"})
        flagged = flagged_holes(data.diagnostics)

        for hole in data.holes:
            cx, cy = layout.point(mm_from_nm(hole.x_nm), mm_from_nm(hole.y_nm))
            radius = max(0.4, layout.length(mm_from_nm(hole.diameter_nm)) / 2.0)
            is_dup = is_flagged(hole, flagged)
            colour = RED if is_dup else INK

            _sub(
                group,
                "circle",
                **{"class": "hole dup" if is_dup else "hole"},
                cx=cx,
                cy=cy,
                r=radius,
                fill="none",
                stroke=colour,
                stroke_width=0.4,
            )
            if is_dup:
                _sub(
                    group,
                    "circle",
                    **{"class": "dup-ring"},
                    cx=cx,
                    cy=cy,
                    r=radius + 1.6,
                    fill="none",
                    stroke=RED,
                    stroke_width=0.3,
                    stroke_dasharray="1.2 1.2",
                )

            arm = radius + 1.2
            for dx, dy in ((arm, 0.0), (0.0, arm)):
                _sub(
                    group,
                    "line",
                    **{"class": "centre-mark"},
                    x1=cx - dx,
                    y1=cy - dy,
                    x2=cx + dx,
                    y2=cy + dy,
                    stroke=colour,
                    stroke_width=0.2,
                )

            self._balloon(group, cx, cy, radius, hole.index)

    def _balloon(
        self, parent: ET.Element, cx: float, cy: float, radius: float, number: int
    ) -> None:
        """Draw a balloon carrying stable ``Hole.index``, never tuple position."""
        unit = math.sqrt(0.5)
        reach = radius + 7.0
        bx = cx + unit * reach
        by = cy - unit * reach
        _sub(
            parent,
            "line",
            **{"class": "leader"},
            x1=cx + unit * radius,
            y1=cy - unit * radius,
            x2=bx - unit * 3.0,
            y2=by + unit * 3.0,
            stroke=INK,
            stroke_width=0.2,
        )
        _sub(
            parent,
            "circle",
            **{"class": "balloon"},
            cx=bx,
            cy=by,
            r=3.0,
            fill="#ffffff",
            stroke=INK,
            stroke_width=0.3,
        )
        _text(parent, bx, by + 0.9, str(number), 2.6, anchor="middle", cls="balloon-no")

    # -- dimensions ------------------------------------------------------
    def _draw_dimensions(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        if not data.holes and data.reference is None:
            return
        group = _sub(root, "g", **{"class": "dimensions"})
        self._draw_row_chains(group, layout, data)
        self._draw_overall(group, layout, data)

    def _draw_row_chains(self, parent: ET.Element, layout: Layout, data: DrillData) -> None:
        """Draw as many Y-row chains as fit, then state the omitted count."""
        rows = data.rows()
        content_bottom = layout.point(0.0, -layout.half_height)[1]
        # A station is a *length*: it is subtracted from its neighbour and the
        # difference is printed, so it stays an exact nanometre all the way to
        # ``format_nm``. The floor mirrors ``DrillData.with_origin``'s, and for
        # its reason — an outline of an odd number of nanometres has no exact
        # half, and half a nanometre is three decimal places below anything this
        # sheet prints, where a float edge would be a quantity the drill file and
        # the drawing could round differently.
        edge_nm = (
            Nanometre(data.reference.width_nm // 2) if data.reference is not None else None
        )

        top = content_bottom + 8.0
        # The extension lines overshoot the dimension line by 1.5, so that is
        # the lowest ink a chain puts on the sheet.
        room = int((layout.area[3] - 1.5 - top) / _ROW_PITCH) + 1
        # Bottom row first, which is the order they stack away from the panel.
        ordered = list(reversed(rows))
        drawn, omitted = allot(len(ordered), room)
        if omitted:
            _text(
                parent,
                layout.area[0] + 2.0,
                top + _ROW_PITCH * drawn,
                fits(
                    f"… {omitted} further row dimensions not shown",
                    2.2,
                    layout.area[2] - layout.area[0] - 4.0,
                ),
                2.2,
                cls="dim-overflow",
                fill=RED,
            )

        for level, (row_y_nm, holes) in enumerate(ordered[:drawn]):
            stations_nm = [hole.x_nm for hole in holes]
            if edge_nm is not None:
                stations_nm = [Nanometre(-edge_nm), *stations_nm, edge_nm]
            # Stations are integer nanometres, so exact equality alone identifies
            # duplicate dimension stations, including an edge-aligned hole.
            stations_nm = sorted(set(stations_nm))
            if len(stations_nm) < 2:
                continue

            chain = _sub(parent, "g", **{"class": "dim-chain"})
            dim_y = content_bottom + 8.0 + _ROW_PITCH * level

            for x_nm in stations_nm:
                sx, sy = layout.point(mm_from_nm(x_nm), mm_from_nm(row_y_nm))
                _sub(
                    chain,
                    "line",
                    **{"class": "extension"},
                    x1=sx,
                    y1=sy,
                    x2=sx,
                    y2=dim_y + 1.5,
                    stroke=FEINT,
                    stroke_width=0.15,
                )

            for start_nm, end_nm in pairwise(stations_nm):
                x1 = layout.point(mm_from_nm(start_nm), 0.0)[0]
                x2 = layout.point(mm_from_nm(end_nm), 0.0)[0]
                _sub(
                    chain,
                    "line",
                    **{"class": "dim-line"},
                    x1=x1,
                    y1=dim_y,
                    x2=x2,
                    y2=dim_y,
                    stroke=INK,
                    stroke_width=0.2,
                )
                _arrow(chain, x1, dim_y, 1.0, 0.0)
                _arrow(chain, x2, dim_y, -1.0, 0.0)
                # The subtraction is the two stations', not the two sheet
                # coordinates': ``x1`` and ``x2`` have been through the scale.
                label = format_nm(Nanometre(end_nm - start_nm), POSITION_DECIMALS)
                _text(
                    chain,
                    (x1 + x2) / 2.0,
                    dim_y - 1.2,
                    fits(label, 2.2, abs(x2 - x1) + 6.0),
                    2.2,
                    anchor="middle",
                    cls="dim-text",
                )

    def _draw_overall(self, parent: ET.Element, layout: Layout, data: DrillData) -> None:
        if data.reference is not None:
            width_nm, height_nm = data.reference.width_nm, data.reference.height_nm
        else:
            xs = [hole.x_nm for hole in data.holes]
            ys = [hole.y_nm for hole in data.holes]
            if not xs:
                return
            width_nm = Nanometre(max(xs) - min(xs))
            height_nm = Nanometre(max(ys) - min(ys))
        if width_nm <= 0 and height_nm <= 0:
            return

        group = _sub(parent, "g", **{"class": "dim-overall-group"})

        if width_nm > 0:
            half = mm_from_nm(width_nm) / 2.0
            left = layout.point(-half, 0.0)[0]
            right = layout.point(half, 0.0)[0]
            top = layout.point(0.0, layout.half_height)[1]
            dim_y = top - 10.0
            for x in (left, right):
                _sub(
                    group,
                    "line",
                    **{"class": "extension"},
                    x1=x,
                    y1=top,
                    x2=x,
                    y2=dim_y - 1.5,
                    stroke=FEINT,
                    stroke_width=0.15,
                )
            _sub(
                group,
                "line",
                **{"class": "dim-line"},
                x1=left,
                y1=dim_y,
                x2=right,
                y2=dim_y,
                stroke=INK,
                stroke_width=0.2,
            )
            _arrow(group, left, dim_y, 1.0, 0.0)
            _arrow(group, right, dim_y, -1.0, 0.0)
            _text(
                group,
                (left + right) / 2.0,
                dim_y - 1.4,
                format_nm(width_nm, POSITION_DECIMALS),
                2.4,
                anchor="middle",
                cls="dim-overall",
            )

        if height_nm > 0:
            half = mm_from_nm(height_nm) / 2.0
            top = layout.point(0.0, half)[1]
            bottom = layout.point(0.0, -half)[1]
            left = layout.point(-layout.half_width, 0.0)[0]
            dim_x = left - 10.0
            for y in (top, bottom):
                _sub(
                    group,
                    "line",
                    **{"class": "extension"},
                    x1=left,
                    y1=y,
                    x2=dim_x - 1.5,
                    y2=y,
                    stroke=FEINT,
                    stroke_width=0.15,
                )
            _sub(
                group,
                "line",
                **{"class": "dim-line"},
                x1=dim_x,
                y1=top,
                x2=dim_x,
                y2=bottom,
                stroke=INK,
                stroke_width=0.2,
            )
            _arrow(group, dim_x, top, 0.0, 1.0)
            _arrow(group, dim_x, bottom, 0.0, -1.0)
            # Rotated, or it runs straight off the left-hand edge of the sheet.
            _text(
                group,
                dim_x - 1.4,
                (top + bottom) / 2.0,
                format_nm(height_nm, POSITION_DECIMALS),
                2.4,
                anchor="middle",
                cls="dim-overall",
                rotate=-90.0,
            )

    # -- schedule --------------------------------------------------------
    def _draw_schedule(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        x0, y0, x1, y1 = layout.schedule
        group = _sub(root, "g", **{"class": "schedule"})
        _sub(
            group,
            "rect",
            **{"class": "schedule-box"},
            x=x0,
            y=y0,
            width=x1 - x0,
            height=y1 - y0,
            fill="none",
            stroke=INK,
            stroke_width=0.3,
        )
        width = x1 - x0
        _text(group, x0 + 2.0, y0 + 4.6, "HOLE SCHEDULE", 3.2, cls="schedule-title", weight="bold")

        tools = data.tools()
        counts = data.tool_counts()
        label = diameter_label(data)

        # The hole list and tool summary share the box. Capacity includes both
        # lists and their structural lines within the available height.
        summary_lines = len(tools)
        available = (y1 - y0) - 8.0
        needed = len(data.holes) + 2 + summary_lines + 1
        pitch = min(4.6, available / max(1, needed))
        shown = data.holes
        listed = list(tools.items())
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
            listed = listed[:kept_tools]
            kept_holes, overflow = allot(len(data.holes), max(0, body - room_for_tools))
            shown = data.holes[:kept_holes]
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
        for (cx, anchor), heading, cls in zip(
            columns,
            # No "mm" in the heading: the cells below carry their own units,
            # and a fractional standard spells this column ``⌀9/32"``.
            ("NO.", "X", "Y", "⌀", "TOOL"),
            ("sched-head", "sched-head", "sched-head", "sched-head", "sched-head"),
        ):
            _text(group, cx, y, heading, font, anchor=anchor, cls=cls, weight="bold")
        _sub(
            group,
            "line",
            **{"class": "sched-rule"},
            x1=x0 + 1.5,
            y1=y + pitch * 0.35,
            x2=x1 - 1.5,
            y2=y + pitch * 0.35,
            stroke=INK,
            stroke_width=0.2,
        )

        flagged = flagged_holes(data.diagnostics)
        for hole in shown:
            y += pitch
            row = _sub(group, "g", **{"class": "sched-row"})
            colour = RED if is_flagged(hole, flagged) else None
            cells = (
                # The hole's own id, not its place in the tuple — see
                # ``_balloon``. NO. is the column a diagnostic is joined on.
                (str(hole.index), "sched-no"),
                # format_nm, not an f-string over ``mm_from_nm``: the position
                # is an integer and this is the one rendering of it, so there is
                # no float in between for the drill file to disagree with. It is
                # also where the negative zero was — a hole at -400 nm printed
                # "-0.000" here while the Excellon writer printed "0.000" for the
                # very same hole.
                (format_nm(hole.x_nm, POSITION_DECIMALS), "sched-x"),
                (format_nm(hole.y_nm, POSITION_DECIMALS), "sched-y"),
                (label(hole.diameter_nm), "sched-dia"),
                (f"T{tools[hole.diameter_nm]}", "sched-tool"),
            )
            for (cx, anchor), (value, cls) in zip(columns, cells):
                _text(
                    row,
                    cx,
                    y,
                    fits(value, font, cell_w),
                    font,
                    anchor=anchor,
                    cls=cls,
                    fill=colour,
                )

        if overflow:
            y += pitch
            _text(
                group,
                x0 + 2.0,
                y,
                fits(f"… {overflow} further holes not listed", font, width - 4.0),
                font,
                cls="sched-overflow",
                fill=RED,
            )

        y += pitch * 0.6
        _sub(
            group,
            "line",
            **{"class": "sched-rule"},
            x1=x0 + 1.5,
            y1=y,
            x2=x1 - 1.5,
            y2=y,
            stroke=INK,
            stroke_width=0.2,
        )
        for diameter_nm, tool in listed:
            y += pitch
            _text(
                group,
                x0 + 2.0,
                y,
                fits(
                    f"T{tool}  {label(diameter_nm)}  QTY {counts[diameter_nm]}",
                    font,
                    width - 4.0,
                ),
                font,
                cls="sched-summary",
            )
        if tool_overflow:
            y += pitch
            # Tool overflow names the omitted quantity separately from hole rows.
            _text(
                group,
                x0 + 2.0,
                y,
                fits(f"… {tool_overflow} further tools not listed", font, width - 4.0),
                font,
                cls="sched-tool-overflow",
                fill=RED,
            )

    # -- title block -----------------------------------------------------
    def _draw_title_block(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        x0, y0, x1, y1 = layout.title_block
        width = x1 - x0
        group = _sub(root, "g", **{"class": "title-block-group"})
        _sub(
            group,
            "rect",
            **{"class": "title-block"},
            x=x0,
            y=y0,
            width=width,
            height=y1 - y0,
            fill="none",
            stroke=INK,
            stroke_width=0.5,
        )

        inner = width - 4.0
        options = self.options
        company_font = fit_font(options.company, inner, 4.4, 2.2)
        _text(
            group,
            x0 + 2.0,
            y0 + 5.4,
            fits(options.company, company_font, inner),
            company_font,
            cls="tb-company",
            weight="bold",
        )
        _sub(
            group,
            "line",
            **{"class": "tb-rule"},
            x1=x0,
            y1=y0 + 7.4,
            x2=x1,
            y2=y0 + 7.4,
            stroke=INK,
            stroke_width=0.3,
        )

        lines = [
            f"TITLE  {options.title or 'PANEL DRILL DRAWING'}",
            f"DRG No  {options.drawing_no or '—'}",
            enclosure_note(data, capacity(inner, _TITLE_MIN_FONT)),
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
        font = max(_TITLE_MIN_FONT, min(2.8, step * 0.62))
        y = y0 + 8.0
        for line in lines:
            y += step
            # Shrink the line before chopping it. Every line here is a claim the
            # sheet makes, and a claim that does not fit is worth a smaller font
            # rather than an ellipsis: ``designator`` elides the series so that
            # a four-candidate footprint fits, and adding ``ROTATED`` to the same
            # line took two of the four away again.
            size = fit_font(line, inner, font, _TITLE_MIN_FONT)
            _text(group, x0 + 2.0, y, fits(line, size, inner), size, cls="tb")

    # -- notes -----------------------------------------------------------
    def _draw_notes(self, root: ET.Element, layout: Layout, data: DrillData) -> None:
        x0, y0, x1, y1 = layout.notes
        group = _sub(root, "g", **{"class": "notes"})
        _sub(
            group,
            "rect",
            **{"class": "notes-box"},
            x=x0,
            y=y0,
            width=x1 - x0,
            height=y1 - y0,
            fill="none",
            stroke=INK,
            stroke_width=0.3,
        )
        font = layout.note_font
        _text(group, x0 + 2.0, y0 + font * 1.6, "NOTES", font * 1.15, cls="notes-title", weight="bold")

        notes = note_lines(data)
        width = x1 - x0 - 5.0
        limit = y1 - 1.0
        y = y0 + font * 1.6
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
                # same a few methods up.
                _text(
                    group,
                    x0 + 2.5,
                    y,
                    fits(f"… {remaining} further notes not listed", font, width),
                    font,
                    cls="note note-overflow",
                    fill=RED,
                )
                break
            classification = {
                Severity.WARNING: "note note-warning",
                Severity.ERROR: "note note-error",
            }.get(note.severity, "note note-info")
            # Inline style, not fill= : the stylesheet's text{fill:…} rule would
            # win over a presentation attribute and the note would render black.
            colour = RED if note.severity in (Severity.WARNING, Severity.ERROR) else None
            _text(
                group,
                x0 + 2.5,
                y,
                fits(note.text, font, width),
                font,
                cls=classification,
                fill=colour,
            )


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

_STYLESHEET = (
    "svg{background:#ffffff}"
    "text{font-family:'DejaVu Sans','Helvetica Neue',Helvetica,Arial,sans-serif;"
    "fill:" + INK + "}"
)


def _sub(parent: ET.Element, tag: str, **attrs) -> ET.Element:
    element = ET.SubElement(parent, tag)
    for key, value in attrs.items():
        if value is None:
            continue
        element.set(key.replace("_", "-"), _fmt(value))
    return element


def _text(
    parent: ET.Element,
    x: float,
    y: float,
    content: str,
    size: float,
    *,
    anchor: str = "start",
    cls: str = "",
    fill: str | None = None,
    weight: str | None = None,
    rotate: float | None = None,
) -> ET.Element:
    attrs: dict[str, object] = {"x": x, "y": y, "font-size": size}
    if anchor != "start":
        attrs["text-anchor"] = anchor
    if weight:
        attrs["font-weight"] = weight
    if rotate is not None:
        attrs["transform"] = f"rotate({_fmt(rotate)} {_fmt(x)} {_fmt(y)})"
    if fill:
        # Inline style beats the stylesheet; a fill= attribute does not.
        attrs["style"] = f"fill:{fill}"
    if cls:
        attrs["class"] = cls
    element = _sub(parent, "text", **attrs)
    element.text = content
    return element


def _arrow(parent: ET.Element, x: float, y: float, dx: float, dy: float) -> None:
    """Filled arrowhead at (x, y) pointing along the unit vector (dx, dy)."""
    length, half = 2.2, 0.7
    tail_x, tail_y = x + dx * length, y + dy * length
    px, py = -dy * half, dx * half
    points = " ".join(
        f"{_fmt(ax)},{_fmt(ay)}"
        for ax, ay in (
            (x, y),
            (tail_x + px, tail_y + py),
            (tail_x - px, tail_y - py),
        )
    )
    _sub(parent, "polygon", **{"class": "arrow"}, points=points, fill=INK, stroke="none")
