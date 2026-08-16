"""Sheet layout: given a sheet and a panel, where everything goes.

Two directions on one relation. ``scale=None`` fixes the sheet and fits the
scale to it; a float fixes the scale and leaves the sheet to the caller, which
walks ``choose_sheet`` down the ISO 5457 ladder. ``fits`` is what the walk asks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ...model import DrillData
from ...units import mm_from_nm
from .content import fit_font, note_lines
from .sheet import Box, FrameStyle, Sheet

__all__ = [
    "Layout",
    "choose_sheet",
    "content_half_extents",
    "preferred_scale",
    "PREFERRED_SCALES",
    "LEFT_ALLOWANCE",
    "RIGHT_ALLOWANCE",
    "TOP_ALLOWANCE",
    "BOTTOM_BASE",
    "ROW_PITCH",
    "GUTTER",
    "TITLE_MIN_FONT",
]

#: Scales an engineer expects to read in a title block. The fitted scale is
#: rounded *down* to one of these, so fitting can never overflow.
PREFERRED_SCALES = (
    20.0, 10.0, 5.0, 4.0, 2.0, 1.0,
    0.5, 0.4, 0.25, 0.2, 0.1, 0.05, 0.04, 0.025, 0.02, 0.01,
)

# space reserved inside the drawing area for drawing furniture, in sheet mm
LEFT_ALLOWANCE = 14.0  # left-hand height dimension (rotated label; see _draw_overall)
RIGHT_ALLOWANCE = 14.0  # balloons
TOP_ALLOWANCE = 16.0  # overall width dimension
BOTTOM_BASE = 12.0  # below the last chain dimension
ROW_PITCH = 8.0  # between stacked chain dimensions
GUTTER = 4.0

#: The smallest a title block line is allowed to shrink to earn its width. A
#: line that still does not fit at this size is truncated, so the enclosure
#: note composes its candidate list against this size and no other: it is the
#: widest string the line can ever be asked to carry.
TITLE_MIN_FONT = 1.6


def _trim(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True, slots=True)
class Layout:
    """Pure sheet geometry, independent of any backend."""

    sheet: Sheet
    frame: FrameStyle
    border: Box
    area: Box
    notes: Box
    schedule: Box
    title_block: Box
    scale: float
    origin_x: float
    origin_y: float
    half_width: float
    half_height: float
    note_font: float
    #: What the content demands of the drawing area at this scale, in sheet mm.
    needed_width: float
    needed_height: float

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

    @property
    def fits(self) -> bool:
        """Whether the sheet's drawing space holds the content at this scale.

        Asked against ``border`` — ISO 5457's tabulated drawing space — not the
        narrower ``area`` a fixed-proportion schedule column leaves behind. A
        schedule or notes box that has to omit rows has its own counted marker
        and is not grounds to consume a larger sheet.
        """
        return (
            self.needed_width <= self.border[2] - self.border[0]
            and self.needed_height <= self.border[3] - self.border[1]
        )

    @classmethod
    def for_sheet(
        cls,
        sheet: Sheet,
        data: DrillData,
        *,
        scale: float | None = None,
        frame: FrameStyle = FrameStyle.PLAIN,
    ) -> Layout:
        """Resolve the sheet's geometry; ``scale=None`` fits the content to it."""
        border = sheet.space
        inner_w = border[2] - border[0]
        inner_h = border[3] - border[1]

        right_w = min(92.0, inner_w * 0.4)
        title_h = min(46.0, inner_h * 0.35)
        right_x = border[2] - right_w
        title_block = (right_x, border[3] - title_h, border[2], border[3])
        schedule = (right_x, border[1], border[2], title_block[1] - 2.0)

        left_w = max(20.0, inner_w - right_w - GUTTER)
        notes = note_lines(data)
        note_font = min(
            (fit_font(note.text, left_w - 5.0, 2.6, 1.5) for note in notes),
            default=2.6,
        )
        notes_h = min(inner_h * 0.4, 6.0 + note_font * 1.6 * (len(notes) + 1))
        notes_box = (border[0], border[3] - notes_h, border[0] + left_w, border[3])

        area = (border[0], border[1], border[0] + left_w, notes_box[1] - GUTTER)
        area_h = max(20.0, area[3] - area[1])

        rows = data.rows()
        bottom = min(BOTTOM_BASE + ROW_PITCH * len(rows), area_h * 0.5)
        usable_w = max(10.0, (area[2] - area[0]) - LEFT_ALLOWANCE - RIGHT_ALLOWANCE)
        usable_h = max(10.0, area_h - TOP_ALLOWANCE - bottom)

        half_w, half_h = content_half_extents(data)
        if scale is None:
            resolved = preferred_scale(min(usable_w / (2 * half_w), usable_h / (2 * half_h)))
        else:
            resolved = float(scale)

        return cls(
            sheet=sheet,
            frame=frame,
            border=border,
            area=area,
            notes=notes_box,
            schedule=schedule,
            title_block=title_block,
            scale=resolved,
            origin_x=area[0] + LEFT_ALLOWANCE + usable_w / 2.0,
            origin_y=area[1] + TOP_ALLOWANCE + usable_h / 2.0,
            half_width=half_w,
            half_height=half_h,
            note_font=note_font,
            # The furniture is part of the demand: a panel that fits the area
            # only by overwriting its own dimension lines has not fitted.
            needed_width=2 * half_w * resolved + LEFT_ALLOWANCE + RIGHT_ALLOWANCE,
            needed_height=2 * half_h * resolved + TOP_ALLOWANCE + bottom,
        )


def content_half_extents(data: DrillData) -> tuple[float, float]:
    """Return layout extents in model millimetres, with a 5 mm empty floor."""
    half_w = 5.0
    half_h = 5.0
    if data.reference is not None:
        half_w = max(half_w, mm_from_nm(data.reference.width_nm) / 2.0)
        half_h = max(half_h, mm_from_nm(data.reference.height_nm) / 2.0)
    for hole in data.holes:
        radius = mm_from_nm(hole.diameter_nm) / 2.0
        half_w = max(half_w, abs(mm_from_nm(hole.x_nm)) + radius)
        half_h = max(half_h, abs(mm_from_nm(hole.y_nm)) + radius)
    return half_w, half_h


def preferred_scale(raw: float) -> float:
    # A ``nan`` request has no ordering to round down through, so it falls
    # back to 1:1; an infinite one does have one, and rounds down to the
    # largest scale on the ladder like any other value above it.
    if raw <= 0 or math.isnan(raw):
        return 1.0
    for candidate in PREFERRED_SCALES:
        if candidate <= raw:
            return candidate
    return raw


def choose_sheet(
    data: DrillData, candidates: Sequence[Sheet], *, frame: FrameStyle
) -> Layout:
    """Return the first candidate that holds ``data`` at 1:1, else the last.

    ISO 5457 3.1 asks for the smallest sheet that serves, and the candidates are
    in ascending area, so the first fit is that sheet. Past the end of the ladder
    the scale is still not reduced; the caller states the overflow instead.
    """
    layout = None
    for sheet in candidates:
        layout = Layout.for_sheet(sheet, data, scale=1.0, frame=frame)
        if layout.fits:
            return layout
    if layout is None:
        raise ValueError("choose_sheet needs at least one candidate sheet")
    return layout
