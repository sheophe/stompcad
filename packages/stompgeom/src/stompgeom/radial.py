"""How far a solid reaches along an axis, and how far outside a radius about it.

The question a through-panel part asks: not "which cylinders is it made of"
but "where does material too wide for this hole begin". Answered by an exact
boolean against a cylinder of that radius, never by triangulating the solid
-- a mesh varies with its deflection parameters and with the kernel's own
version, and two runs over one input must agree byte for byte (ADR-0006).
Millimetre floats: these are measurements (ADR-0004). See ADR-0008.
"""

from __future__ import annotations

from typing import Any

from stompmodel.units import check_millimetres

from .errors import StompgeomError
from .kernel import require_kernel
from .levels import Direction

__all__ = ["axial_extent", "radial_bands", "radial_reach"]

#: How far past each end of the solid the cutting cylinder is built. A tool
#: that only has to contain the solid has no other natural size, and the
#: value is fixed here rather than passed in so that one solid measured
#: twice is measured the same way.
_MARGIN_MM = 1.0


def _turned(direction: Direction) -> Any:
    """A location turning ``direction`` onto ``+Z``, so a box reads along it.

    A ``TopLoc_Location`` rather than a rebuilt shape: locating rebuilds no
    geometry, so the measurement is of the solid itself. An axis-aligned
    box in the turned frame is the extent along ``direction``; boxing in the
    model frame and projecting the corners is a different, larger quantity.
    """
    require_kernel()
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    origin = gp_Pnt(0.0, 0.0, 0.0)
    transformation = gp_Trsf()
    transformation.SetTransformation(
        gp_Ax3(origin, gp_Dir(*direction)), gp_Ax3(origin, gp_Dir(0.0, 0.0, 1.0))
    )
    return TopLoc_Location(transformation)


def _box(shape: Any, location: Any) -> Any:
    """``shape``'s bounding box in the turned frame, from geometry alone.

    ``useTriangulation`` is false on purpose: a box read off a mesh is a box
    read off whichever deflection that mesh was built at.
    """
    require_kernel()
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape.Moved(location), box, False)
    if box.IsVoid():
        raise StompgeomError("a shape with no bounding box cannot be measured")
    return box


def axial_extent(shape: Any, direction: Direction) -> tuple[float, float]:
    """How far ``shape`` reaches along ``direction``, least first."""
    check_millimetres(
        "axial_extent", **{f"direction[{i}]": v for i, v in enumerate(direction)}
    )
    box = _box(shape, _turned(direction))
    return (box.CornerMin().Z(), box.CornerMax().Z())


def radial_reach(
    shape: Any,
    axis_location_mm: tuple[float, float, float],
    direction: Direction,
    radius_mm: float,
) -> float | None:
    """Where material further than ``radius_mm`` from the axis reaches, along ``direction``.

    The greatest coordinate along ``direction`` of any part of ``shape``
    lying **strictly** outside a cylinder of ``radius_mm`` about the axis
    through ``axis_location_mm``; ``None`` when none of it does. Strictness
    is the kernel's: material exactly on the cylinder is coincident with it
    and the cut removes it, so a shaft exactly filling its bore reaches
    nothing -- see "Fit clearance" in ``stompcollider-technical.md``.
    """
    found = _residue("radial_reach", shape, axis_location_mm, direction, radius_mm)
    if found is None:
        return None
    return _box(*found).CornerMax().Z()


def radial_bands(
    shape: Any,
    axis_location_mm: tuple[float, float, float],
    direction: Direction,
    radius_mm: float,
) -> tuple[tuple[float, float], ...]:
    """Where material outside ``radius_mm`` lies along ``direction``, least first.

    One ``(low, high)`` per separate piece of it, because a part may be too
    wide in two places with nothing between them and a single pair spanning
    both would claim material the gap does not hold. Ordered on the pairs
    themselves, so the kernel's walk reaches no answer (ADR-0006). Empty
    where nothing lies outside the cylinder; strictness is as
    :func:`radial_reach` states it.
    """
    found = _residue("radial_bands", shape, axis_location_mm, direction, radius_mm)
    return () if found is None else _pieces(*found)


def _residue(
    caller: str,
    shape: Any,
    axis_location_mm: tuple[float, float, float],
    direction: Direction,
    radius_mm: float,
) -> tuple[Any, Any] | None:
    """What of ``shape`` lies outside the cylinder, with the frame it reads in.

    One cut serving both public questions, and each reads it its own way: a
    box over the whole residue answers the reach, and a box per solid answers
    the bands. ``None`` where nothing lies outside the cylinder.
    """
    require_kernel()
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    check_millimetres(
        caller,
        radius_mm=radius_mm,
        **{f"axis_location_mm[{i}]": v for i, v in enumerate(axis_location_mm)},
        **{f"direction[{i}]": v for i, v in enumerate(direction)},
    )
    if radius_mm < 0.0:
        raise ValueError(f"{caller} needs a radius, not {radius_mm!r}")

    location = _turned(direction)
    box = _box(shape, location)
    low, high = box.CornerMin().Z(), box.CornerMax().Z()
    # The box bounds the radial extent too, so a radius no material can
    # reach is answered without a boolean at all. An upper bound, so the
    # short-circuit only ever skips a cut whose answer is already known.
    axis = gp_Pnt(*axis_location_mm).Transformed(location.Transformation())
    corners = (
        (box.CornerMin().X(), box.CornerMin().Y()),
        (box.CornerMin().X(), box.CornerMax().Y()),
        (box.CornerMax().X(), box.CornerMin().Y()),
        (box.CornerMax().X(), box.CornerMax().Y()),
    )
    bound = max(
        ((x - axis.X()) ** 2 + (y - axis.Y()) ** 2) ** 0.5 for x, y in corners
    )
    if radius_mm >= bound:
        return None

    # The turned frame's Z *is* the coordinate along ``direction``, so the
    # axis point's own Z is where the tool must start counting from.
    step = gp_Dir(*direction)
    offset = (low - _MARGIN_MM) - axis.Z()
    base = gp_Pnt(
        axis_location_mm[0] + step.X() * offset,
        axis_location_mm[1] + step.Y() * offset,
        axis_location_mm[2] + step.Z() * offset,
    )
    tool = BRepPrimAPI_MakeCylinder(
        gp_Ax2(base, step), radius_mm, (high - low) + 2.0 * _MARGIN_MM
    ).Shape()

    operation = BRepAlgoAPI_Cut(shape, tool)
    if not operation.IsDone():
        raise StompgeomError("the material outside a radius could not be evaluated")
    residue = operation.Shape()
    # Emptiness asked topologically, as ``shapes.common`` asks it: every
    # non-empty result carries a vertex, and a void box cannot be read.
    if residue.IsNull() or not TopExp_Explorer(
        residue, TopAbs_ShapeEnum.TopAbs_VERTEX
    ).More():
        return None
    return (residue, location)


def _pieces(residue: Any, location: Any) -> tuple[tuple[float, float], ...]:
    """Each solid of ``residue`` as its extent along the turned frame's own Z.

    A cut of one solid by another yields solids; a residue carrying none is
    boxed whole rather than reported as nothing, because material was found
    and a shell or a face is still where it is.
    """
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    found = []
    explorer = TopExp_Explorer(residue, TopAbs_ShapeEnum.TopAbs_SOLID)
    while explorer.More():
        box = _box(explorer.Current(), location)
        found.append((box.CornerMin().Z(), box.CornerMax().Z()))
        explorer.Next()
    if not found:
        whole = _box(residue, location)
        found.append((whole.CornerMin().Z(), whole.CornerMax().Z()))
    return tuple(sorted(found))
