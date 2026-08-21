"""Write a resolved drawing scene as a standalone SVG engineering drawing.

What the sheet shows is decided in ``drawing.build``; this module only turns
each primitive into the SVG element that carries it, in millimetre user units.
Sheet colours and pens arrive on the primitives, so nothing here decides how
wide a line is or what it means.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import ClassVar

from stompmodel.model import DrillData

from .base import register_emitter
from .drawing.build import SheetText, build_scene
from .drawing.layout import Layout
from .drawing.scene import INK, Circle, Group, Item, Line, Polygon, Rect, Scene, Stroke, Text
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

A4_PORTRAIT = Sheet("A4", 210.0, 297.0)


@dataclass(frozen=True, slots=True)
class DrawingOptions:
    """Options specific to the drawing emitter."""

    sheet: Sheet = A4_LANDSCAPE
    scale: float | None = None
    text: SheetText = SheetText()


def _fmt(value: float | str) -> str:
    if isinstance(value, str):
        return value
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
        scene = build_scene(self.layout(data), data, self.options.text)
        return self.render(scene, self._sheet_title(data))

    def render(self, scene: Scene, title: str) -> str:
        """Serialise a resolved scene. The seam a two-backend comparison needs.

        ``emit`` fuses layout, build and serialise; only here is one scene
        drawn by one backend, which is the only way a divergence localises to
        a serialiser rather than to a layout.
        """
        # The namespace is declared as a plain attribute rather than through
        # ElementTree's ``default_namespace``: that option rejects unqualified
        # attribute names, and every SVG attribute here is unqualified.
        root = ET.Element(
            "svg",
            {
                "xmlns": SVG_NS,
                "width": f"{_fmt(scene.sheet.width)}mm",
                "height": f"{_fmt(scene.sheet.height)}mm",
                "viewBox": f"0 0 {_fmt(scene.sheet.width)} {_fmt(scene.sheet.height)}",
                "version": "1.1",
            },
        )
        _sub(root, "title").text = title
        _sub(root, "style", type="text/css").text = _STYLESHEET

        for item in scene.items:
            _render_item(root, item)

        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"

    def layout(self, data: DrillData) -> Layout:
        """Compute the sheet layout for ``data``. Pure; no drawing happens."""
        return Layout.for_sheet(self.options.sheet, data, scale=self.options.scale)

    def _sheet_title(self, data: DrillData) -> str:
        return self.options.text.title or data.source.path or "DRILL DRAWING"


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

_STYLESHEET = (
    "svg{background:#ffffff}"
    "text{font-family:'DejaVu Sans','Helvetica Neue',Helvetica,Arial,sans-serif;"
    "fill:" + INK + "}"
)


def _render_item(parent: ET.Element, item: Item) -> None:
    """Write one primitive as the SVG element that carries it."""
    if isinstance(item, Group):
        group = _sub(parent, "g", **({"class": item.cls} if item.cls else {}))
        for child in item.items:
            _render_item(group, child)
    elif isinstance(item, Line):
        _stroked(parent, "line", item.stroke, item.cls, x1=item.x1, y1=item.y1, x2=item.x2, y2=item.y2)
    elif isinstance(item, Circle):
        _stroked(parent, "circle", item.stroke, item.cls, cx=item.cx, cy=item.cy, r=item.r, fill=item.fill)
    elif isinstance(item, Rect):
        # A zero radius produces no rx, which is what a plain rectangle is.
        _stroked(
            parent,
            "rect",
            item.stroke,
            item.cls,
            x=item.x,
            y=item.y,
            width=item.width,
            height=item.height,
            rx=item.radius or None,
            ry=item.radius or None,
            fill="none",
        )
    elif isinstance(item, Polygon):
        points = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in item.points)
        _sub(
            parent,
            "polygon",
            **({"class": item.cls} if item.cls else {}),
            points=points,
            fill=item.fill,
            stroke="none",
        )
    else:
        _text_element(parent, item)


def _stroked(parent: ET.Element, tag: str, stroke: Stroke, cls: str, **attrs) -> None:
    """Write a stroked shape, folding the pen into presentation attributes."""
    ordered: dict[str, object] = {"class": cls} if cls else {}
    ordered.update(attrs)
    ordered["stroke"] = stroke.colour
    ordered["stroke_width"] = stroke.width
    if stroke.dashes:
        ordered["stroke_dasharray"] = " ".join(_fmt(d) for d in stroke.dashes)
    _sub(parent, tag, **ordered)


def _text_element(parent: ET.Element, item: Text) -> ET.Element:
    attrs: dict[str, object] = {"x": item.x, "y": item.y, "font-size": item.size}
    if item.anchor != "start":
        attrs["text-anchor"] = item.anchor
    if item.weight != "normal":
        attrs["font-weight"] = item.weight
    if item.rotate:
        attrs["transform"] = f"rotate({_fmt(item.rotate)} {_fmt(item.x)} {_fmt(item.y)})"
    if item.colour != INK:
        # Inline style beats the stylesheet; a fill= attribute does not.
        attrs["style"] = f"fill:{item.colour}"
    if item.cls:
        attrs["class"] = item.cls
    element = _sub(parent, "text", **attrs)
    element.text = item.content
    return element


def _sub(parent: ET.Element, tag: str, **attrs) -> ET.Element:
    element = ET.SubElement(parent, tag)
    for key, value in attrs.items():
        if value is None:
            continue
        element.set(key.replace("_", "-"), _fmt(value))
    return element
