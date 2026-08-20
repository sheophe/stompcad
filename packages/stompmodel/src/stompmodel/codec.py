"""The versioned drill document, written and read.

Nominal ``*_nm`` values are integer nanometres; unsuffixed ``raw`` values
remain measured millimetres. Model order and identities are preserved, and
model tuples become JSON lists. Both directions live together because more
than one package exchanges this file, and a second parser written elsewhere
is how two of them come to disagree about it. See ADR-0009.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .diagnostics import Diagnostic, Severity
from .errors import EmitterError
from .model import (
    DrillData,
    EnclosureMatch,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from .units import Millimetre, Nanometre

__all__ = ["FORMAT", "VERSION", "to_document", "from_document"]

FORMAT = "stompcad-drill-data"
VERSION = 5


def to_document(data: DrillData) -> dict[str, Any]:
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


def from_document(document: Mapping[str, Any]) -> DrillData:
    """Rebuild ``DrillData`` from a document ``to_document`` produced.

    Mirrors the writers above one for one. A document whose ``format`` is not
    this one, or whose ``version`` is unknown, is refused rather than parsed
    on a guess: a reader that silently accepts a shape it does not know is
    how two packages come to disagree about the same file.
    """
    if document.get("format") != FORMAT:
        raise EmitterError(f"not a {FORMAT} document: {document.get('format')!r}")
    if document.get("version") != VERSION:
        raise EmitterError(f"{FORMAT} version {document.get('version')!r}, expected {VERSION}")
    return DrillData(
        holes=tuple(_read_hole(h) for h in document["holes"]),
        reference=_read_reference(document["reference"]),
        diagnostics=tuple(_read_diagnostic(d) for d in document["diagnostics"]),
        source=_read_source(document["source"]),
        processing=tuple(_read_stage_run(r) for r in document["processing"]),
        enclosure=_read_enclosure(document["enclosure"]),
    )


def _read_source(payload: Mapping[str, Any]) -> SourceInfo:
    return SourceInfo(
        path=payload["path"],
        drill_layer=payload["drill_layer"],
        reference_layer=payload["reference_layer"],
        layers_found=tuple(payload["layers_found"]),
        producer=payload["producer"],
    )


def _read_reference(payload: Mapping[str, Any] | None) -> ReferenceOutline | None:
    """Restore both the nominal outline and the measurement it was snapped from."""
    if payload is None:
        return None
    return ReferenceOutline(
        width_nm=Nanometre(payload["width_nm"]),
        height_nm=Nanometre(payload["height_nm"]),
        centre_x_nm=Nanometre(payload["centre_x_nm"]),
        centre_y_nm=Nanometre(payload["centre_y_nm"]),
        raw=RawOutline(
            Millimetre(payload["raw"]["width"]), Millimetre(payload["raw"]["height"])
        ),
    )


def _read_hole(payload: Mapping[str, Any]) -> Hole:
    """Restore one hole with the number it was written with.

    ``tool`` is not read: ``DrillData.tools()`` derives it from the diameters,
    and a stored copy could contradict them.
    """
    hole = Hole(
        x_nm=Nanometre(payload["x_nm"]),
        y_nm=Nanometre(payload["y_nm"]),
        diameter_nm=Nanometre(payload["diameter_nm"]),
        raw=RawHole(
            Millimetre(payload["raw"]["x"]),
            Millimetre(payload["raw"]["y"]),
            Millimetre(payload["raw"]["diameter"]),
        ),
    )
    return hole.with_number(payload["index"])


def _read_diagnostic(payload: Mapping[str, Any]) -> Diagnostic:
    """Restore a finding; ``Diagnostic`` re-tuples what ``_listed`` flattened."""
    location = payload["location_nm"]
    return Diagnostic(
        severity=Severity(payload["severity"]),
        code=payload["code"],
        message=payload["message"],
        location_nm=(
            None if location is None else (Nanometre(location[0]), Nanometre(location[1]))
        ),
        data=tuple(payload["data"].items()),
    )


def _read_stage_run(payload: Mapping[str, Any]) -> StageRun:
    """Restore a stage record; ``StageRun`` re-tuples what ``_listed`` flattened."""
    return StageRun(payload["name"], tuple(payload["parameters"].items()))


def _read_enclosure(payload: Mapping[str, Any] | None) -> EnclosureMatch | None:
    """Restore the match as written, candidates and catalogue orientation intact."""
    if payload is None:
        return None
    return EnclosureMatch(
        family=payload["family"],
        length_nm=Nanometre(payload["length_nm"]),
        width_nm=Nanometre(payload["width_nm"]),
        candidates=tuple(payload["candidates"]),
        rotated=payload["rotated"],
        selected_part=payload["selected_part"],
    )
