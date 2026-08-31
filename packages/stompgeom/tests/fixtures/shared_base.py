"""A document whose solids draw on one base shape, built through OCP.

The structure ``build_document`` has to keep apart: one ``TopoDS_Shape``
placed several ways, plus an unplaced solid over the same base, which is
what a placement API invites -- two identical footswitches on one board.
Built rather than committed, for the same reason as ``repeated_colour``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SHARED_COLOUR", "shared_base_document"]

#: Not one of STEP's pre-defined colours -- see ``repeated_colour``'s note.
SHARED_COLOUR = (0.21, 0.43, 0.65)


def shared_base_document() -> Any:
    """Four solids over two base shapes: located, unlocated, coloured, not."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    from stompgeom.build import PlacedSolid, build_document
    from stompmodel.frames import RigidTransform

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    first = BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()
    second = BRepPrimAPI_MakeBox(5.0, 6.0, 7.0).Shape()
    return build_document([
        PlacedSolid(first, "A", SHARED_COLOUR, None),
        PlacedSolid(first, "B", None, RigidTransform(identity, (10.0, 0.0, 0.0))),
        PlacedSolid(first, "C", (0.75, 0.31, 0.12), RigidTransform(identity, (20.0, 0.0, 0.0))),
        PlacedSolid(second, "D", None, None),
    ])
