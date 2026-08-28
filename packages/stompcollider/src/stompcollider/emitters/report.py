"""Serialise ``DockData`` as the dock report -- ``stompcollider-dock-report`` v1.

Satisfies ``stompmodel.protocols.Emitter[DockData]``: ``ReportEmitter.emit``
returns bytes and never writes them (ADR-0005). Integer nanometres
throughout except ``theta_deg``, the one float in the document, which is
written to exactly six decimal places -- the standard library's JSON
encoder always uses ``repr`` for a float and cannot be told otherwise, so
this module marks a pre-formatted literal and unmarks it after ``json.dumps``
has run. See ``docs/specs/stompcollider-technical.md``'s "The report".
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import CaseRegistration

from ..model import Board, Clash, Correspondence, DockData, Placement

__all__ = ["ReportEmitter"]

FORMAT = "stompcollider-dock-report"
VERSION = 1
_UNITS = "nm"

_THETA_TAG = "stompcolliderthetaliteral"
_THETA_PATTERN = re.compile('"' + re.escape(_THETA_TAG) + r'([-0-9.]+)"')


def _theta_literal(theta_deg: float) -> str:
    """A pre-formatted six-decimal literal, wrapped so it survives ``json.dumps``.

    The standard encoder's float branch always calls ``float.__repr__``
    directly and cannot be overridden per value, so this returns an
    ordinary JSON string here; ``_THETA_PATTERN`` strips the wrapper and
    the quotes once encoding is done, turning it back into a bare number.
    ASCII letters and digits only -- a control or non-ASCII marker would
    itself be escaped by ``json.dumps`` and stop appearing literally in
    the encoded text.
    """
    return f"{_THETA_TAG}{theta_deg:.6f}"


class ReportEmitter:
    """Emit the whole run's answer: every placement found, and why."""

    name: ClassVar[str] = "report"
    media_type: ClassVar[str] = "application/json"
    extension: ClassVar[str] = ".json"

    def emit(self, data: DockData) -> bytes:
        text = json.dumps(_document(data), indent=2)
        text = _THETA_PATTERN.sub(r"\1", text)
        return (text + "\n").encode("utf-8")


def _document(data: DockData) -> dict[str, Any]:
    """The document itself, as a JSON-ready mapping: key order is part of it."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "units": _UNITS,
        "case": _case(data.case),
        "boards": [_board(board, data) for board in data.boards],
        # A set of leftover holes, not a ranked list: sorted regardless of
        # how the caller's tuple was ordered -- see ADR-0006.
        "unmatched_holes": sorted(data.unmatched_holes),
        "diagnostics": [_diagnostic(d) for d in data.diagnostics],
    }


def _case(case: CaseRegistration) -> dict[str, Any]:
    """Echo the case registration; ``face`` is read here, never chosen."""
    return {"part": case.part, "face": case.face.value, "model": case.model}


def _board(board: Board, data: DockData) -> dict[str, Any]:
    """One board's report entry, in the order the caller's boards arrived.

    ``board.ordinal`` is read from the board itself, never recomputed from
    this loop's position -- boards may be numbered out of tuple order.
    Placements are looked up by that ordinal, then sorted by rank.
    """
    placements = sorted(data.placements.get(board.ordinal, ()), key=lambda p: p.rank)
    return {
        "ordinal": board.ordinal,
        "designators": list(board.designators),
        "extent_nm": list(board.extent_nm),
        "panel_face": board.panel_face,
        "placements": [_placement(p) for p in placements],
    }


def _placement(placement: Placement) -> dict[str, Any]:
    return {
        "rank": placement.rank,
        "x_nm": placement.x_nm,
        "y_nm": placement.y_nm,
        "z_nm": placement.z_nm,
        "theta_deg": _theta_literal(placement.theta_deg),
        "correspondence": [_correspondence(c) for c in placement.correspondence],
        "clashes": [_clash(c) for c in placement.clashes],
    }


def _correspondence(correspondence: Correspondence) -> dict[str, Any]:
    """``insertion_nm`` is JSON ``null`` for a hole admitting the part fully.

    That is a stated geometric fact -- nothing bounds the depth -- not a
    missing measurement, so the key stays present rather than disappearing;
    a caller can tell "unbounded" from "the field was never written".
    """
    return {
        "designator": correspondence.designator,
        "hole_index": correspondence.hole_index,
        "hole_xy_nm": list(correspondence.hole_xy_nm),
        "insertion_nm": correspondence.insertion_nm,
        "offset_nm": correspondence.offset_nm,
    }


def _clash(clash: Clash) -> dict[str, Any]:
    return {
        "with": clash.with_,
        "kind": clash.kind,
        "bbox_nm": list(clash.bbox_nm),
        "depth_nm": clash.depth_nm,
        "axis": clash.axis,
        "volume_nm3": clash.volume_nm3,
    }


def _diagnostic(diagnostic: Diagnostic) -> dict[str, Any]:
    """Matched by ``code``, never by ``message`` -- see CLAUDE.md.

    ``location_nm`` is always present, ``null`` when the finding is
    panel-wide -- no ``stompcollider`` diagnostic sets one today, but the
    key must not silently drop the day one does, mirroring
    ``stompmodel.codec``'s unconditional emission of the same shared field.
    """
    return {
        "severity": diagnostic.severity.value,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "location_nm": (
            None if diagnostic.location_nm is None else list(diagnostic.location_nm)
        ),
        "data": {key: _listed(value) for key, value in diagnostic.data},
    }


def _listed(value: Any) -> Any:
    """Convert a tuple to a list, recursively, leaving a scalar untouched."""
    if isinstance(value, tuple):
        return [_listed(element) for element in value]
    return value
