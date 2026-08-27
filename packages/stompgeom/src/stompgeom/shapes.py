"""Assembling kernel shapes into one shape.

The topological side of geometry, as distinct from the format side that
reads and writes STEP. See ADR-0008.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from stompmodel.frames import RigidTransform

from .kernel import require_kernel

__all__ = ["compound", "placed"]


def compound(shapes: Iterable[Any]) -> Any:
    """Bundle ``shapes`` into one ``TopoDS_Compound``, in the order given.

    An empty iterable yields an empty compound rather than raising: a level
    with no faces is a legitimate value, and refusing it here would push the
    same check into every caller.
    """
    require_kernel()
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    built = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(built)
    for shape in shapes:
        builder.Add(built, shape)
    return built


def placed(shape: Any, motion: RigidTransform) -> Any:
    """A located copy of ``shape`` under ``motion``.

    A ``TopLoc_Location`` rather than a rebuilt transform: locating
    rebuilds no geometry, so the writer still sees the original topology
    and the names and colours attached to it survive the placement.
    """
    require_kernel()
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    rows = motion.rotation
    trsf.SetValues(
        rows[0][0], rows[0][1], rows[0][2], motion.translation_mm[0],
        rows[1][0], rows[1][1], rows[1][2], motion.translation_mm[1],
        rows[2][0], rows[2][1], rows[2][2], motion.translation_mm[2],
    )
    return shape.Moved(TopLoc_Location(trsf))
