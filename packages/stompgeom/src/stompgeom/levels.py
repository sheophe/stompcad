"""Grouping a solid's planar faces into the planes they lie in.

A partition, not a search: every planar face belongs to exactly one level,
keyed on the face's own outward direction and offset. See ADR-0008.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from stompmodel.frames import dot
from stompmodel.units import Nanometre, check_nanometres, nm_from_mm

from .kernel import require_kernel
from .step import StepSolid

__all__ = ["Direction", "Level", "levels"]

#: A unit vector in kernel coordinates.
Direction = tuple[float, float, float]

#: Components in a direction.
_COMPONENTS = 3

#: Direction components are keyed as integer millionths -- a bin, not a
#: merge tolerance: two components land in one bin or they do not, however
#: narrowly they straddle the boundary between two. Chosen from a measured
#: gap, not rounded to taste: the largest real coplanar deviation across
#: every available fixture is 3.846e-08, and the tolerance the axis filter
#: below inherits is ~4.5e-5 radians. A millionth sits 26x above the noise
#: and 45x below the tolerance -- near that three-order gap's geometric
#: midpoint. A billionth was measured and rejected: it splits one real side
#: wall in two. tests/test_levels.py holds both probes.
_DIRECTION_SCALE = 1e6

#: How far a direction's length may sit from one at construction. The same
#: figure ``stompmodel.frames`` checks a basis vector's length against and
#: ``cylinders`` an axis direction's: it refuses a malformed hand-built value
#: rather than absorbing kernel drift, and it is not either tolerance below.
_UNIT_TOLERANCE = 1e-9

#: How nearly a plane's normal must lie along a caller's axis to be kept.
#: Inherited unchanged from ``stompdrill``'s ``cad/case.py``, where it has
#: always governed this decision; it is not a second expression of the
#: constant above and does not track it.
_PARALLEL_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class Level:
    """Every coplanar planar face of one solid sharing one outward facing.

    ``offset_nm`` is signed **along** ``direction``, so two opposed levels'
    offsets sum to the material between them. A single physical plane can
    tessellate into disconnected patches, which is why this is a set.
    """

    direction: Direction
    offset_nm: Nanometre
    area_mm2: float
    faces: tuple[Any, ...]

    def __post_init__(self) -> None:
        """Refuse a level that states no plane, at construction.

        A unit direction, a whole-nanometre offset along it, a real positive
        area and at least one face: a level with none of the last is not a
        plane this solid has. ``_partition`` satisfies all four by
        construction; a hand-built fixture is where a malformed one enters.
        """
        if len(self.direction) != _COMPONENTS:
            raise ValueError(
                f"Level.direction must have exactly three components, "
                f"not {len(self.direction)}"
            )
        if not all(math.isfinite(component) for component in self.direction):
            raise ValueError(f"Level.direction must be finite, not {self.direction!r}")
        length = math.sqrt(dot(self.direction, self.direction))
        if abs(length - 1.0) > _UNIT_TOLERANCE:
            raise ValueError(
                f"Level.direction must be unit length, not {self.direction!r} "
                f"(length {length!r})"
            )
        check_nanometres("Level", offset_nm=self.offset_nm)
        if not math.isfinite(self.area_mm2) or self.area_mm2 <= 0.0:
            raise ValueError(
                f"Level.area_mm2 must be a positive number of square millimetres, "
                f"not {self.area_mm2!r}"
            )
        if not self.faces:
            raise ValueError("Level.faces must hold at least one face")


def levels(solid: StepSolid, axis: Direction | None = None) -> tuple[Level, ...]:
    """Group ``solid``'s planar faces into the planes they lie in.

    Ordered on direction then offset, so a consumer may rely on the order.
    ``axis`` is an optional **unsigned** filter: given one, levels facing
    either way along it are kept and the rest dropped, by the parallelism
    test ``stompdrill`` has always applied.
    """
    require_kernel()
    found = _partition(solid.shape)
    if axis is None:
        return found
    return tuple(
        level for level in found
        if abs(abs(dot(level.direction, axis)) - 1.0) < _PARALLEL_TOLERANCE
    )


def _partition(shape: Any, scale: float = _DIRECTION_SCALE) -> tuple[Level, ...]:
    """Every planar face of ``shape``, grouped by outward direction and offset.

    The *level* order is a function of the geometry: the sort key is the key
    the groups were built on, so it is total. That claim stops at the level.
    Within one, ``faces`` is the explorer's own order and ``area_mm2`` a
    float sum accumulated in it, so a rule reading either owes ADR-0006 its
    own answer. ``scale`` is a parameter only so the granularity's guilty
    probe can drive the rejected value; production callers take the default.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    groups: dict[tuple[tuple[int, int, int], int], list[tuple[float, Any]]] = defaultdict(list)
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            plane = adaptor.Plane()
            normal, location = plane.Axis().Direction(), plane.Location()
            outward = [normal.X(), normal.Y(), normal.Z()]
            if face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
                outward = [-component for component in outward]
            offset = (
                location.X() * outward[0]
                + location.Y() * outward[1]
                + location.Z() * outward[2]
            )
            key = (
                (
                    round(outward[0] * scale),
                    round(outward[1] * scale),
                    round(outward[2] * scale),
                ),
                int(nm_from_mm(offset)),
            )
            properties = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, properties)
            groups[key].append((properties.Mass(), face))
        explorer.Next()
    return tuple(
        sorted(
            (
                Level(
                    direction=_unit(components, scale),
                    offset_nm=Nanometre(offset_nm),
                    area_mm2=sum(area for area, _face in members),
                    faces=tuple(face for _area, face in members),
                )
                for (components, offset_nm), members in groups.items()
            ),
            key=lambda level: (level.direction, level.offset_nm),
        )
    )


def _unit(components: tuple[int, int, int], scale: float) -> Direction:
    """The quantised key as a unit vector.

    Re-normalised rather than handed back as it rounds, so that every member
    of a level shares one bit-identical direction and a consumer's own
    unit-length check has margin.
    """
    raw = [component / scale for component in components]
    length = math.sqrt(sum(component * component for component in raw))
    return (raw[0] / length, raw[1] / length, raw[2] / length)

