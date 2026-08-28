"""Every cylindrical face of a shape, with the half a radius alone cannot state.

An axis has a direction and a face has an axial trim; a consumer building a
radius-versus-depth profile needs both. Parallelism and coaxiality are the
kernel's own declarations -- ``Precision::Angular()`` for a direction,
``Precision::Confusion()`` for a position -- never a tolerance chosen here.
See ADR-0008.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from stompmodel.units import check_millimetres

from .kernel import require_kernel
from .levels import Direction

__all__ = ["Cylinder", "cylindrical_faces"]

#: How far a direction's length may sit from one. A ``gp_Dir`` is normalised
#: by the kernel, so this refuses a malformed hand-built value rather than
#: absorbing kernel drift; it is the same figure ``stompmodel.frames`` checks
#: a basis vector's length against and ``levels()`` its parallelism, and it is
#: not the tolerance either rule below applies.
_UNIT_TOLERANCE = 1e-9

#: Components in a position or a direction, and bounds in an axial extent.
_VECTOR_COMPONENTS = 3
_EXTENT_BOUNDS = 2


@dataclass(frozen=True, slots=True)
class Cylinder:
    """One cylindrical face: where its axis runs, how wide, and how far along.

    ``extent_mm`` is ``(low, high)``, signed along ``axis_direction`` from
    ``axis_location_mm`` -- the face's own axial trim, so the two end circles
    sit at ``axis_location_mm + extent_mm[i] * axis_direction``. Millimetre
    floats: this is a measurement, not a canonical length (ADR-0004).
    """

    axis_location_mm: tuple[float, float, float]
    axis_direction: Direction
    radius_mm: float
    extent_mm: tuple[float, float]

    def __post_init__(self) -> None:
        for name, vector, width in (
            ("axis_location_mm", self.axis_location_mm, _VECTOR_COMPONENTS),
            ("axis_direction", self.axis_direction, _VECTOR_COMPONENTS),
            ("extent_mm", self.extent_mm, _EXTENT_BOUNDS),
        ):
            if len(vector) != width:
                raise ValueError(
                    f"Cylinder.{name} must have exactly "
                    f"{'three' if width == _VECTOR_COMPONENTS else 'two'} components, "
                    f"not {len(vector)}"
                )
        check_millimetres(
            "Cylinder",
            radius_mm=self.radius_mm,
            **{f"axis_location_mm[{i}]": v for i, v in enumerate(self.axis_location_mm)},
            **{f"axis_direction[{i}]": v for i, v in enumerate(self.axis_direction)},
            **{f"extent_mm[{i}]": v for i, v in enumerate(self.extent_mm)},
        )
        if self.radius_mm <= 0.0:
            raise ValueError(f"Cylinder.radius_mm must be positive, not {self.radius_mm!r}")
        if self.extent_mm[0] > self.extent_mm[1]:
            raise ValueError(
                f"Cylinder.extent_mm runs low to high along the axis, not {self.extent_mm!r}"
            )
        length = math.sqrt(sum(c * c for c in self.axis_direction))
        if abs(length - 1.0) > _UNIT_TOLERANCE:
            raise ValueError(
                f"Cylinder.axis_direction must be unit length, not "
                f"{self.axis_direction!r} (length {length!r})"
            )

    def is_parallel_to(self, direction: Direction) -> bool:
        """Whether this axis lies along ``direction``, either way round.

        ``gp_Dir.IsParallel`` at ``Precision::Angular()``: the kernel's own
        declaration of when two directions are the same one. It is
        sign-agnostic, and must stay so -- which way a cylindrical surface's
        axis points is a convention of the exporter, not a fact about the part.
        """
        require_kernel()
        from OCP.gp import gp_Dir
        from OCP.Precision import Precision

        return gp_Dir(*self.axis_direction).IsParallel(
            gp_Dir(*direction), Precision.Angular_s()
        )

    def is_coaxial_with(self, other: Cylinder) -> bool:
        """Whether ``other``'s axis is this one's line.

        Parallelism above, then ``Precision::Confusion()`` on the axis
        position, measured by the kernel's own point-to-line distance.
        ``gp_Ax1.IsCoaxial`` is not used: it tests directions for equality
        rather than parallelism, so it refuses a coaxial face whose surface
        points the other way along the same line.
        """
        require_kernel()
        from OCP.gp import gp_Ax1, gp_Dir, gp_Lin, gp_Pnt
        from OCP.Precision import Precision

        if not self.is_parallel_to(other.axis_direction):
            return False
        line = gp_Lin(gp_Ax1(gp_Pnt(*self.axis_location_mm), gp_Dir(*self.axis_direction)))
        return bool(line.Distance(gp_Pnt(*other.axis_location_mm)) <= Precision.Confusion_s())


def cylindrical_faces(shape: Any) -> tuple[Cylinder, ...]:
    """Every cylindrical face of ``shape``, in ``shape``'s own coordinates.

    Faces are reported one per face, never merged: one surface tessellated
    into patches is still that surface, and merging here would decide for a
    consumer what counts as one feature. The order is the walk's, which no
    rule may consult (ADR-0006) -- a consumer choosing among these keys on
    the geometry instead.
    """
    require_kernel()
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    found: list[Cylinder] = []
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        # A bare TopoDS_Shape has no surface; downcast before adapting one.
        surface = BRepAdaptor_Surface(TopoDS.Face_s(explorer.Current()))
        if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis()
            location, direction = axis.Location(), axis.Direction()
            found.append(
                Cylinder(
                    axis_location_mm=(location.X(), location.Y(), location.Z()),
                    axis_direction=(direction.X(), direction.Y(), direction.Z()),
                    radius_mm=cylinder.Radius(),
                    # V parametrises a cylinder along its own axis, so the
                    # face's V bounds are its axial trim directly.
                    extent_mm=(surface.FirstVParameter(), surface.LastVParameter()),
                )
            )
        explorer.Next()
    return tuple(found)
