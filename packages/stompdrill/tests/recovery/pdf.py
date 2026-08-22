"""Read a drawing sheet back out of its PDF, independently of the writer.

The PDF backend owns three transforms nothing else in the project reaches: a
frame flip, a points matrix, and a circle built from four cubic Beziers. A
radius therefore cannot be read from a field, which is why this recovery is
load-bearing rather than a smoke check. Constants here come from the format,
never from ``drawing_pdf``.
"""

from __future__ import annotations

import io
import math
from decimal import Decimal
from typing import Any

from pdfminer.high_level import extract_pages

from stompmodel.units import Nanometre

from .facts import NM_PER_MM, RecoveredCircle, RecoveredPanel

__all__ = ["circle_from_path", "read_pdf"]

#: PDF user space is 1/72 inch and an inch is exactly 25.4 millimetres.
_PT_PER_MM = Decimal(72) / Decimal("25.4")

#: ``_num`` states four decimals of a millimetre, so every coordinate in the
#: stream is a whole multiple of this. Rounding to it recovers the stated
#: value exactly and leaves no epsilon in the comparison.
_QUANTUM_NM = 100

#: Four cubic segments closed by ``h``: the only circle PDF has.
_CIRCLE = "mcccch"

#: A rectangle with four corner arcs. The panel outline, and nothing else.
_ROUNDED_RECT = "mlclclclch"

#: Endpoint radii may disagree by float noise (measured: 1.14e-13 pt) and by
#: nothing else. Well under the stated quantum, well over the noise.
_ROUND_ENOUGH_PT = 1e-6


def circle_from_path(path: list[Any]) -> tuple[float, float, float]:
    """Centre and radius in points, from four cubic segments.

    The signature alone does not prove a circle: the four on-curve endpoints
    must be equidistant from their own centroid. Refusing rather than
    skipping keeps an emitter change from passing by omission.
    """
    ends = [segment[-1] for segment in path[1:5]]
    cx = sum(x for x, _ in ends) / 4.0
    cy = sum(y for _, y in ends) / 4.0
    radii = [math.hypot(x - cx, y - cy) for x, y in ends]
    if max(radii) - min(radii) > _ROUND_ENOUGH_PT:
        raise ValueError(f"not a circle: endpoint radii disagree by {max(radii) - min(radii)}")
    return cx, cy, sum(radii) / 4.0


def _nm(points: float) -> int:
    """Page points to nanometres, at the precision the stream states."""
    nanometres = float(Decimal(1) / _PT_PER_MM) * points * NM_PER_MM
    return round(nanometres / _QUANTUM_NM) * _QUANTUM_NM


def read_pdf(payload: bytes) -> RecoveredPanel:
    """Every circle the page draws, and the panel outline's extent.

    Reported in the sheet's own frame -- millimetres, Y down -- so undoing
    the emitter's Y-up flip is part of what this checks.
    """
    page = next(iter(extract_pages(io.BytesIO(payload), laparams=None)))
    height_nm = _nm(page.bbox[3])

    circles: list[RecoveredCircle] = []
    outline: tuple[Nanometre, Nanometre] | None = None
    for obj in page:
        path = getattr(obj, "original_path", None)
        if not path:
            continue
        signature = "".join(segment[0] for segment in path)
        if signature == _CIRCLE:
            cx, cy, radius = circle_from_path(path)
            circles.append(
                RecoveredCircle(
                    x_nm=Nanometre(_nm(cx)),
                    y_nm=Nanometre(height_nm - _nm(cy)),
                    diameter_nm=Nanometre(_nm(2 * radius)),
                )
            )
        elif signature == _ROUNDED_RECT and outline is None:
            x0, y0, x1, y1 = obj.bbox
            outline = (Nanometre(_nm(x1 - x0)), Nanometre(_nm(y1 - y0)))
    return RecoveredPanel(circles=tuple(circles), outline_nm=outline)
