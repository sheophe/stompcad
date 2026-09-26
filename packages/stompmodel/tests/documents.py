"""One hand-built document, shared by the codec's tests and the byte lock.

Hand-built rather than read from artwork: the lock has to compare two
codec versions over identical input, and a reader's own output would drag
a panel fixture and a kernel into a comparison about key order.
"""

from __future__ import annotations

from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import (
    CaseFace,
    CaseRegistration,
    DrillData,
    EnclosureMatch,
    Hole,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from stompmodel.units import Nanometre

__all__ = ["panel_frame", "sample_data"]


def panel_frame() -> FaceFrame:
    """A frame whose ``w`` is +Z and whose origin is 2 mm below the plate."""
    return FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-2_000_000)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )


def sample_data() -> DrillData:
    """Two holes on the drilled plate, with every optional section filled."""
    return DrillData(
        holes=(
            Hole.from_measurement(
                Nanometre(-19_000_000), Nanometre(-18_750_000), Nanometre(5_000_000)
            ).with_number(1),
            Hole.from_measurement(
                Nanometre(19_000_000), Nanometre(-18_750_000), Nanometre(7_000_000)
            ).with_number(2),
        ),
        reference=ReferenceOutline(Nanometre(112_400_000), Nanometre(60_500_000)),
        source=SourceInfo(path="panel.ai", drill_layer="Drill", producer="stompdrill"),
        processing=(StageRun("snap", (("grid_nm", 500_000),)),),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(112_400_000),
            width_nm=Nanometre(60_500_000),
            candidates=("1590B",),
            selected_part="1590B",
        ),
        case=CaseRegistration("1590B", CaseFace.BOX, "1590B.stp", panel_frame()),
    )
