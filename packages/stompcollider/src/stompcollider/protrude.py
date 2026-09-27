"""A component's protrusion: where its axis runs, and how wide it is where.

The cylinders answer only where the axis is. What arrests a through-panel
part is almost never one of them -- a potentiometer is stopped by its can, a
footswitch by its body, a jack by a shell with no axis-parallel cylindrical
face at all -- so the profile is the whole solid's radial extent about that
axis, measured by an exact boolean at the radii the panel's own holes admit.
Kernel-backed, but only through ``stompgeom``; nothing here imports OCP.
Measurements only -- millimetre floats upstream of ``canonicalise``, which
is the one place they become canonical lengths. See ADR-0003 and ADR-0008.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from stompgeom.cylinders import Cylinder, cylindrical_faces
from stompgeom.levels import Direction, direction_bin
from stompgeom.radial import axial_extent, radial_reach
from stompgeom.step import StepSolid
from stompmodel.frames import dot
from stompmodel.units import Nanometre, mm_from_nm

from .boards import basis_about
from .raw import RawComponent, RawCylinder

__all__ = ["admissible", "bore_of", "clad_length", "in_plane", "protrusion_of", "reach_along", "wall_axis"]


def admissible(solid: StepSolid, carrier_normal: Direction) -> tuple[Cylinder, ...]:
    """``solid``'s cylindrical faces whose axis lies along ``carrier_normal``.

    A cylinder at any other angle cannot pass through a hole in a flat panel,
    so admitting one risks an axis that means nothing. Parallelism is
    sign-agnostic; only :func:`protrusion_of` reads the direction's sign.
    """
    return _about(solid, lambda cylinder: cylinder.is_parallel_to(carrier_normal))


def _about(
    solid: StepSolid, keep: Callable[[Cylinder], bool]
) -> tuple[Cylinder, ...]:
    """``solid``'s cylindrical faces that ``keep`` admits.

    One walk and one predicate, because :func:`admissible` and
    :func:`in_plane` are the same filter in two modes -- through the panel and
    along the board -- and writing the walk twice would let them drift apart.
    """
    return tuple(
        cylinder for cylinder in cylindrical_faces(solid.shape) if keep(cylinder)
    )


def in_plane(solid: StepSolid, carrier_normal: Direction) -> tuple[Cylinder, ...]:
    """``solid``'s cylindrical faces whose axis lies in the carrier plane.

    :func:`admissible` inverted: that one keeps what could pass *through* a
    flat panel, this one what runs *along* the board, at a wall. Not its
    complement -- a face oblique to both is neither, and neither question
    admits one. Perpendicularity is the kernel's own, as parallelism is there.
    """
    return _about(solid, lambda cylinder: cylinder.is_normal_to(carrier_normal))


def clad_length(faces: Sequence[Cylinder], direction: Direction) -> float:
    """How much of ``direction`` these faces' own surfaces actually cover, in mm.

    The union of their axial extents, not the span between the extremes and
    not their sum: a gap between two features is not material, and one
    surface an exporter split into patches is still that surface -- which
    ``cylindrical_faces`` states is not a fact about the part. Both are why
    this and not reach decides an axis.
    """
    spans = sorted(reach_along(face, direction) for face in faces)
    total, covered_to = 0.0, None
    for low, high in spans:
        if covered_to is None or low > covered_to:
            total += high - low
            covered_to = high
        elif high > covered_to:
            total += high - covered_to
            covered_to = high
    return total


def wall_axis(solid: StepSolid, carrier_normal: Direction) -> Direction | None:
    """The in-plane direction ``solid``'s material clads the most of, or ``None``.

    Grouped on ``direction_bin`` so a bore's two half-faces agree on one
    axis, and sign-folded because an in-plane axis has two and neither is
    known to point at a wall -- the caller measures both. Ties break on the
    bin itself, which is geometry, so two spellings of one part agree
    (ADR-0006).
    """
    faces = in_plane(solid, carrier_normal)
    if not faces:
        return None
    bins: dict[tuple[int, int, int], list[Cylinder]] = {}
    for face in faces:
        key = direction_bin(face.axis_direction)
        bins.setdefault(max(key, tuple(-c for c in key)), []).append(face)  # type: ignore[arg-type]
    best = max(
        bins.items(),
        key=lambda item: (clad_length(item[1], item[1][0].axis_direction), item[0]),
    )
    return best[1][0].axis_direction


def bore_of(faces: Sequence[Cylinder], direction: Direction) -> float | None:
    """The largest concave radius among the faces along ``direction``, or ``None``.

    A plug entering a bore has to pass the wall even where no material of
    the part protrudes, which is the whole reason a bore is measured at all
    (decision 7). Parallel rather than coaxial: a part's bore and its
    envelope are one feature seen from two sides, and a bore offset from the
    envelope's own axis is still a bore that plug goes into.
    """
    concave = [
        face.radius_mm
        for face in faces
        if face.concave and face.is_parallel_to(direction)
    ]
    return max(concave) if concave else None


def protrusion_of(
    solid: StepSolid, carrier_normal: Direction, probes_nm: Sequence[Nanometre] = ()
) -> RawComponent | None:
    """``solid``'s measured protrusion, or ``None`` when it has no axis.

    ``carrier_normal`` is signed: it points away from the board, at the
    panel, and the admitted cylinder reaching furthest along it fixes the
    axis. ``probes_nm`` are the radii the panel's holes admit; the solid is
    cut against each, which is what states the width of a can or a body no
    cylinder describes. A component yielding no admissible cylinder has no
    axis and cannot pair.
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
        tip_mm=tip_mm,
        # Every coaxial face, stated as measured, and every radius a hole
        # admits, stated as cut. Deduplicating a seam's two halves and
        # ordering the stack are both ``canonicalise``'s, where the values
        # are whole nanometres: exact equality is a fact about those and not
        # about a millimetre float, and a set keyed on one would be the
        # composite float key ADR-0003's boundary rules out.
        stack=tuple(
            _measured(cylinder, carrier_normal, tip_mm)
            for cylinder in admitted
            if tipmost.is_coaxial_with(cylinder)
        )
        + _cut(solid, tipmost, carrier_normal, tip_mm, probes_nm),
    )


def _cut(
    solid: StepSolid,
    tipmost: Cylinder,
    outward: Direction,
    tip_mm: float,
    probes_nm: Sequence[Nanometre],
) -> tuple[RawCylinder, ...]:
    """One band per probe radius the solid is wider than somewhere.

    *Strictly* wider than the probe is, in whole nanometres, at least one
    nanometre wider, and ``probe_nm + 1`` is both the radius the cut is
    measured at and the radius the band records -- one number, not two.
    The radius a profile is asked about is a radius it was probed at:
    ``model.admitting_radius`` states it once, for this module's caller and
    for ``Match``. Each band runs to the part's far end, the deepest depth.
    """
    ends_mm = tip_mm - axial_extent(solid.shape, outward)[0]
    bands = []
    for probe_nm in sorted(set(probes_nm)):
        reach_mm = radial_reach(
            solid.shape,
            tipmost.axis_location_mm,
            outward,
            mm_from_nm(Nanometre(probe_nm + 1)),
        )
        if reach_mm is None:
            continue
        bands.append(
            RawCylinder(
                radius_mm=mm_from_nm(Nanometre(probe_nm + 1)),
                depth_from_tip_min_mm=tip_mm - reach_mm,
                depth_from_tip_max_mm=ends_mm,
            )
        )
    return tuple(bands)


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
