"""Output formats.

Importing this package imports every emitter module, which is what runs the
``@register_emitter`` decorators and fills ``REGISTRY``. ``cli.py`` therefore
resolves ``--emit FORMAT=PATH`` purely through :func:`get_emitter` and never
names a concrete class: adding a format means adding a module and one line here,
and nothing else in the codebase changes (OCP).
"""

from . import drawing_svg, excellon, json_out  # noqa: F401  (imported for the side effect)
from .base import REGISTRY, available, get_emitter, register_emitter
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
    "ExcellonEmitter",
    "ExcellonOptions",
    "JsonEmitter",
    "JsonOptions",
]
