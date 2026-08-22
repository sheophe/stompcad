"""Render ``DrillData`` as a printable ISO engineering drawing at 1:1.

The sheet is the free variable: the scale is fixed and the smallest ISO 5457
candidate that holds the panel is chosen. Content-stream coordinates, line
widths and font sizes are all millimetres, under one scale-only CTM, so a width
in the stream is the width ISO 128-24 names.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import ClassVar

import pikepdf

from stompmodel.model import DrillData

from .base import register_emitter
from .drawing.build import SheetText, build_scene
from .drawing.layout import Layout, choose_sheet
from .drawing.scene import Circle, Group, Item, Line, Polygon, Rect, Scene, Stroke, Text
from .drawing.sheet import ISO_5457_CANDIDATES, FrameStyle, Sheet

__all__ = [
    "PdfDrawingOptions",
    "SheetText",
    "Scene",
    "DrawingPdfEmitter",
    "encode_text",
    "PT_PER_MM",
    "WINANSI_SUBSTITUTIONS",
]

#: PDF user space is 1/72 inch and an inch is exactly 25.4 millimetres.
PT_PER_MM: float = 72.0 / 25.4

#: ⌀ (U+2300) has no WinAnsi code point. Ø (U+00D8) does, is visually the
#: diameter sign, and is what most title blocks print. Anything else that will
#: not encode becomes ``?``: a visible substitution beats a byte the viewer
#: resolves to some other glyph.
WINANSI_SUBSTITUTIONS: dict[str, str] = {"⌀": "Ø"}

#: The four cubic Bézier control points of a circle, as a fraction of radius.
#: The same constant the source uses to *recognise* a circle.
_KAPPA: float = 0.5522847498

#: Only the base-14 faces, so nothing is embedded and no /Widths is needed.
_REGULAR = "F1"
_BOLD = "F2"


def encode_text(text: str) -> bytes:
    """Encode one run for a WinAnsi literal string, escaping what PDF reserves."""
    substituted = "".join(WINANSI_SUBSTITUTIONS.get(ch, ch) for ch in text)
    raw = b"".join(_encode_char(ch) for ch in substituted)
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _encode_char(ch: str) -> bytes:
    try:
        return ch.encode("cp1252")
    except UnicodeEncodeError:
        return b"?"


@dataclass(frozen=True, slots=True)
class PdfDrawingOptions:
    """Presentation values for the PDF sheet."""

    text: SheetText = SheetText()
    candidates: tuple[Sheet, ...] = ISO_5457_CANDIDATES
    frame: FrameStyle = FrameStyle.ISO_5457


@register_emitter
class DrawingPdfEmitter:
    """Emit a one-page ISO drawing sheet, drawn 1:1."""

    name: ClassVar[str] = "drawing-pdf"
    media_type: ClassVar[str] = "application/pdf"
    extension: ClassVar[str] = ".pdf"

    def __init__(self, options: PdfDrawingOptions | None = None) -> None:
        self.options = options if options is not None else PdfDrawingOptions()

    def emit(self, data: DrillData) -> bytes:
        scene = build_scene(self.layout(data), data, self.options.text)
        return self.render(scene, self._title(data))

    def render(self, scene: Scene, title: str) -> bytes:
        """Serialise a resolved scene. The seam a two-backend comparison needs.

        The SVG side carries the same method for the same reason; keeping the
        pair symmetrical is what lets one test drive both over one scene.
        """
        return _serialise(scene, title)

    def layout(self, data: DrillData) -> Layout:
        """Choose the smallest candidate that holds ``data`` at 1:1."""
        return choose_sheet(data, self.options.candidates, frame=self.options.frame)

    def _title(self, data: DrillData) -> str:
        return self.options.text.title or data.source.path or "DRILL DRAWING"


# --- serialisation --------------------------------------------------------


def _num(value: float) -> str:
    """Four decimals of a millimetre is well below what any plotter resolves."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _scale_num(value: float) -> str:
    """Format the CTM's own scale factor, not a millimetre length on the page.

    Every coordinate, width and font size in the stream is stated in the
    millimetres ``_num`` truncates to; the two entries in the leading ``cm``
    are the conversion factor itself, applied to all of them, so a coarser
    rounding here would nudge every mark on the sheet by the same fraction.
    """
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text or "0"


def _rgb(colour: str) -> tuple[float, float, float]:
    """``#rrggbb`` to the three operands PDF's colour operators take."""
    value = colour.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b)


def _serialise(scene: Scene, title: str) -> bytes:
    """Write the scene as a one-page PDF, byte-reproducibly."""
    sheet = scene.sheet
    body = [f"{_scale_num(PT_PER_MM)} 0 0 {_scale_num(PT_PER_MM)} 0 0 cm"]
    for item in scene.items:
        body.extend(_ops_for(item, sheet))
    content = ("\n".join(body) + "\n").encode("latin-1")

    pdf = pikepdf.new()
    fonts = pikepdf.Dictionary(
        {
            "/" + _REGULAR: _font(pdf, "Helvetica"),
            "/" + _BOLD: _font(pdf, "Helvetica-Bold"),
        }
    )
    pdf.pages.append(
        pikepdf.Page(
            pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name.Page,
                    MediaBox=[0, 0, sheet.width * PT_PER_MM, sheet.height * PT_PER_MM],
                    Resources=pikepdf.Dictionary(Font=fonts),
                    Contents=pdf.make_stream(content),
                )
            )
        )
    )
    pdf.docinfo["/Title"] = title
    pdf.docinfo["/Creator"] = "stompdrill"
    out = io.BytesIO()
    # deterministic_id and no XMP: open_metadata() stamps xmp:ModifyDate, which
    # cascades into the trailer /ID and makes two runs disagree.
    pdf.save(
        out,
        deterministic_id=True,
        compress_streams=False,
        min_version="1.7",
        force_version="1.7",
    )
    return out.getvalue()


def _font(pdf: pikepdf.Pdf, base: str) -> pikepdf.Object:
    return pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/" + base),
            Encoding=pikepdf.Name.WinAnsiEncoding,
        )
    )


# --- per-primitive operators ------------------------------------------------


def _y(sheet: Sheet, value: float) -> float:
    """Sheet millimetres, Y down, into PDF millimetres, Y up."""
    return sheet.height - value


def _ops_for(item: Item, sheet: Sheet) -> list[str]:
    if isinstance(item, Line):
        return [
            *_pen(item.stroke),
            (
                f"{_num(item.x1)} {_num(_y(sheet, item.y1))} m\n"
                f"{_num(item.x2)} {_num(_y(sheet, item.y2))} l S"
            ),
            "[] 0 d",
        ]
    if isinstance(item, Circle):
        return [*_pen(item.stroke), _circle_path(item, sheet), "[] 0 d"]
    if isinstance(item, Rect):
        return [*_pen(item.stroke), *_rect_path(item, sheet), "[] 0 d"]
    if isinstance(item, Polygon):
        return _polygon_ops(item, sheet)
    if isinstance(item, Group):
        # PDF has no grouping construct that matters here: the nesting is a
        # content decision (see ``scene.Group``), so a scene group is read by
        # flattening its children's operators into the surrounding stream.
        ops: list[str] = []
        for child in item.items:
            ops.extend(_ops_for(child, sheet))
        return ops
    return _text_ops(item, sheet)


def _pen(stroke: Stroke) -> list[str]:
    red, green, blue = _rgb(stroke.colour)
    dashes = " ".join(_num(d) for d in stroke.dashes)
    return [
        f"{_num(stroke.width)} w {_num(red)} {_num(green)} {_num(blue)} RG",
        f"[{dashes}] 0 d",
    ]


def _circle_path(circle: Circle, sheet: Sheet) -> str:
    """Four cubic Béziers, which is the only circle PDF has.

    A ``fill`` of ``"none"`` strokes only. Anything else — a balloon masking
    the leader beneath it — sets the non-stroking colour and paints with ``B``,
    which fills and strokes in one operation without covering its own outline.
    """
    cx, cy, r = circle.cx, _y(sheet, circle.cy), circle.r
    k = _KAPPA * r
    path = (
        f"{_num(cx + r)} {_num(cy)} m\n"
        f"{_num(cx + r)} {_num(cy + k)} {_num(cx + k)} {_num(cy + r)} {_num(cx)} {_num(cy + r)} c "
        f"{_num(cx - k)} {_num(cy + r)} {_num(cx - r)} {_num(cy + k)} {_num(cx - r)} {_num(cy)} c "
        f"{_num(cx - r)} {_num(cy - k)} {_num(cx - k)} {_num(cy - r)} {_num(cx)} {_num(cy - r)} c "
        f"{_num(cx + k)} {_num(cy - r)} {_num(cx + r)} {_num(cy - k)} {_num(cx + r)} {_num(cy)} c h"
    )
    if circle.fill == "none":
        return f"{path} S"
    red, green, blue = _rgb(circle.fill)
    return f"{_num(red)} {_num(green)} {_num(blue)} rg {path} B"


def _rect_path(rect: Rect, sheet: Sheet) -> list[str]:
    """A plain rectangle uses ``re``; a rounded one needs four corner arcs.

    ``Rect`` carries no ``fill`` field — every rectangle the sheet draws is
    stroke-only furniture — so this always ends in a plain stroke, unlike
    ``_circle_path``.
    """
    bottom = _y(sheet, rect.y + rect.height)
    if rect.radius <= 0:
        return [f"{_num(rect.x)} {_num(bottom)} {_num(rect.width)} {_num(rect.height)} re S"]
    r = min(rect.radius, rect.width / 2.0, rect.height / 2.0)
    k = _KAPPA * r
    x0, y0 = rect.x, bottom
    x1, y1 = rect.x + rect.width, bottom + rect.height
    return [
        (
            f"{_num(x0 + r)} {_num(y0)} m\n"
            f"{_num(x1 - r)} {_num(y0)} l "
            f"{_num(x1 - r + k)} {_num(y0)} {_num(x1)} {_num(y0 + r - k)} {_num(x1)} {_num(y0 + r)} c "
            f"{_num(x1)} {_num(y1 - r)} l "
            f"{_num(x1)} {_num(y1 - r + k)} {_num(x1 - r + k)} {_num(y1)} {_num(x1 - r)} {_num(y1)} c "
            f"{_num(x0 + r)} {_num(y1)} l "
            f"{_num(x0 + r - k)} {_num(y1)} {_num(x0)} {_num(y1 - r + k)} {_num(x0)} {_num(y1 - r)} c "
            f"{_num(x0)} {_num(y0 + r)} l "
            f"{_num(x0)} {_num(y0 + r - k)} {_num(x0 + r - k)} {_num(y0)} {_num(x0 + r)} {_num(y0)} c "
            "h S"
        )
    ]


def _polygon_ops(polygon: Polygon, sheet: Sheet) -> list[str]:
    # Arrowheads and trimming marks are the only polygons a scene holds, and
    # both are built from a fixed tuple of corners, so the unpacking below has
    # a first point to take.
    red, green, blue = _rgb(polygon.fill)
    (first_x, first_y), *rest = polygon.points
    path = [f"{_num(first_x)} {_num(_y(sheet, first_y))} m"]
    path += [f"{_num(x)} {_num(_y(sheet, y))} l" for x, y in rest]
    return [f"{_num(red)} {_num(green)} {_num(blue)} rg", " ".join(path) + " h f"]


def _text_ops(text: Text, sheet: Sheet) -> list[str]:
    """Place one run, anchoring it by the same estimate the layout fitted with."""
    from .drawing.content import CHAR_RATIO

    width = CHAR_RATIO * text.size * len(text.content)
    offset = {"middle": -width / 2.0, "end": -width}.get(text.anchor, 0.0)
    font = _BOLD if text.weight == "bold" else _REGULAR
    red, green, blue = _rgb(text.colour)
    x, y = text.x, _y(sheet, text.y)
    literal = encode_text(text.content).decode("latin-1")

    if text.rotate:
        # ``text.rotate`` is defined in the scene's Y-down frame — the same
        # sense SVG's own ``rotate()`` reads it in. PDF text space is Y-up,
        # and mirroring one axis reverses a rotation's sense, so the angle
        # is negated here: without it, a label advances the opposite
        # physical direction from the one the SVG backend draws it in.
        angle = math.radians(-text.rotate)
        cos, sin = math.cos(angle), math.sin(angle)
        # Rotate about the anchor point, then step along the rotated baseline.
        place = (
            f"{_num(cos)} {_num(sin)} {_num(-sin)} {_num(cos)} "
            f"{_num(x + offset * cos)} {_num(y + offset * sin)} Tm"
        )
    else:
        place = f"{_num(x + offset)} {_num(y)} Td"
    return [
        f"{_num(red)} {_num(green)} {_num(blue)} rg",
        f"BT /{font} {_num(text.size)} Tf {place} ({literal}) Tj ET",
    ]
