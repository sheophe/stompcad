"""A component's protrusion: which cylinders count, and the stack they make.

Kernel-backed, but only through ``stompgeom``: the parallelism and
coaxiality rules are the kernel's own tolerances, published as ``Cylinder``
methods, and nothing here imports OCP. Measurements only -- millimetre
floats upstream of ``canonicalise``, which is the one place they become
canonical lengths. See "Protrusions" in
``docs/specs/stompcollider-technical.md``, ADR-0003 and ADR-0008.
"""

from __future__ import annotations

from stompgeom.cylinders import Cylinder, cylindrical_faces
from stompgeom.levels import Direction
from stompgeom.step import StepSolid

from .boards import basis_about, dot
from .raw import RawComponent, RawCylinder

__all__ = ["admissible", "protrusion_of", "reach_along"]


def admissible(solid: StepSolid, carrier_normal: Direction) -> tuple[Cylinder, ...]:
    """``solid``'s cylindrical faces whose axis lies along ``carrier_normal``.

    A cylinder at any other angle cannot pass through a hole in a flat panel,
    so admitting one risks an axis that means nothing. Parallelism is
    sign-agnostic; only :func:`protrusion_of` reads the direction's sign.
    """
    return tuple(
        cylinder
        for cylinder in cylindrical_faces(solid.shape)
        if cylinder.is_parallel_to(carrier_normal)
    )


def protrusion_of(solid: StepSolid, carrier_normal: Direction) -> RawComponent | None:
    """``solid``'s measured protrusion, or ``None`` when it has no axis.

    ``carrier_normal`` is signed: it points away from the board, at the
    panel, and the admitted cylinder reaching furthest along it fixes the
    axis. Every cylinder coaxial with that one joins the stack, each
    measured as a radius against depth from the tip -- never a diameter.
    A component yielding no admissible cylinder has no axis and cannot pair.
    """
    admitted = admissible(solid, carrier_normal)
    if not admitted:
        return None
    u, v = basis_about(carrier_normal)
    tipmost = max(admitted, key=lambda c: _tip_key(c, carrier_normal, u, v))
    tip_mm = reach_along(tipmost, carrier_normal)[1]
    return RawComponent(
        designator=solid.name,
        axis_xy_mm=(_projected(tipmost, u), _projected(tipmost, v)),
        # Every coaxial face, stated as measured. Deduplicating a seam's two
        # halves and ordering the stack are both ``canonicalise``'s, where
        # the values are whole nanometres: exact equality is a fact about
        # those and not about a millimetre float, and a set keyed on one
        # would be the composite float key ADR-0003's boundary rules out.
        stack=tuple(
            _measured(cylinder, carrier_normal, tip_mm)
            for cylinder in admitted
            if tipmost.is_coaxial_with(cylinder)
        ),
    )


def _measured(cylinder: Cylinder, outward: Direction, tip_mm: float) -> RawCylinder:
    """One cylinder as a radius and the depths from the tip it spans.

    Depth grows away from the tip, so a cylinder's far end along ``outward``
    is its shallow bound.
    """
    low_mm, high_mm = reach_along(cylinder, outward)
    return RawCylinder(
        radius_mm=cylinder.radius_mm,
        depth_from_tip_min_mm=tip_mm - high_mm,
        depth_from_tip_max_mm=tip_mm - low_mm,
    )


def reach_along(cylinder: Cylinder, outward: Direction) -> tuple[float, float]:
    """Where the cylinder's two end circles sit along ``outward``, least first.

    Public because a caller must be able to ask how far a cylinder reaches
    *before* it knows which way is outward: ``sources/step.py`` derives that
    sign from this measurement, and a second copy of it there would be a
    second chance to disagree about where a face ends.
    """
    base = dot(cylinder.axis_location_mm, outward)
    step = dot(cylinder.axis_direction, outward)
    ends = (base + cylinder.extent_mm[0] * step, base + cylinder.extent_mm[1] * step)
    return (min(ends), max(ends))


def _tip_key(
    cylinder: Cylinder, outward: Direction, u: Direction, v: Direction
) -> tuple[float, float, float, float, float]:
    """How far the cylinder reaches, and how to break a tie without the walk.

    Reach decides it. Two cylinders reaching exactly as far are separated on
    the wider one, then its near end, then where its axis sits in the carrier
    plane -- all geometry, so two spellings of one part agree (ADR-0006).
    """
    low, high = reach_along(cylinder, outward)
    return (high, cylinder.radius_mm, low, dot(cylinder.axis_location_mm, u),
            dot(cylinder.axis_location_mm, v))


def _projected(cylinder: Cylinder, axis: Direction) -> float:
    """The cylinder's axis position along one of the carrier plane's axes.

    Any point of a parallel axis projects the same way, so the axis location
    stands for the whole line.
    """
    return dot(cylinder.axis_location_mm, axis)
