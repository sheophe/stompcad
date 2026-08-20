"""Register stompmodel's drill document as an emitter format.

The document and its codec live in stompmodel, because stompcollider reads
the same file and cannot import stompdrill. What is left here is the
registry entry and the one option that is genuinely presentation:
``indent``. See ADR-0009.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

from stompmodel.codec import to_document
from stompmodel.model import DrillData

from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter"]


@dataclass(frozen=True, slots=True)
class JsonOptions:
    """``indent`` is passed straight to :func:`json.dumps`; ``None`` is compact."""

    indent: int | None = 2


@register_emitter
class JsonEmitter:
    """Emit the whole of ``DrillData`` as JSON."""

    name: ClassVar[str] = "json"
    media_type: ClassVar[str] = "application/json"
    extension: ClassVar[str] = ".json"

    def __init__(self, options: JsonOptions | None = None) -> None:
        self.options = options if options is not None else JsonOptions()

    def emit(self, data: DrillData) -> str:
        return json.dumps(to_document(data), indent=self.options.indent) + "\n"
