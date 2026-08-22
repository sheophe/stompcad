"""Read a drawing sheet back out of its SVG, with the standard library.

Plain elements in millimetre user units at 1:1, and the only ``transform``
anywhere is ``rotate`` on text -- nothing nests a coordinate system, so no
CTM composition is needed. Values arrive at six decimals of a millimetre,
which is one nanometre, so a ``Decimal`` parse is exact.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from .facts import RecoveredCircle, RecoveredPanel, nm_from_decimal

__all__ = ["read_svg"]

_NS = "{http://www.w3.org/2000/svg}"


def read_svg(text: str) -> RecoveredPanel:
    """Every circle the sheet draws, and the panel outline's extent.

    The input is a document this suite emitted moments earlier, from a writer
    that produces no DOCTYPE and no entities: no untrusted input, so no
    ``defusedxml``.
    """
    root = ET.fromstring(text)
    circles = tuple(
        RecoveredCircle(
            x_nm=nm_from_decimal(element.attrib["cx"]),
            y_nm=nm_from_decimal(element.attrib["cy"]),
            diameter_nm=nm_from_decimal(Decimal(element.attrib["r"]) * 2),
            cls=element.get("class", ""),
        )
        for element in root.iter(f"{_NS}circle")
    )
    outline = next(
        (
            (nm_from_decimal(r.attrib["width"]), nm_from_decimal(r.attrib["height"]))
            for r in root.iter(f"{_NS}rect")
            if "outline" in (r.get("class") or "").split()
        ),
        None,
    )
    return RecoveredPanel(circles=circles, outline_nm=outline)
