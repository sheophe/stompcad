"""Backend-neutral sheet layout shared by the drawing emitters.

The package resolves ``DrillData`` into a ``Scene`` of primitives in sheet
millimetres; a backend only serialises that scene. Both drawing emitters read
the same layout so two sheets of one panel cannot state it differently.
"""

from __future__ import annotations

from .scene import FEINT, INK, RED, Circle, Item, Line, Polygon, Rect, Scene, Stroke, Text

__all__ = [
    "Scene",
    "Item",
    "Stroke",
    "Line",
    "Circle",
    "Rect",
    "Polygon",
    "Text",
    "INK",
    "RED",
    "FEINT",
]
