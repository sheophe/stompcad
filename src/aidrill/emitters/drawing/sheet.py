"""Drawing sheets, their ISO 5457 geometry, and ISO 128-24 line groups.

Sizes and drawing spaces are tabulated by the standard rather than derived, so
this module transcribes tables rather than computing them. Each constant names
the clause it comes from; ``tests/test_drawing_iso.py`` checks them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "Sheet",
    "Box",
    "FrameStyle",
    "LineGroup",
    "LINE_GROUPS",
    "GROUP_0_7",
    "FILING_BORDER",
    "PLAIN_BORDER",
    "FRAME_WIDTH",
    "CENTRING_MARK_WIDTH",
    "CENTRING_MARK_OVERSHOOT",
    "GRID_LINE_WIDTH",
    "GRID_CHARACTER_SIZE",
    "GRID_FIELD_LENGTH",
    "GRID_BAND_WIDTH",
    "GRID_LETTERS",
    "TRIM_MARK_LONG",
    "TRIM_MARK_SHORT",
    "TITLE_BLOCK_WIDTH",
    "grid_divisions",
    "A4_PORTRAIT",
    "A3_LANDSCAPE",
    "A2_LANDSCAPE",
    "A1_LANDSCAPE",
    "A0_LANDSCAPE",
    "ISO_5457_CANDIDATES",
    "A4_LANDSCAPE",
    "A3_LANDSCAPE_PLAIN",
]

Box = tuple[float, float, float, float]  # x0, y0, x1, y1

# --- ISO 5457:1999 -------------------------------------------------------

#: 4.2. The left edge carries a filing margin and includes the frame.
FILING_BORDER: float = 20.0
#: 4.2. Every other edge.
PLAIN_BORDER: float = 10.0
#: 4.2. "executed with continuous lines of 0,7 mm width".
FRAME_WIDTH: float = 0.7

#: 4.3. Centring marks are drawn at the frame's own width and run from the grid
#: reference border past the frame, into the drawing space. The clause spends
#: 10 mm on that reach; this sheet spends 5, because at 10 the top mark is drawn
#: through the overall width dimension and the side marks reach the panel. The
#: whole mark is then the 10 mm the standard gave the reach alone.
CENTRING_MARK_WIDTH: float = 0.7
CENTRING_MARK_OVERSHOOT: float = 5.0

#: 4.4. Grid reference lines, character height, and the field length measured
#: from the axes of symmetry.
GRID_LINE_WIDTH: float = 0.35
GRID_CHARACTER_SIZE: float = 3.5
GRID_FIELD_LENGTH: float = 50.0
#: The depth of the band itself, taken from Figure 4 rather than the prose,
#: which gives the border widths but never the band's own. It sits against the
#: frame, so the rest of each border stays clear: 5 mm of margin outside it on
#: three edges and 15 mm on the filing edge.
GRID_BAND_WIDTH: float = 5.0
#: 4.4. "capital letters (I and O shall not be used)".
GRID_LETTERS: str = "ABCDEFGHJKLMNPQRSTUVWXYZ"

#: 4.5. Two overlapping rectangles of these dimensions, at all four edges.
TRIM_MARK_LONG: float = 10.0
TRIM_MARK_SHORT: float = 5.0

#: ISO 7200:2004 6. "The same title block is used for all paper sizes."
TITLE_BLOCK_WIDTH: float = 180.0


def grid_divisions(extent: float, count: int) -> tuple[float, ...]:
    """Split ``extent`` into ``count`` grid fields, per ISO 5457 4.4.

    Fields are ``GRID_FIELD_LENGTH`` measured outwards from the centre axis;
    whatever the division leaves over goes to the two fields at the corners, so
    an end field may be longer or shorter than the interior ones.
    """
    if count < 2:
        return (extent,)
    interior = count - 2
    end = (extent - interior * GRID_FIELD_LENGTH) / 2.0
    return (end, *(GRID_FIELD_LENGTH,) * interior, end)


class FrameStyle(Enum):
    """Which furniture a sheet carries."""

    #: One border rectangle. What the SVG sheet has always drawn.
    PLAIN = "plain"
    #: Border, frame, centring marks, grid reference system, trimming marks.
    ISO_5457 = "iso-5457"


@dataclass(frozen=True, slots=True)
class Sheet:
    """A sheet in millimetres, with its tabulated drawing space when it has one.

    ``space_width`` and ``space_height`` are ISO 5457 Table 1 values. A sheet
    without them is not a standard size and falls back to ``margin``.
    """

    name: str
    width: float
    height: float
    space_width: float | None = None
    space_height: float | None = None
    #: 4.4 Table 2, as (horizontal, vertical) field counts for this orientation.
    fields_across: int = 0
    fields_down: int = 0

    @property
    def margin(self) -> float:
        """The non-ISO fallback border, unchanged from the original SVG sheet."""
        return min(10.0, min(self.width, self.height) * 0.05)

    @property
    def is_landscape(self) -> bool:
        return self.width > self.height

    @property
    def grid_fields(self) -> tuple[int, int]:
        return (self.fields_across, self.fields_down)

    @property
    def space(self) -> Box:
        """The drawing space, as a sheet-millimetre box with Y running down."""
        if self.space_width is None or self.space_height is None:
            margin = self.margin
            return (margin, margin, self.width - margin, self.height - margin)
        # 4.2: the filing margin is on the left edge; the top border is plain.
        return (
            FILING_BORDER,
            PLAIN_BORDER,
            FILING_BORDER + self.space_width,
            PLAIN_BORDER + self.space_height,
        )


# 4.1 leaves one legal orientation per size: A4 vertical, A0 to A3 horizontal.
# Table 1 gives the trimmed size and the drawing space; Table 2 the field counts.
A4_PORTRAIT = Sheet("A4", 210.0, 297.0, 180.0, 277.0, fields_across=4, fields_down=6)
A3_LANDSCAPE = Sheet("A3", 420.0, 297.0, 390.0, 277.0, fields_across=8, fields_down=6)
A2_LANDSCAPE = Sheet("A2", 594.0, 420.0, 564.0, 400.0, fields_across=12, fields_down=8)
A1_LANDSCAPE = Sheet("A1", 841.0, 594.0, 811.0, 574.0, fields_across=16, fields_down=12)
A0_LANDSCAPE = Sheet("A0", 1189.0, 841.0, 1159.0, 821.0, fields_across=24, fields_down=16)

#: 3.1: "the smallest sheet permitting the necessary clarity", so ascending area.
ISO_5457_CANDIDATES: tuple[Sheet, ...] = (
    A4_PORTRAIT,
    A3_LANDSCAPE,
    A2_LANDSCAPE,
    A1_LANDSCAPE,
    A0_LANDSCAPE,
)

#: The SVG emitter's own sheets. Not ISO 5457 layouts and not in the ladder:
#: that emitter fits a scale to a fixed sheet rather than a sheet to 1:1.
A4_LANDSCAPE = Sheet("A4", 297.0, 210.0)
A3_LANDSCAPE_PLAIN = Sheet("A3", 420.0, 297.0)


# --- ISO 128-24:1999 -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineGroup:
    """A pair of widths in the 1:2 proportion clause 5 requires."""

    wide: float
    narrow: float


#: Table 2. A group is named by its *wide* width; 0,5 and 0,7 are the preferred
#: two. Naming matters: group 0,35 is 0.35/0.18, not 0.7/0.35.
LINE_GROUPS: dict[str, tuple[float, float]] = {
    "0.25": (0.25, 0.13),
    "0.35": (0.35, 0.18),
    "0.5": (0.5, 0.25),
    "0.7": (0.7, 0.35),
    "1": (1.0, 0.5),
    "1.4": (1.4, 0.7),
    "2": (2.0, 1.0),
}

#: What the PDF sheet draws with. ISO 5457 independently asks for a 0,7 frame
#: (4.2) and 0,35 grid lines (4.4), which is this row, so the drawing and the
#: sheet furniture are one system.
GROUP_0_7 = LineGroup(*LINE_GROUPS["0.7"])
