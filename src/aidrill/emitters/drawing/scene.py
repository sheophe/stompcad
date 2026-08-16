"""Primitives a drawing backend serialises, in sheet millimetres, Y down.

The model-to-sheet transform has already happened, so these coordinates are
page coordinates and are described from the top, as a page is. A backend whose
own frame runs the other way flips once at serialisation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the checker
    from .sheet import Sheet

__all__ = [
    "INK",
    "RED",
    "FEINT",
    "Stroke",
    "Line",
    "Circle",
    "Rect",
    "Polygon",
    "Text",
    "Item",
    "Scene",
]

#: Sheet colours. Kept as hex so the SVG backend writes them unchanged; the PDF
#: backend converts to its own operator form.
INK = "#111111"
RED = "#c00000"
FEINT = "#8a8a8a"


@dataclass(frozen=True, slots=True)
class Stroke:
    """A pen: width in sheet millimetres, colour, and an optional dash pattern."""

    width: float
    colour: str
    dashes: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Line:
    """A straight segment between two sheet points."""

    x1: float
    y1: float
    x2: float
    y2: float
    stroke: Stroke
    cls: str = ""


@dataclass(frozen=True, slots=True)
class Circle:
    """An unfilled circle. A backend without one draws four cubic Béziers."""

    cx: float
    cy: float
    r: float
    stroke: Stroke
    cls: str = ""


@dataclass(frozen=True, slots=True)
class Rect:
    """An unfilled rectangle, optionally with rounded corners."""

    x: float
    y: float
    width: float
    height: float
    stroke: Stroke
    radius: float = 0.0
    cls: str = ""


@dataclass(frozen=True, slots=True)
class Polygon:
    """A filled polygon. Arrowheads and trimming marks are the only users."""

    points: tuple[tuple[float, float], ...]
    fill: str
    cls: str = ""


@dataclass(frozen=True, slots=True)
class Text:
    """A run of text at a size, with the anchor and rotation the layout chose."""

    x: float
    y: float
    content: str
    size: float
    anchor: str = "start"
    weight: str = "normal"
    rotate: float = 0.0
    colour: str = INK
    cls: str = ""


Item = Union[Line, Circle, Rect, Polygon, Text]


@dataclass(frozen=True, slots=True)
class Scene:
    """A resolved sheet and everything drawn on it, in draw order."""

    sheet: Sheet
    items: tuple[Item, ...] = ()

    def with_items(self, items: tuple[Item, ...]) -> Scene:
        return replace(self, items=items)
