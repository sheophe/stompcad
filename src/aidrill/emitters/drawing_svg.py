"""``drawing-svg`` — an engineering drawing of the drill data (SPEC §7).

This is the sheet you hand to whoever drills the panel. It is **not** a render of
the artwork: an earlier attempt drew the Illustrator Graphics layer with
substitute fonts and bbox-only text metrics, which produced something that
looked like the panel, wasn't the panel, and told the machinist nothing. Only
drill data is drawn here — holes, dimensions, a schedule, and the pipeline's
diagnostics as notes.

What ends up on the sheet:

* a border, default A4 landscape, sheet configurable
* the reference outline as a rounded rectangle
* chain-dash centrelines and an origin symbol at (0, 0)
* every hole at true diameter with a centre mark and a balloon carrying its
  ``Hole.index`` — the same number the report, the JSON and every diagnostic
  use, so that "hole 2" names one hole across all four
* one chain dimension per Y row (``DrillData.rows()``) with extension lines,
  plus overall width and height
* a hole schedule — No. / X / Y / ⌀ / TOOL — with tool numbers taken from
  ``DrillData.tools()`` and never renumbered, and a per-tool quantity summary
* a title block naming the enclosure the panel was identified as, and a NOTES
  block, warnings and errors in red

Nothing on the sheet runs out of its box, and **nothing leaves it in silence**.
A panel of 120 distinct diameters used to print 36 summary lines through the
title block and 3 off the page; a 15-row panel — ordinary work — drew its
topmost chain dimensions off the sheet, leaving holes with no dimension beside
them. Both came from the same shape of mistake: :meth:`layout` clamped the
capacity arithmetic and the loops that spend it were unclamped, so the deficit
was discarded rather than reported. Every list that can be cut short now goes
through :func:`_allot`, which reserves the line its own marker needs, and every
marker names what was dropped and how many — a tool is not a hole, and a sheet
listing fewer tools than the drill file defines is ADR-0001's failure with the
drawing as the wrong artifact.

Two things about SVG that this module is careful about, both learned the hard
way:

1. **A CSS rule in ``<style>`` beats a ``fill=`` presentation attribute.** With
   ``text{fill:#111111}`` in the stylesheet, ``<text fill="red">`` renders
   black. Every coloured string here therefore carries ``style="fill:…"``, which
   does win. The same trap applies to ``font-size``, so the stylesheet declares
   none and every ``<text>`` sets its own.
2. **Vertical dimension labels must be rotated.** An unrotated label on the
   left-hand height dimension runs straight off the side of the sheet.

The emitter re-derives nothing and remembers nothing: no snapping, no diameter
clustering, no deduplication, and no second copy of a pipeline setting. It reads
``tools()``, ``tool_counts()``, ``rows()``, ``diagnostics`` and ``processing``,
and draws what it is given. Four facts on the sheet each have exactly one honest
source, and every one of them can go stale in silence if taken from anywhere
else:

* *Which* holes are duplicates comes from the ``duplicate-hole`` diagnostics'
  ``hole_index`` — see :func:`_flagged_holes`. Matching on coordinates instead
  worked only until a stage moved the survivor, and
  ``Pipeline([Deduplicate, SnapPositions])`` is a legal order.
* *What grid* the holes are on comes from the recorded ``snap`` run — see
  :func:`_grid_note`. Taking it through ``DrawingOptions`` instead means taking
  a default when the caller gives none, and data snapped at 0.5 gets stamped
  0.25.
* *How a diameter is spelled* comes from the drill standard the recorded
  ``snap-diameters`` run names — see :func:`_diameter_label`. A millimetre
  spelling is honest for the metric drawer and not for the fractional one, where
  1/64" is 0.396875 mm and every decimal-millimetre label is a rounding of a
  size that is exact.
* *Which enclosure* the panel is comes from ``DrillData.enclosure`` — see
  :func:`_enclosure_note`.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, ClassVar, Iterable, Sequence

from ..formatting import format_mm
from ..model import Diagnostic, DrillData, EnclosureMatch, Hole, Severity
from ..pipeline import DRILL_STANDARDS
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

#: The ``StageRun`` name the title block's grid is read from, and the parameter
#: within it. Names the *record*, not the class: the emitter reads provenance and
#: has no import of, or opinion about, which stage wrote it.
SNAP_STAGE = "snap"
GRID_PARAMETER = "grid_mm"

#: The same idiom for the schedule's diameter spelling: the ``StageRun`` name
#: the drill standard is read from, and the parameter within it. The standard
#: itself is looked up by name in ``DRILL_STANDARDS``, so the record stays a
#: name rather than 183 sizes.
DIAMETER_STAGE = "snap-diameters"
STANDARD_PARAMETER = "standard"


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

#: The smallest a title block line is allowed to shrink to earn its width. A
#: line that still does not fit at this size is truncated, so the enclosure
#: note composes its candidate list against this size and no other: it is the
#: widest string the line can ever be asked to carry.
_TITLE_MIN_FONT = 1.6


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


def _capacity(width: float, size: float) -> int:
    """How many characters :func:`_fits` will keep at this size.

    One formula, two callers. A line composed to a capacity that ``_fits``
    disagreed with would be chopped anyway, which is how the title block's
    candidate list came to end in an ellipsis that named no number.
    """
    if width <= 0 or size <= 0:
        return 0
    return max(1, int(width / (CHAR_RATIO * size)))


def _fits(text: str, size: float, width: float) -> str:
    """Truncate ``text`` so its estimated extent stays inside ``width``."""
    if width <= 0:
        return ""
    limit = _capacity(width, size)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _allot(count: int, room: int) -> tuple[int, int]:
    """How many of ``count`` items to draw in ``room`` lines, and how many are left.

    Not ``min(count, room)``: announcing the leftovers costs a line of its own,
    and a marker drawn in a line that does not exist is the very failure it is
    there to report. Both of this module's overflowing loops came from a
    capacity that was clamped in the arithmetic and unclamped in the drawing —
    the tool summary ran through the title block and off the page, and the chain
    dimensions off the bottom of the sheet — so the deficit is returned here
    rather than discarded, and every caller has to say what it did with it.
    """
    if count <= room:
        return count, 0
    shown = max(0, room - 1)
    return shown, count - shown


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
        """One panel, one outline. Which enclosure it is, the title block says.

        There was a second, dashed rectangle here — the operator's own ``WxH``,
        drawn as a check on the first. See the module docstring: once the
        pipeline identifies the enclosure, the check either coincides with the
        outline exactly or is better stated in words than as two rectangles a
        millimetre apart.
        """
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
        flagged = _flagged_holes(data.diagnostics)

        for hole in data.holes:
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

            self._balloon(group, cx, cy, radius, hole.index)

    def _balloon(
        self, parent: ET.Element, cx: float, cy: float, radius: float, number: int
    ) -> None:
        """The balloon carries the hole's ``index``, never its place in the tuple.

        Numbering 1..n down ``data.holes`` gave the sheet a private numbering
        that agreed with nothing: "hole 2" was the duplicate at (−40, 18) to the
        JSON and every diagnostic, and the clean hole at (−20, 18) here. The
        numbers are therefore not contiguous — a gap is a hole the pipeline
        dropped or deduped, which is a fact worth reading off the sheet.
        """
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
        """One chain per Y row, stacked below the panel — as many as fit.

        ``layout`` reserves ``_BOTTOM_BASE + _ROW_PITCH * len(rows)`` for these
        and then clamps the reservation to half the drawing area; this loop drew
        one chain per row regardless. A 15-row panel — ordinary work — put its
        topmost chains off the sheet, and because the stack is built from the
        bottom row up, the rows that lost their dimension were the ones nearest
        the top of the panel. Their holes were still drawn, so the sheet showed
        holes with no dimension and no note saying one was missing.
        """
        rows = data.rows()
        content_bottom = layout.point(0.0, -layout.half_height)[1]
        edge = data.reference.width / 2.0 if data.reference is not None else None

        top = content_bottom + 8.0
        # The extension lines overshoot the dimension line by 1.5, so that is
        # the lowest ink a chain puts on the sheet.
        room = int((layout.area[3] - 1.5 - top) / _ROW_PITCH) + 1
        # Bottom row first, which is the order they stack away from the panel.
        ordered = list(reversed(rows))
        drawn, omitted = _allot(len(ordered), room)
        if omitted:
            _text(
                parent,
                layout.area[0] + 2.0,
                top + _ROW_PITCH * drawn,
                _fits(
                    f"… {omitted} further row dimensions not shown",
                    2.2,
                    layout.area[2] - layout.area[0] - 4.0,
                ),
                2.2,
                cls="dim-overflow",
                fill=RED,
            )

        for level, (row_y, holes) in enumerate(ordered[:drawn]):
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
        diameter_label = _diameter_label(data)

        # Two lists share one box, and both used to be sized as though the other
        # were free. The capacity arithmetic subtracted the summary and then
        # clamped the remainder to zero, throwing the deficit away, while the
        # summary loop below still drew one line per tool: 120 distinct
        # diameters put 36 lines through the title block and 3 off the page, and
        # the only notice printed said "further holes not listed" — a true
        # statement about a different quantity.
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
            kept_tools, tool_overflow = _allot(summary_lines, room_for_tools)
            listed = listed[:kept_tools]
            kept_holes, overflow = _allot(len(data.holes), max(0, body - room_for_tools))
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
        for (cx, anchor), label, cls in zip(
            columns,
            # No "mm" in the heading: the cells below carry their own units,
            # and a fractional standard spells this column ``⌀9/32"``.
            ("NO.", "X", "Y", "⌀", "TOOL"),
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
        for hole in shown:
            y += pitch
            row = _sub(group, "g", **{"class": "sched-row"})
            colour = RED if _is_flagged(hole, flagged) else None
            cells = (
                # The hole's own id, not its place in the tuple — see
                # ``_balloon``. NO. is the column a diagnostic is joined on.
                (str(hole.index), "sched-no"),
                # format_mm, not an f-string: a hole at -0.0004 printed "-0.00"
                # here while the Excellon writer printed "0.000" for the very
                # same hole.
                (format_mm(hole.x, 2), "sched-x"),
                (format_mm(hole.y, 2), "sched-y"),
                (diameter_label(hole.diameter), "sched-dia"),
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
                _fits(f"… {overflow} further holes not listed", font, width - 4.0),
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
        for diameter, tool in listed:
            y += pitch
            _text(
                group,
                x0 + 2.0,
                y,
                _fits(
                    f"T{tool}  {diameter_label(diameter)}  QTY {counts[diameter]}",
                    font,
                    width - 4.0,
                ),
                font,
                cls="sched-summary",
            )
        if tool_overflow:
            y += pitch
            # Its own wording, and its own class. A tool the sheet does not name
            # is a bit that does not get fitted, and saying "holes" about it —
            # which is all the schedule used to say — describes the wrong
            # quantity while the drill file quietly defines every one of them.
            _text(
                group,
                x0 + 2.0,
                y,
                _fits(f"… {tool_overflow} further tools not listed", font, width - 4.0),
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
            _enclosure_note(data, _capacity(inner, _TITLE_MIN_FONT)),
            f"SHEET 1 OF 1   SIZE {layout.sheet.name}",
            f"UNITS mm   SCALE {layout.scale_label}",
            f"{_grid_note(data)}   HOLES {len(data.holes)}",
            "THIRD ANGLE PROJECTION — DO NOT SCALE FROM DRAWING",
            f"SOURCE  {data.source.path or '—'}",
            f"LAYERS  drill={data.source.drill_layer or '—'} "
            f"ref={data.source.reference_layer or '—'}",
        ]
        step = min(4.2, max(2.4, (y1 - (y0 + 9.0) - 1.5) / len(lines)))
        font = max(_TITLE_MIN_FONT, min(2.8, step * 0.62))
        y = y0 + 8.0
        for line in lines:
            y += step
            # Shrink the line before chopping it. Every line here is a claim the
            # sheet makes, and a claim that does not fit is worth a smaller font
            # rather than an ellipsis: ``_designator`` elides the series so that
            # a four-candidate footprint fits, and adding ``ROTATED`` to the same
            # line took two of the four away again.
            size = _fit_font(line, inner, font, _TITLE_MIN_FONT)
            _text(group, x0 + 2.0, y, _fits(line, size, inner), size, cls="tb")

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


def _grid_note(data: DrillData) -> str:
    """What the title block says about the grid, read from what actually ran.

    The grid used to arrive through ``DrawingOptions``, defaulting to 0.25, so a
    library consumer who snapped at 0.5 and called ``emit`` got a sheet stamped
    with a pitch the holes had never been near. The number is a fact about the
    data, so it comes out of the data.

    Three answers, all of them honest:

    * a recorded positive pitch — print it;
    * a recorded ``0`` — ``SnapPositions`` ran as the identity (that is exactly
      what its ``enabled: False`` records), so say OFF rather than "GRID 0 mm",
      which reads as a pitch;
    * no record at all — say so. Hand-built ``DrillData`` never met a pipeline,
      and a plausible-looking default is the failure this whole change is about.
    """
    run = data.last_run(SNAP_STAGE)
    grid = None if run is None else run.get(GRID_PARAMETER)
    # ``StageRun`` payloads are deliberately generic, so a value that is not a
    # number is not a pitch and gets the same answer as no value at all. ``bool``
    # is excluded explicitly because it is a legal ``ParameterValue`` *and* an
    # ``int`` in Python: a recorded ``True`` would otherwise stamp the sheet
    # "GRID 1 mm", which is a plausible, wrong and entirely drillable number.
    if not isinstance(grid, (int, float)) or isinstance(grid, bool):
        return "GRID NOT RECORDED"
    if grid > 0:
        return f"GRID {_trim(float(grid))} mm"
    return "GRID OFF"


def _millimetre_label(diameter: float) -> str:
    """``⌀7.00 mm`` — the fallback spelling, when no standard was recorded.

    Through ``format_mm`` rather than an f-string for the reason the schedule's
    X and Y are: a value that rounds to zero from below printed ``-0.00`` here
    while the Excellon writer printed ``0.000`` for the same hole.
    """
    return f"⌀{format_mm(diameter, 2)} mm"


def _diameter_label(data: DrillData) -> Callable[[float], str]:
    """How the schedule spells a diameter, taken from the standard that ran.

    The drill table owns the display form, and ``DrillStandard.label`` is a
    *function* rather than a decimal precision because no single precision can
    serve both drawers: metric sizes are unique and truthful at 2 dp, while the
    fractional series is truthful at none — 1/64" is 0.396875 mm, and ``⌀0.40
    mm`` is a bit that exists nowhere. A fractional bit's honest name is its
    fraction, which is also what is stamped on it.

    Read out of provenance the way :func:`_grid_note` reads the grid, and by
    name: ``snap-diameters`` records ``standard`` as a word, so the emitter
    looks it up in ``DRILL_STANDARDS`` and holds no table of its own. A name the
    registry does not hold — a hand-built standard, or a document written by a
    later version of this tool — resolves to nothing, and the fallback states
    millimetres rather than inventing a spelling for a drawer it cannot see.
    Narrowing does not matter here: ``select`` copies the label through, so the
    registry's entry spells a narrowed run's sizes exactly as the run would.
    """
    run = data.last_run(DIAMETER_STAGE)
    name = None if run is None else run.get(STANDARD_PARAMETER)
    # ``StageRun`` payloads are generic, so a value that is not a name cannot
    # name a standard. This guard is for the type checker rather than for the
    # output — every ``ParameterValue`` is hashable, so ``get`` would return
    # ``None`` for a non-name anyway — and it is kept because the alternative is
    # a lookup whose key type is unchecked. Unlike ``_grid_note``'s
    # ``isinstance``, which is load-bearing: a recorded ``True`` really would
    # print there.
    if not isinstance(name, str):
        return _millimetre_label
    standard = DRILL_STANDARDS.get(name)
    if standard is None:
        return _millimetre_label
    return standard.label


def _enclosure_note(data: DrillData, capacity: int) -> str:
    """What the title block says the panel is, read from the identified match.

    ``HAMMOND 1590  112 × 61 mm  CANDIDATES B / B2 / BS``. Three decisions in
    one line, each of which the drawing would otherwise get wrong:

    * **The catalogue footprint, never the measured outline.** The artwork comes
      to 113.000 × 60.000 for a 1590B; 112 × 61 is the number on the datasheet
      the operator orders the box by, and the number every other consumer of
      this panel has already agreed on.
    * **Candidates, never a part.** A 2-D outline identifies a footprint — 37
      catalogue parts collapse into 22 footprints because many differ only in
      height — so the sheet lists every part sharing the outline and names one
      only when the operator declared it with ``--case``. The declared part
      replaces the list rather than joining it: the question the list asks has
      been answered.
    * **The order it was given.** ``candidates`` is rendered as handed over,
      because ordering it here would be the emitter deciding a fact the match
      already carries. Sorting happens to be invisible today — ``footprints()``
      sorts, so all 22 production footprints arrive alphabetical — which is
      exactly why it must not be done here: whoever builds the match owns the
      order, and a matcher that later ordered by height would find the drawing
      quietly undoing it.

    ``rotated`` is stated because the two numbers on the sheet would otherwise
    contradict each other: the match keeps the catalogue's orientation while the
    drawing dimensions the artwork's, so a turned 1590B is dimensioned 61 × 112
    beside an enclosure line reading 112 × 61.

    No match at all is said out loud, for the reason :func:`_grid_note` says
    ``GRID NOT RECORDED``. A missing line reads as a Hammond case nobody wrote
    down, and "this is not a case we stock" is a legitimate outcome — the
    catalogue holds 22 footprints and the world holds rather more.

    ``capacity`` is how many characters the line may run to, and it is required
    rather than optional because there is no honest default: a note composed
    against no limit is one ``_fits`` is free to chop. Only the candidate list
    is composed against it, being the only part of the line that can be
    shortened *and still be read* — dropping a candidate and saying so leaves a
    shorter true statement, whereas a chopped line leaves ``CANDIDATES BB /
    BB2 / …``, from which nobody can tell whether one box was left off or three.
    """
    match = data.enclosure
    if match is None:
        return "ENCLOSURE NOT IDENTIFIED"
    size = f"{match.length_mm} × {match.width_mm} mm"
    if match.rotated:
        size += " ROTATED"
    head = f"{match.family.upper()}  {size}  "
    if match.selected_part is not None:
        return head + f"PART {match.selected_part}"
    designators = [_designator(part, match) for part in match.candidates]
    room = capacity - len(head) - len("CANDIDATES ")
    return head + "CANDIDATES " + _candidate_list(designators, room)


def _candidate_list(designators: Sequence[str], room: int) -> str:
    """``BB / BB2 / +2 MORE`` — the parts, and how many would not fit.

    A count, never a bare ellipsis. The candidates are the boxes this artwork
    could be for, and "two more, unnamed" is a question the reader can go and
    answer against the datasheet; "…" is not. The names are dropped from the
    end, so the list stays in the order the match handed it over.
    """
    text = " / ".join(designators)
    for keep in range(len(designators), 0, -1):
        text = " / ".join(designators[:keep])
        if keep < len(designators):
            text += f" / +{len(designators) - keep} MORE"
        if len(text) <= room:
            break
    return text


def _designator(part: str, match: EnclosureMatch) -> str:
    """``1590B`` under a ``Hammond 1590`` heading is the ``B`` of that series.

    The datasheet groups the parts this way and so does the line: the series is
    already printed, and repeating it four times over is what pushes a
    four-candidate footprint past the width of the title block, where ``_fits``
    truncates the last candidate away entirely. A designator that does not begin
    with the series — or one that *is* the series — is left exactly as it came,
    since eliding it would leave nothing to read.
    """
    words = match.family.split()
    # A family of no words leaves ``series`` empty, which the test below then
    # answers correctly on its own: every string starts with "" and every
    # non-empty one differs from it, so the part comes back whole. No separate
    # guard for it, because a branch no input can distinguish is a branch no
    # test can pin.
    series = words[-1] if words else ""
    if part.startswith(series) and part != series:
        return part[len(series):]
    return part


def _flagged_holes(diagnostics: Sequence[Diagnostic]) -> frozenset[float | int | str]:
    """The ``Hole.index`` of every hole ``Deduplicate`` kept and reported.

    ``hole_index`` is the survivor's stable identity, which is why it exists: a
    coordinate is only true until the next stage moves the hole, and ``location``
    is written at the moment of the report. A diagnostic carrying no id names no
    hole this emitter can place, so it rings nothing rather than guessing.

    Typed as ``Diagnostic.data``'s own value type and not ``int`` on purpose. The
    payload is generic and the set is only ever tested with ``in``, so a value
    that is not an id simply matches no hole — whereas an ``isinstance(…, int)``
    filter would also throw away a ``3.0`` that equals, and would have correctly
    rung, hole 3. Dropping a ring in silence is the failure this function was
    rewritten to fix, so no filter is added to narrow the annotation.
    """
    return frozenset(
        index
        for d in diagnostics
        if d.code == DUP_CODE and (index := d.get("hole_index")) is not None
    )


def _is_flagged(hole: Hole, flagged: frozenset[float | int | str]) -> bool:
    """Identity, not geometry. Whoever the pipeline named is who gets the ring.

    Two earlier versions decided this from positions. The first matched within a
    hardcoded 0.05 mm and ringed a ⌀5 hole sitting beside a flagged ⌀7 that the
    pipeline had correctly kept. The second matched exactly, on position and
    diameter, and so was right only while nothing moved the survivor afterwards
    — ``Pipeline([Deduplicate, SnapPositions])`` is a legal order, and under it
    the ring silently vanished from the sheet while the CLI still reported the
    duplicate.
    """
    return hole.index in flagged
