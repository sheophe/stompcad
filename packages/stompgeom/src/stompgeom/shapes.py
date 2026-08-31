"""Making one shape out of others: bundling, locating, intersecting.

The topological side of geometry, as distinct from the format side that
reads and writes STEP. Every operation here is describable without naming a
panel or a board, which is ADR-0008's admission test.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from stompmodel.frames import RigidTransform

from .errors import StompgeomError
from .kernel import require_kernel

__all__ = ["compound", "placed", "common", "volume_mm3"]


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


def common(first: Any, second: Any) -> Any | None:
    """The region ``first`` and ``second`` share, or ``None`` when they share none.

    An exact boolean, never a bounding-box estimate. ``None`` rather than the
    empty compound the kernel hands back: that shape carries no topology at
    all, so a caller reading a bounding box off it gets an exception instead
    of a fact. Two bodies in contact -- meeting on a face, or a shaft exactly
    filling its bore -- share no region and arrive here as ``None``.
    """
    require_kernel()
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    operation = BRepAlgoAPI_Common(first, second)
    if not operation.IsDone():
        raise StompgeomError("the shared region of two shapes could not be evaluated")
    region = operation.Shape()
    # Emptiness asked topologically rather than by bounding box: every
    # non-empty result has at least one vertex, whatever its dimension, and
    # a void ``Bnd_Box`` cannot be read without raising.
    if region.IsNull() or not TopExp_Explorer(region, TopAbs_ShapeEnum.TopAbs_VERTEX).More():
        return None
    return region


def volume_mm3(shape: Any) -> float:
    """How much material ``shape`` holds, in cubic millimetres.

    Read off the exact geometry by Gauss integration over its faces, never
    off a triangulation: a quantity read from a mesh is a function of the
    deflection it was built at rather than of the input. A region with no
    thickness -- two bodies meeting on a face -- holds nothing and measures
    zero, which is the same answer :func:`common` gives by handing back
    ``None`` before a caller ever gets here.
    """
    require_kernel()
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return float(properties.Mass())
