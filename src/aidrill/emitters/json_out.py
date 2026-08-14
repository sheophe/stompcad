"""JSON emitter (SPEC §7) — the integration surface for the wider toolchain.

Everything in ``DrillData`` comes out: nominal positions *and* the raw measured
values behind them, the reference outline, the tool table, every diagnostic, and
where the data came from. A consumer can rebuild an identical ``DrillData`` from
this document, which is what ``test_json_emitter.py`` asserts.

Document shape (version 1)::

    {
      "format": "aidrill-drill-data",
      "version": 1,
      "units": "mm",                     # always; canonical frame, never inches
      "origin": "centre",                # centre of the reference outline, Y up
      "source":     {"path", "drill_layer", "reference_layer",
                     "layers_found", "producer"},
      "reference":  {"width", "height", "centre_x", "centre_y"} | null,
      "tools":     [{"number", "diameter", "count"}, …],   # ascending diameter
      "holes":     [{"x", "y", "diameter", "tool",
                     "raw": {"x", "y", "diameter"}}, …],   # pipeline order
      "diagnostics": [{"severity", "code", "message", "location"}, …]
    }

Key order is fixed and part of the contract, so diffing two runs shows real
changes rather than dictionary reshuffling. ``location`` is ``[x, y]`` in
canonical millimetres or ``null``.

Like every emitter, this one only serialises: hole order is whatever the pipeline
left behind, values are passed through unrounded, and both the tool numbers and
the per-tool quantities come from the model — :meth:`DrillData.tools` and
:meth:`DrillData.tool_counts` — so this document, the drawing's schedule and the
CLI report cannot disagree about how many holes a bit drills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from ..model import Diagnostic, DrillData, Hole, ReferenceOutline, SourceInfo
from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter", "FORMAT", "VERSION"]

FORMAT = "aidrill-drill-data"
VERSION = 1


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

    # -- public ----------------------------------------------------------
    def emit(self, data: DrillData) -> str:
        return json.dumps(self.document(data), indent=self.options.indent) + "\n"

    def document(self, data: DrillData) -> dict[str, Any]:
        """The JSON-ready mapping, exposed so callers can embed it elsewhere."""
        tools = data.tools()
        counts = data.tool_counts()

        return {
            "format": FORMAT,
            "version": VERSION,
            "units": "mm",
            "origin": "centre",
            "source": _source(data.source),
            "reference": _reference(data.reference),
            "tools": [
                {"number": number, "diameter": diameter, "count": counts[diameter]}
                for diameter, number in tools.items()
            ],
            "holes": [_hole(h, tools[h.diameter]) for h in data.holes],
            "diagnostics": [_diagnostic(d) for d in data.diagnostics],
        }


def _source(source: SourceInfo) -> dict[str, Any]:
    return {
        "path": source.path,
        "drill_layer": source.drill_layer,
        "reference_layer": source.reference_layer,
        "layers_found": list(source.layers_found),
        "producer": source.producer,
    }


def _reference(reference: ReferenceOutline | None) -> dict[str, Any] | None:
    if reference is None:
        return None
    return {
        "width": reference.width,
        "height": reference.height,
        "centre_x": reference.centre_x,
        "centre_y": reference.centre_y,
    }


def _hole(hole: Hole, tool: int) -> dict[str, Any]:
    return {
        "x": hole.x,
        "y": hole.y,
        "diameter": hole.diameter,
        "tool": tool,
        "raw": {"x": hole.raw.x, "y": hole.raw.y, "diameter": hole.raw.diameter},
    }


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    return {
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "location": None if diagnostic.location is None else list(diagnostic.location),
    }
