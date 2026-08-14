"""``drawing-svg`` — an engineering drawing of the drill data (SPEC §7).

This is the sheet you hand to whoever drills the panel. It is **not** a render of
the artwork: an earlier attempt drew the Illustrator Graphics layer with
substitute fonts and bbox-only text metrics, which produced something that
looked like the panel, wasn't the panel, and told the machinist nothing. Only
drill data is drawn here — holes, dimensions, a schedule, and the pipeline's
diagnostics as notes.

What ends up on the sheet:

* a border, default A4 landscape, sheet configurable
* the reference outline as a rounded rectangle, plus an optional dashed
  ``true_size`` overlay so a drawn outline can be checked against the real
  enclosure
* chain-dash centrelines and an origin symbol at (0, 0)
* every hole at true diameter with a centre mark and a numbered balloon
* one chain dimension per Y row (``DrillData.rows()``) with extension lines,
  plus overall width and height
* a hole schedule — No. / X / Y / ⌀ / TOOL — with tool numbers taken from
  ``DrillData.tools()`` and never renumbered, and a per-tool quantity summary
* a title block and a NOTES block, warnings and errors in red

Two things about SVG that this module is careful about, both learned the hard
way:

1. **A CSS rule in ``<style>`` beats a ``fill=`` presentation attribute.** With
   ``text{fill:#111111}`` in the stylesheet, ``<text fill="red">`` renders
   black. Every coloured string here therefore carries ``style="fill:…"``, which
   does win. The same trap applies to ``font-size``, so the stylesheet declares
   none and every ``<text>`` sets its own.
2. **Vertical dimension labels must be rotated.** An unrotated label on the
   left-hand height dimension runs straight off the side of the sheet.

The emitter re-derives nothing: no snapping, no diameter clustering, no
deduplication. It reads ``tools()``, ``tool_counts()``, ``rows()`` and
``diagnostics`` and draws what it is given. In particular, *which* holes are
duplicates is read out of the ``duplicate-hole`` diagnostics themselves — see
:func:`_flagged_holes` — because the one time this file decided that for itself
it disagreed with the pipeline and painted an innocent hole red.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import ClassVar, Iterable, Sequence

from ..formatting import format_mm
from ..model import Diagnostic, DrillData, Hole, Severity
from .base import register_emitter

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
TRUE_SIZE_COLOUR = "#1f6fb4"

#: Conservative glyph-advance estimate, as a fraction of the font size. Used to
#: truncate strings to their box. Deliberately wider than a real sans face so
#: nothing is clipped by the border.
CHAR_RATIO = 0.62

#: Scales an engineer expects to read in a title block. The fitted scale is
#: rounded *down* to one of these, so fitting can never overflow.
PREFERRED_SCALES = (
    20.0, 10.0, 5.0, 4.0, 2.0, 1.0,
    0.5, 0.4, 0.25, 0.2, 0.1, 0.05, 0.04, 0.025, 0.02, 0.01,
)

DUP_CODE = "duplicate-hole"


@dataclass(frozen=True, slots=True)
class Sheet:
    """A drawing sheet, in millimetres."""

    name: str
    width: float
    height: float

    @property
    def margin(self) -> float:
        return min(10.0, min(self.width, self.height) * 0.05)


A4_LANDSCAPE = Sheet("A4", 297.0, 210.0)
A4_PORTRAIT = Sheet("A4", 210.0, 297.0)
A3_LANDSCAPE = Sheet("A3", 420.0, 297.0)


@dataclass(frozen=True, slots=True)
class DrawingOptions:
    """Options for the drawing emitter alone (ISP: no shared options bag)."""

    sheet: Sheet = A4_LANDSCAPE
    scale: float | None = None
    title: str = ""
    drawing_no: str = ""
    true_size: tuple[float, float] | None = None
    grid: float = 0.25
    company: str = "ARTIFACT INSTRUMENTS"


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass(frozen=True, slots=True)
class Layout:
    """Where everything goes on the sheet. Pure geometry, no SVG.

    Separated from the drawing code so tests (and the emitter itself) can ask
    "where would hole (x, y) land?" without parsing the output.
    """

    sheet: Sheet
    border: Box
    area: Box  # the drawing area proper
    notes: Box
    schedule: Box
    title_block: Box
    scale: float
    origin_x: float
    origin_y: float
    half_width: float  # model half-extents of the drawn content
    half_height: float
    note_font: float

    def point(self, x: float, y: float) -> tuple[float, float]:
        """Model millimetres (Y up) → sheet millimetres (Y down)."""
        return (self.origin_x + x * self.scale, self.origin_y - y * self.scale)

    def length(self, mm: float) -> float:
        return mm * self.scale

    @property
    def content(self) -> Box:
        """The drawn content's extent on the sheet, in sheet millimetres."""
        x0, y0 = self.point(-self.half_width, self.half_height)
        x1, y1 = self.point(self.half_width, -self.half_height)
        return (x0, y0, x1, y1)

    @property
    def scale_label(self) -> str:
        if self.scale >= 1.0:
            return f"{_trim(self.scale)}:1"
        return f"1:{_trim(1.0 / self.scale)}"


# space reserved inside the drawing area for drawing furniture, in sheet mm
_LEFT_ALLOWANCE = 14.0  # left-hand height dimension (rotated label; see _draw_overall)
_RIGHT_ALLOWANCE = 14.0  # balloons
_TOP_ALLOWANCE = 16.0  # overall width dimension
_BOTTOM_BASE = 12.0  # below the last chain dimension
_ROW_PITCH = 8.0  # between stacked chain dimensions
_GUTTER = 4.0


def _trim(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt(value: float | int | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _fits(text: str, size: float, width: float) -> str:
    """Truncate ``text`` so its estimated extent stays inside ``width``."""
    if width <= 0:
        return ""
    limit = max(1, int(width / (CHAR_RATIO * size))) if size > 0 else 0
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _fit_font(text: str, width: float, largest: float, smallest: float) -> float:
    if not text or width <= 0:
        return largest
    return max(smallest, min(largest, width / (CHAR_RATIO * len(text))))


# ---------------------------------------------------------------------------
# emitter
# ---------------------------------------------------------------------------


@register_emitter
class DrawingSvgEmitter:
    """Renders ``DrillData`` as an engineering drawing in SVG.

    The output is a standalone SVG document whose user units are millimetres,
    so every number in it is directly meaningful and the sheet prints 1:1.
    """

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
        sheet = self.options.sheet
        margin = sheet.margin
        border = (margin, margin, sheet.width - margin, sheet.height - margin)
        inner_w = border[2] - border[0]
        inner_h = border[3] - border[1]

        right_w = min(92.0, inner_w * 0.4)
        title_h = min(46.0, inner_h * 0.35)
        right_x = border[2] - right_w
        title_block = (right_x, border[3] - title_h, border[2], border[3])
        schedule = (right_x, border[1], border[2], title_block[1] - 2.0)

        left_w = max(20.0, inner_w - right_w - _GUTTER)
        note_lines = self._note_lines(data)
        note_font = min(
            (_fit_font(line, left_w - 5.0, 2.6, 1.5) for line in note_lines),
            default=2.6,
        )
        notes_h = min(inner_h * 0.4, 6.0 + note_font * 1.6 * (len(note_lines) + 1))
        notes = (border[0], border[3] - notes_h, border[0] + left_w, border[3])

        area = (border[0], border[1], border[0] + left_w, notes[1] - _GUTTER)
        area_w = area[2] - area[0]
        area_h = max(20.0, area[3] - area[1])

        rows = data.rows()
        bottom = min(_BOTTOM_BASE + _ROW_PITCH * len(rows), area_h * 0.5)
        usable_w = max(10.0, area_w - _LEFT_ALLOWANCE - _RIGHT_ALLOWANCE)
        usable_h = max(10.0, area_h - _TOP_ALLOWANCE - bottom)

        half_w, half_h = self._content_half_extents(data)
        if self.options.scale is not None:
            scale = float(self.options.scale)
        else:
            raw = min(usable_w / (2 * half_w), usable_h / (2 * half_h))
            scale = _preferred_scale(raw)

        return Layout(
            sheet=sheet,
            border=border,
            area=area,
            notes=notes,
            schedule=schedule,
            title_block=title_block,
            scale=scale,
            origin_x=area[0] + _LEFT_ALLOWANCE + usable_w / 2.0,
            origin_y=area[1] + _TOP_ALLOWANCE + usable_h / 2.0,
            half_width=half_w,
            half_height=half_h,
            note_font=note_font,
        )

    # -- layout helpers --------------------------------------------------
    def _content_half_extents(self, data: DrillData) -> tuple[float, float]:
        """Half-width and half-height of everything drawn in model space."""
        half_w = 5.0
        half_h = 5.0
        if data.reference is not None:
            half_w = max(half_w, data.reference.width / 2.0)
            half_h = max(half_h, data.reference.height / 2.0)
        if self.options.true_size is not None:
            half_w = max(half_w, self.options.true_size[0] / 2.0)
            half_h = max(half_h, self.options.true_size[1] / 2.0)
        for hole in data.holes:
            half_w = max(half_w, abs(hole.x) + hole.diameter / 2.0)
            half_h = max(half_h, abs(hole.y) + hole.diameter / 2.0)
        return half_w, half_h

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
        group = _sub(root, "g", **{"class": "outlines"})
        if data.reference is not None:
            self._rounded(
                group,
                layout,
                data.reference.width,
                data.reference.height,
                cls="outline",
                stroke=INK,
                stroke_width=0.4,
            )
        if self.options.true_size is not None:
            width, height = self.options.true_size
            self._rounded(
                group,
                layout,
                width,
                height,
                cls="true-size",
                stroke=TRUE_SIZE_COLOUR,
                stroke_width=0.35,
                dash="3 1.5",
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
        dash: str | None = None,
    ) -> None:
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
            stroke_dasharray=dash,
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
        flagged = _flagged_holes(data.diagnostics)

        for index, hole in enumerate(data.holes, start=1):
            cx, cy = layout.point(hole.x, hole.y)
            radius = max(0.4, layout.length(hole.diameter) / 2.0)
            is_dup = _is_flagged(hole, flagged)
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

            self._balloon(group, cx, cy, radius, index)

    def _balloon(
        self, parent: ET.Element, cx: float, cy: float, radius: float, number: int
    ) -> None:
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
        rows = data.rows()
        content_bottom = layout.point(0.0, -layout.half_height)[1]
        edge = data.reference.width / 2.0 if data.reference is not None else None

        for level, (row_y, holes) in enumerate(reversed(rows)):
            stations = [hole.x for hole in holes]
            if edge is not None:
                stations = [-edge, *stations, edge]
            stations = _dedupe_sorted(stations)
            if len(stations) < 2:
                continue

            chain = _sub(parent, "g", **{"class": "dim-chain"})
            dim_y = content_bottom + 8.0 + _ROW_PITCH * level

            for x in stations:
                sx, sy = layout.point(x, row_y)
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

            for start, end in zip(stations, stations[1:]):
                x1 = layout.point(start, 0.0)[0]
                x2 = layout.point(end, 0.0)[0]
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
                label = f"{end - start:.2f}"
                _text(
                    chain,
                    (x1 + x2) / 2.0,
                    dim_y - 1.2,
                    _fits(label, 2.2, abs(x2 - x1) + 6.0),
                    2.2,
                    anchor="middle",
                    cls="dim-text",
                )

    def _draw_overall(self, parent: ET.Element, layout: Layout, data: DrillData) -> None:
        if data.reference is not None:
            width, height = data.reference.width, data.reference.height
        else:
            xs = [hole.x for hole in data.holes]
            ys = [hole.y for hole in data.holes]
            if not xs:
                return
            width, height = max(xs) - min(xs), max(ys) - min(ys)
        if width <= 0 and height <= 0:
            return

        group = _sub(parent, "g", **{"class": "dim-overall-group"})

        if width > 0:
            left = layout.point(-width / 2.0, 0.0)[0]
            right = layout.point(width / 2.0, 0.0)[0]
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
                f"{width:.2f}",
                2.4,
                anchor="middle",
                cls="dim-overall",
            )

        if height > 0:
            top = layout.point(0.0, height / 2.0)[1]
            bottom = layout.point(0.0, -height / 2.0)[1]
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
                f"{height:.2f}",
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

        summary_lines = len(tools)
        available = (y1 - y0) - 8.0
        needed = len(data.holes) + 2 + summary_lines + 1
        pitch = min(4.6, available / max(1, needed))
        shown = data.holes
        overflow = 0
        if pitch < 1.6:
            pitch = 1.6
            capacity = int(available / pitch) - (3 + summary_lines)
            capacity = max(0, capacity)
            overflow = len(data.holes) - capacity
            shown = data.holes[:capacity]
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
        for (cx, anchor), label, cls in zip(
            columns,
            ("NO.", "X", "Y", "⌀ mm", "TOOL"),
            ("sched-head", "sched-head", "sched-head", "sched-head", "sched-head"),
        ):
            _text(group, cx, y, label, font, anchor=anchor, cls=cls, weight="bold")
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

        flagged = _flagged_holes(data.diagnostics)
        for index, hole in enumerate(shown, start=1):
            y += pitch
            row = _sub(group, "g", **{"class": "sched-row"})
            colour = RED if _is_flagged(hole, flagged) else None
            cells = (
                (str(index), "sched-no"),
                # format_mm, not an f-string: a hole at -0.0004 printed "-0.00"
                # here while the Excellon writer printed "0.000" for the very
                # same hole.
                (format_mm(hole.x, 2), "sched-x"),
                (format_mm(hole.y, 2), "sched-y"),
                (f"⌀{format_mm(hole.diameter, 2)}", "sched-dia"),
                (f"T{tools[hole.diameter]}", "sched-tool"),
            )
            for (cx, anchor), (value, cls) in zip(columns, cells):
                _text(
                    row,
                    cx,
                    y,
                    _fits(value, font, cell_w),
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
                f"… {overflow} further holes not listed",
                font,
                cls="sched-overflow",
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
        for diameter, tool in tools.items():
            y += pitch
            _text(
                group,
                x0 + 2.0,
                y,
                _fits(
                    f"T{tool}  ⌀{format_mm(diameter, 2)} mm  QTY {counts[diameter]}",
                    font,
                    width - 4.0,
                ),
                font,
                cls="sched-summary",
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
        company_font = _fit_font(options.company, inner, 4.4, 2.2)
        _text(
            group,
            x0 + 2.0,
            y0 + 5.4,
            _fits(options.company, company_font, inner),
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
            f"SHEET 1 OF 1   SIZE {layout.sheet.name}",
            f"UNITS mm   SCALE {layout.scale_label}",
            f"GRID {_trim(options.grid)} mm   HOLES {len(data.holes)}",
            "THIRD ANGLE PROJECTION — DO NOT SCALE FROM DRAWING",
            f"SOURCE  {data.source.path or '—'}",
            f"LAYERS  drill={data.source.drill_layer or '—'} "
            f"ref={data.source.reference_layer or '—'}",
        ]
        step = min(4.2, max(2.4, (y1 - (y0 + 9.0) - 1.5) / len(lines)))
        font = max(1.6, min(2.8, step * 0.62))
        y = y0 + 8.0
        for line in lines:
            y += step
            _text(group, x0 + 2.0, y, _fits(line, font, inner), font, cls="tb")

    # -- notes -----------------------------------------------------------
    def _note_lines(self, data: DrillData) -> list[str]:
        lines: list[str] = []
        for index, diagnostic in enumerate(data.diagnostics, start=1):
            prefix = {
                Severity.WARNING: "WARNING  ",
                Severity.ERROR: "ERROR  ",
            }.get(diagnostic.severity, "")
            lines.append(f"{index}. {prefix}{diagnostic.message}")
        if not lines:
            lines.append("1. No diagnostics were raised for this panel.")
        return lines

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

        severities = [d.severity for d in data.diagnostics] or [Severity.INFO]
        lines = self._note_lines(data)
        width = x1 - x0 - 5.0
        limit = y1 - 1.0
        y = y0 + font * 1.6
        for index, (severity, line) in enumerate(zip(severities, lines)):
            y += font * 1.6
            if y > limit:
                break
            remaining = len(lines) - index
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
                    _fits(f"… {remaining} further notes not listed", font, width),
                    font,
                    cls="note note-overflow",
                    fill=RED,
                )
                break
            classification = {
                Severity.WARNING: "note note-warning",
                Severity.ERROR: "note note-error",
            }.get(severity, "note note-info")
            # Inline style, not fill= : the stylesheet's text{fill:…} rule would
            # win over a presentation attribute and the note would render black.
            colour = RED if severity in (Severity.WARNING, Severity.ERROR) else None
            _text(
                group,
                x0 + 2.5,
                y,
                _fits(line, font, width),
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


def _preferred_scale(raw: float) -> float:
    if raw <= 0 or not math.isfinite(raw):
        return 1.0
    for candidate in PREFERRED_SCALES:
        if candidate <= raw:
            return candidate
    return raw


def _dedupe_sorted(values: Iterable[float], tolerance: float = 1e-6) -> list[float]:
    ordered = sorted(values)
    out: list[float] = []
    for value in ordered:
        if not out or abs(value - out[-1]) > tolerance:
            out.append(value)
    return out


def _flagged_holes(
    diagnostics: Sequence[Diagnostic],
) -> frozenset[tuple[float, float, float]]:
    """The ``(x, y, ⌀)`` of every hole ``Deduplicate`` kept and reported.

    ``Deduplicate`` sets ``location`` to the surviving hole's exact post-dedupe
    coordinates and puts that hole's diameter in the diagnostic's payload, so
    identifying the hole is a lookup, not a computation.
    """
    return frozenset(
        (d.location[0], d.location[1], d.get("diameter"))
        for d in diagnostics
        if d.code == DUP_CODE and d.location is not None and d.get("diameter") is not None
    )


def _is_flagged(hole: Hole, flagged: frozenset[tuple[float, float, float]]) -> bool:
    """Exact match on position *and* diameter — no tolerance lives here.

    The emitter used to match on position within a hardcoded 0.05 mm, which is
    neither ``Deduplicate``'s rule (proximity **and** equal diameter) nor
    necessarily its tolerance (``--dedupe-tolerance`` is a user's to choose).
    A ⌀5 hole 0.03 mm from a flagged ⌀7 was drawn red and ringed on the sheet
    the machinist reads, while the pipeline had correctly kept both. Whether a
    hole is a duplicate is decided once, upstream; this reads the answer.
    """
    return (hole.x, hole.y, hole.diameter) in flagged
