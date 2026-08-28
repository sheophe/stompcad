"""A component's protrusion: which cylinders count, and the profile they make.

Kernel-backed, but only through ``stompgeom``: the parallelism and
coaxiality rules are the kernel's own tolerances, published as ``Cylinder``
methods, and nothing here imports OCP. See "Protrusions" in
``docs/specs/stompcollider-technical.md`` and ADR-0008 for the layering.
"""

from __future__ import annotations

from stompgeom.cylinders import Cylinder, cylindrical_faces
from stompgeom.levels import Direction
from stompgeom.step import StepSolid
from stompmodel.units import Millimetre, Nanometre, nm_from_mm

from .boards import basis_about
from .model import Profile, Protrusion

__all__ = ["admissible", "protrusion_of"]


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


def protrusion_of(solid: StepSolid, carrier_normal: Direction) -> Protrusion | None:
    """``solid``'s protrusion along ``carrier_normal``, or ``None`` when it has none.

    ``carrier_normal`` is signed: it points away from the board, at the
    panel, and the admitted cylinder reaching furthest along it fixes the
    axis. Every cylinder coaxial with that one forms the stack, and the
    profile is their radius against depth from the tip -- never a diameter.
    A component yielding no admissible cylinder has no axis and cannot pair.
    """
    admitted = admissible(solid, carrier_normal)
    if not admitted:
        return None
    u, v = basis_about(carrier_normal)
    tipmost = max(admitted, key=lambda c: _tip_key(c, carrier_normal, u, v))
    tip_mm = _reach(tipmost, carrier_normal)[1]
    stack = [cylinder for cylinder in admitted if tipmost.is_coaxial_with(cylinder)]
    steps = sorted(
        {_step(cylinder, carrier_normal, tip_mm) for cylinder in stack},
        # Depth first, so the tip leads and the profile reads outside in;
        # the whole key is geometry, never the order the faces were walked.
        key=lambda step: (step[1], step[2], step[0]),
    )
    return Protrusion(
        designator=solid.name,
        axis_xy_nm=(_projected(tipmost, u), _projected(tipmost, v)),
        profile=Profile(steps=tuple(steps)),
    )


def _step(
    cylinder: Cylinder, outward: Direction, tip_mm: float
) -> tuple[Nanometre, Nanometre, Nanometre]:
    """One cylinder as ``(radius, depth from the tip, to depth)``, in nanometres.

    Depth grows away from the tip, so a cylinder's far end along ``outward``
    is its shallow bound. Scaled once here, at the one boundary where a
    measurement becomes a canonical length (ADR-0003).
    """
    low_mm, high_mm = _reach(cylinder, outward)
    return (
        nm_from_mm(cylinder.radius_mm),
        nm_from_mm(Millimetre(tip_mm - high_mm)),
        nm_from_mm(Millimetre(tip_mm - low_mm)),
    )


def _reach(cylinder: Cylinder, outward: Direction) -> tuple[float, float]:
    """Where the cylinder's two end circles sit along ``outward``, least first."""
    base = _dot(cylinder.axis_location_mm, outward)
    step = _dot(cylinder.axis_direction, outward)
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
    low, high = _reach(cylinder, outward)
    return (high, cylinder.radius_mm, low, _dot(cylinder.axis_location_mm, u),
            _dot(cylinder.axis_location_mm, v))


def _projected(cylinder: Cylinder, axis: Direction) -> Nanometre:
    """The cylinder's axis position along one of the carrier plane's axes.

    Any point of a parallel axis projects the same way, so the axis location
    stands for the whole line.
    """
    return nm_from_mm(Millimetre(_dot(cylinder.axis_location_mm, axis)))


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
