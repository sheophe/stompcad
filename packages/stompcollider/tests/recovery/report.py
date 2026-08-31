"""Read a dock report back out of its JSON, with the standard library.

Every key the document states is modelled and an unrecognised one is
refused: a reader that skipped what it does not model would pass an emitter
change by omission. ``parse_float=Decimal`` keeps the one non-integer field
-- the angle -- exact, so a comparison can demand equality.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from stompmodel.units import Nanometre

from . import (
    RecoveredBoard,
    RecoveredClash,
    RecoveredCorrespondence,
    RecoveredDiagnostic,
    RecoveredDock,
    RecoveredPlacement,
)

__all__ = ["read_report"]

FORMAT = "stompcollider-dock-report"
VERSION = 1
UNITS = "nm"


def _fields(value: Any, expected: tuple[str, ...], what: str) -> Mapping[str, Any]:
    """``value`` as an object stating exactly ``expected``, and nothing else."""
    if not isinstance(value, dict):
        raise ValueError(f"{what} is not a JSON object: {value!r}")
    missing = sorted(set(expected) - set(value))
    unknown = sorted(set(value) - set(expected))
    if missing or unknown:
        raise ValueError(f"unhandled {what}: missing {missing}, unknown {unknown}")
    return value


def _length(value: Any, what: str) -> Nanometre:
    """A canonical length: a whole number of nanometres, never a float."""
    if type(value) is not int:
        raise ValueError(f"{what} is not a whole number of nanometres: {value!r}")
    return Nanometre(value)


def _lengths(value: Any, count: int, what: str) -> tuple[Nanometre, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{what} is not {count} lengths: {value!r}")
    return tuple(_length(element, what) for element in value)


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} is not a string: {value!r}")
    return value


def _count(value: Any, what: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{what} is not a whole number: {value!r}")
    return value


def read_report(text: str) -> RecoveredDock:
    """Everything one dock report states, refusing a document of another shape.

    The header is checked first: a reader that measured a document it did
    not recognise would report a plausible answer about the wrong thing.
    """
    document = _fields(
        json.loads(text, parse_float=Decimal),
        ("format", "version", "units", "case", "boards", "unmatched_holes", "diagnostics"),
        "dock report",
    )
    if (document["format"], document["version"], document["units"]) != (
        FORMAT, VERSION, UNITS,
    ):
        raise ValueError(
            f"not a {FORMAT} v{VERSION} document in {UNITS}: "
            f"{document['format']!r} v{document['version']!r} in {document['units']!r}"
        )
    case = _fields(document["case"], ("part", "face", "model"), "case")
    holes = document["unmatched_holes"]
    if not isinstance(holes, list):
        raise ValueError(f"unmatched_holes is not a list: {holes!r}")
    return RecoveredDock(
        format=FORMAT,
        version=VERSION,
        units=UNITS,
        case=(
            _text(case["part"], "case.part"),
            _text(case["face"], "case.face"),
            _text(case["model"], "case.model"),
        ),
        boards=tuple(_board(board) for board in document["boards"]),
        unmatched_holes=tuple(_count(hole, "unmatched hole") for hole in holes),
        diagnostics=tuple(_diagnostic(found) for found in document["diagnostics"]),
    )


def _board(value: Any) -> RecoveredBoard:
    board = _fields(
        value,
        ("ordinal", "designators", "extent_nm", "panel_face", "placements"),
        "board",
    )
    extent = _lengths(board["extent_nm"], 3, "board.extent_nm")
    face = board["panel_face"]
    return RecoveredBoard(
        ordinal=_count(board["ordinal"], "board.ordinal"),
        designators=tuple(
            _text(name, "board.designators") for name in board["designators"]
        ),
        extent_nm=(extent[0], extent[1], extent[2]),
        panel_face=None if face is None else _text(face, "board.panel_face"),
        placements=tuple(_placement(one) for one in board["placements"]),
    )


def _placement(value: Any) -> RecoveredPlacement:
    placement = _fields(
        value,
        ("rank", "x_nm", "y_nm", "z_nm", "theta_deg", "correspondence", "clashes"),
        "placement",
    )
    theta = placement["theta_deg"]
    if not isinstance(theta, Decimal):
        raise ValueError(f"placement.theta_deg is not a decimal angle: {theta!r}")
    return RecoveredPlacement(
        rank=_count(placement["rank"], "placement.rank"),
        x_nm=_length(placement["x_nm"], "placement.x_nm"),
        y_nm=_length(placement["y_nm"], "placement.y_nm"),
        z_nm=_length(placement["z_nm"], "placement.z_nm"),
        theta_deg=theta,
        correspondence=tuple(_correspondence(one) for one in placement["correspondence"]),
        clashes=tuple(_clash(one) for one in placement["clashes"]),
    )


def _correspondence(value: Any) -> RecoveredCorrespondence:
    paired = _fields(
        value,
        ("designator", "hole_index", "hole_xy_nm", "insertion_nm", "offset_nm"),
        "correspondence",
    )
    centre = _lengths(paired["hole_xy_nm"], 2, "correspondence.hole_xy_nm")
    insertion = paired["insertion_nm"]
    return RecoveredCorrespondence(
        designator=_text(paired["designator"], "correspondence.designator"),
        hole_index=_count(paired["hole_index"], "correspondence.hole_index"),
        hole_xy_nm=(centre[0], centre[1]),
        insertion_nm=(
            None if insertion is None else _length(insertion, "correspondence.insertion_nm")
        ),
        offset_nm=_length(paired["offset_nm"], "correspondence.offset_nm"),
    )


def _clash(value: Any) -> RecoveredClash:
    clash = _fields(
        value, ("with", "kind", "bbox_nm", "depth_nm", "axis", "volume_nm3"), "clash"
    )
    box = _lengths(clash["bbox_nm"], 6, "clash.bbox_nm")
    return RecoveredClash(
        with_=_text(clash["with"], "clash.with"),
        kind=_text(clash["kind"], "clash.kind"),
        bbox_nm=(box[0], box[1], box[2], box[3], box[4], box[5]),
        depth_nm=_length(clash["depth_nm"], "clash.depth_nm"),
        axis=_text(clash["axis"], "clash.axis"),
        volume_nm3=_count(clash["volume_nm3"], "clash.volume_nm3"),
    )


def _diagnostic(value: Any) -> RecoveredDiagnostic:
    """``location_nm`` is read as a stated ``null``, never as an absent key.

    The document emits it unconditionally, so a missing one is a change to
    the report's shape rather than a finding with no position.
    """
    found = _fields(
        value, ("severity", "code", "message", "location_nm", "data"), "diagnostic"
    )
    location = found["location_nm"]
    if location is not None and not isinstance(location, list):
        raise ValueError(f"diagnostic.location_nm is not a position: {location!r}")
    return RecoveredDiagnostic(
        severity=_text(found["severity"], "diagnostic.severity"),
        code=_text(found["code"], "diagnostic.code"),
        location_nm=(
            None
            if location is None
            else _lengths(location, len(location), "diagnostic.location_nm")
        ),
    )
