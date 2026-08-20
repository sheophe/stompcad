"""Serialise complete ``DrillData`` as versioned JSON for toolchain consumers.

Nominal ``*_nm`` values are integer nanometres; unsuffixed ``raw`` values remain
measured millimetres. Model order and identities are preserved, effective
processing and diagnostics are included, and model tuples become JSON lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import (
    DrillData,
    EnclosureMatch,
    Hole,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)

from .base import register_emitter

__all__ = ["JsonOptions", "JsonEmitter", "FORMAT", "VERSION"]

FORMAT = "stompcad-drill-data"
VERSION = 5


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
            "units": "nm",
            "origin": "centre",
            "source": _source(data.source),
            "reference": _reference(data.reference),
            "tools": [
                {
                    "number": number,
                    "diameter_nm": diameter_nm,
                    "count": counts[diameter_nm],
                }
                for diameter_nm, number in tools.items()
            ],
            "holes": [
                _hole(h, tools[h.diameter_nm], number) for number, h in data.numbered()
            ],
            "diagnostics": [_diagnostic(d) for d in data.diagnostics],
            "processing": [_stage_run(r) for r in data.processing],
            "enclosure": _enclosure(data.enclosure),
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
    """Emit nominal outline nanometres and the measured millimetre outline."""
    if reference is None:
        return None
    return {
        "width_nm": reference.width_nm,
        "height_nm": reference.height_nm,
        "centre_x_nm": reference.centre_x_nm,
        "centre_y_nm": reference.centre_y_nm,
        "raw": {"width": reference.raw.width, "height": reference.raw.height},
    }


def _hole(hole: Hole, tool: int, number: int) -> dict[str, Any]:
    """Emit one hole with the number the caller resolved, not its array position."""
    return {
        "x_nm": hole.x_nm,
        "y_nm": hole.y_nm,
        "diameter_nm": hole.diameter_nm,
        "tool": tool,
        "raw": {"x": hole.raw.x, "y": hole.raw.y, "diameter": hole.raw.diameter},
        "index": number,
    }


def _listed(value: Any) -> Any:
    """Convert a tuple to a list, recursively, leaving a scalar untouched.

    A location payload such as ``tied_locations`` nests a tuple of coordinate
    tuples, so one level of conversion is not enough to make it JSON-shaped.
    """
    if isinstance(value, tuple):
        return [_listed(element) for element in value]
    return value


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    """Emit a finding with always-present payload; convert tuple values to lists."""
    return {
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "location_nm": (
            None if diagnostic.location_nm is None else list(diagnostic.location_nm)
        ),
        "data": {key: _listed(value) for key, value in diagnostic.data},
    }


def _stage_run(run: StageRun) -> dict[str, Any]:
    """Emit effective stage parameters, converting tuple values to JSON lists."""
    return {
        "name": run.name,
        "parameters": {key: _listed(value) for key, value in run.parameters},
    }


def _enclosure(match: EnclosureMatch | None) -> dict[str, Any] | None:
    """Emit the match unchanged, preserving candidate and catalogue orientation.

    No match is ``null``; ``selected_part`` remains null unless declared.
    """
    if match is None:
        return None
    return {
        "family": match.family,
        "length_nm": match.length_nm,
        "width_nm": match.width_nm,
        "candidates": list(match.candidates),
        "rotated": match.rotated,
        "selected_part": match.selected_part,
    }
