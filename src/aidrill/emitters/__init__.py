"""Output formats and their public registry API.

Importing this package loads each emitter module so its registration decorator
populates ``REGISTRY``.
"""

from . import drawing_pdf, drawing_svg, excellon, json_out  # noqa: F401  (imported for the side effect)
from .base import REGISTRY, available, get_emitter, register_emitter
from .drawing_pdf import DrawingPdfEmitter, PdfDrawingOptions
from .drawing_svg import DrawingOptions, DrawingSvgEmitter
from .excellon import ExcellonEmitter, ExcellonOptions
from .json_out import JsonEmitter, JsonOptions

__all__ = [
    "REGISTRY",
    "available",
    "get_emitter",
    "register_emitter",
    "DrawingOptions",
    "DrawingSvgEmitter",
    "DrawingPdfEmitter",
    "PdfDrawingOptions",
    "ExcellonEmitter",
    "ExcellonOptions",
    "JsonEmitter",
    "JsonOptions",
]
