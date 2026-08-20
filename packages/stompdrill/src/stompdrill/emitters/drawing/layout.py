"""Sheet layout: given a sheet and a panel, where everything goes.

Two directions on one relation. ``scale=None`` fixes the sheet and fits the
scale to it; a float fixes the scale and leaves the sheet to the caller, which
walks ``choose_sheet`` down the ISO 5457 ladder. ``fits`` is what the walk asks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stompmodel.model import DrillData
from stompmodel.units import mm_from_nm

from .content import Note, fit_font, note_lines, row_chains
from .sheet import TITLE_BLOCK_WIDTH, Box, FrameStyle, Sheet

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
    "BALLOON_LEADER",
    "BALLOON_RADIUS",
    "HOLE_MIN_RADIUS",
    "CHAIN_STANDOFF",
    "LEVEL_CHAIN_LABEL",
    "MAX_BALLOON_OVERHANG",
    "TITLE_BLOCK_HEIGHT",
    "TITLE_BLOCK_SHARE",
    "SCHEDULE_MIN_WIDTH",
    "SCHEDULE_MAX_WIDTH",
    "SCHEDULE_BAND_SHARE",
    "NOTES_BAND_HEIGHT",
    "TITLE_MIN_FONT",
]

#: Scales an engineer expects to read in a title block. The fitted scale is
#: rounded *down* to one of these, so fitting can never overflow.
PREFERRED_SCALES = (
    20.0, 10.0, 5.0, 4.0, 2.0, 1.0,
    0.5, 0.4, 0.25, 0.2, 0.1, 0.05, 0.04, 0.025, 0.02, 0.01,
)

# space reserved inside the drawing area for drawing furniture, in sheet mm
LEFT_ALLOWANCE = 14.0  # left-hand height dimension (rotated label; see build._build_overall)
TOP_ALLOWANCE = 16.0  # overall width dimension
BOTTOM_BASE = 12.0  # below the last chain dimension
ROW_PITCH = 8.0  # between stacked chain dimensions
GUTTER = 4.0

#: How a balloon is drawn: a leader this far beyond the hole's own radius, then
#: a circle of this radius; and the smallest radius a hole is ever drawn at.
#: ``build`` draws them and the right-hand reservation below budgets for them,
#: so, like ``ROW_PITCH``, they are stated once and read from both places.
BALLOON_LEADER = 7.0
BALLOON_RADIUS = 3.0
HOLE_MIN_RADIUS = 0.4

#: Between the content already drawn and the first dimension line standing off
#: it. The row chains below the panel and the chain of levels beside it read as
#: one system, so they stand off by the one distance rather than by two literals
#: that agree. ``LEVEL_CHAIN_LABEL`` is the room the level chain's rotated label
#: takes outboard of itself.
CHAIN_STANDOFF = 8.0
LEVEL_CHAIN_LABEL = 4.0

#: The furthest past the content extent a balloon can reach. It leaves its hole
#: at 45°, so the hole's own radius — which the extent already counts — eats
#: into the leader's horizontal component, and the bound falls out at the drawn
#: radius that gives back the least. Most panels are nowhere near it: a balloon
#: only escapes the outline when its hole is hard against the edge.
MAX_BALLOON_OVERHANG = math.sqrt(0.5) * (HOLE_MIN_RADIUS + BALLOON_LEADER) + BALLOON_RADIUS

#: Balloons, then the chain, then its label. A fitted sheet reserves this before
#: it knows the scale, so it is the bound above and not the overhang ``build``
#: measures when it places the chain; placement stays inside it because the
#: measurement can never exceed the bound.
RIGHT_ALLOWANCE = MAX_BALLOON_OVERHANG + CHAIN_STANDOFF + LEVEL_CHAIN_LABEL

#: The deepest the title block is drawn, and the share of a short drawing space
#: it may take instead. ISO 7200 fixes the block's width, not its height.
TITLE_BLOCK_HEIGHT = 46.0
TITLE_BLOCK_SHARE = 0.35

#: The narrowest a schedule can be and still rule five columns. The ISO block is
#: a fixed 180 mm at the foot of the drawing space, so on A4 — where that is the
#: whole width — nothing stands beside it and the schedule takes a band above.
SCHEDULE_MIN_WIDTH = 60.0
#: The widest it is drawn beside the block, so a large sheet keeps a table
#: shaped like a table rather than one ruled across a metre of paper.
SCHEDULE_MAX_WIDTH = 210.0
#: What the banded schedule takes of the drawing space's height.
SCHEDULE_BAND_SHARE = 0.28

#: How deep the ISO notes band is: the heading and four notes at the size the
#: sheet letters them. It does not count the notes, and no sheet's paper depends
#: on how many findings a panel gathered — the panel did not get bigger. What
#: does not fit is stated as a count, as the schedule and chain stack state one.
NOTES_BAND_HEIGHT = 24.0

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
        """Whether the box the drawing occupies holds the content at this scale.

        Under ISO 5457 the furniture is ruled across the foot of the tabulated
        drawing space, so ``area`` is what is left for the drawing, and it is
        both what the demand is capped by and what the demand is tested against.
        The plain sheet rules its columns inside the space and has always been
        measured against the whole of it. Either way a schedule or notes box
        that omits rows carries its own counted marker and is not grounds to
        consume a larger sheet.
        """
        x0, y0, x1, y1 = self.area if self.frame is FrameStyle.ISO_5457 else self.border
        return self.needed_width <= x1 - x0 and self.needed_height <= y1 - y0

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
        notes = note_lines(data)

        if frame is FrameStyle.ISO_5457:
            title_block, schedule, foot = _iso_foot(border, inner_w, inner_h)
            note_font = _note_font(notes, inner_w)
            # The furniture runs across the foot of the drawing space, so the
            # notes band spans it too and the drawing keeps one box above them.
            # The band is a fixed depth: what it cannot show it counts, and a
            # panel that gathered findings is not a panel that grew.
            notes_h = min(inner_h * 0.4, NOTES_BAND_HEIGHT)
            notes_box = (border[0], foot - GUTTER - notes_h, border[2], foot - GUTTER)
            area = (border[0], border[1], border[2], notes_box[1] - GUTTER)
        else:
            right_w = min(92.0, inner_w * 0.4)
            title_h = min(TITLE_BLOCK_HEIGHT, inner_h * TITLE_BLOCK_SHARE)
            right_x = border[2] - right_w
            title_block = (right_x, border[3] - title_h, border[2], border[3])
            schedule = (right_x, border[1], border[2], title_block[1] - 2.0)
            text_w = max(20.0, inner_w - right_w - GUTTER)
            note_font = _note_font(notes, text_w)
            notes_h = min(inner_h * 0.4, 6.0 + note_font * 1.6 * (len(notes) + 1))
            notes_box = (border[0], border[3] - notes_h, border[0] + text_w, border[3])
            area = (border[0], border[1], border[0] + text_w, notes_box[1] - GUTTER)
        area_h = max(20.0, area[3] - area[1])

        # Chains, not rows: rows drilled to one pattern of X share a chain and
        # take one band between them. The stack may take half the box the
        # drawing occupies, and no more; the chains that do not fit are stated
        # as a counted omission. The cap is read off the same box ``fits``
        # measures the demand against, or the demand and the test would be
        # about two different boxes.
        bottom = min(BOTTOM_BASE + ROW_PITCH * len(row_chains(data)), area_h * 0.5)
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


def _note_font(notes: Sequence[Note], width: float) -> float:
    """The largest size every note fits at, so one box letters them alike."""
    return min((fit_font(note.text, width - 5.0, 2.6, 1.5) for note in notes), default=2.6)


def _iso_foot(border: Box, inner_w: float, inner_h: float) -> tuple[Box, Box, float]:
    """Rule the title block and schedule across the foot of the drawing space.

    ISO 7200 6 fixes the block at 180 mm and ISO 5457 4.1 puts it at the bottom
    right, which on A4 is the whole width: there the schedule takes a band above
    the block, and on a wider sheet it stands beside it. The third value is the
    top of the foot, which is where everything above it stops.
    """
    block_w = min(TITLE_BLOCK_WIDTH, inner_w)
    block_h = min(TITLE_BLOCK_HEIGHT, inner_h * TITLE_BLOCK_SHARE)
    title_block = (border[2] - block_w, border[3] - block_h, border[2], border[3])
    beside = inner_w - block_w - GUTTER
    if beside >= SCHEDULE_MIN_WIDTH:
        width = min(beside, SCHEDULE_MAX_WIDTH)
        left = title_block[0] - GUTTER - width
        return title_block, (left, title_block[1], left + width, border[3]), title_block[1]
    band_h = inner_h * SCHEDULE_BAND_SHARE
    top = title_block[1] - GUTTER - band_h
    return title_block, (border[0], top, border[2], title_block[1] - GUTTER), top


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
