"""A coordinate frame, and the face registration that wraps one.

A frame is a registration rather than an operation, so the value lives in the
leaf and the kernel code that builds one lives above it. That keeps the graph
linear and lets a consumer take a frame without taking a CAD kernel. See
ADR-0009.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .units import Millimetre, Nanometre, check_nanometres, mm_from_nm, nm_from_mm

__all__ = ["CoordinateFrame", "FaceFrame", "RigidTransform"]

#: One coordinate frame's origin plus each of its three basis vectors.
_COMPONENTS = 3

#: Orthonormality and right-handedness tolerance for a frame's basis.
#: Measured directly against the four catalogued Hammond models' box and lid
#: faces (1590BB, 1590B, 1590A, 1590Y -- eight frames in all, built by
#: ``stompdrill.cad.case.build_frame`` from real kernel face normals): every
#: unit-length, orthogonality and right-handedness deviation measured exactly
#: 0.0, because each face normal ``stompgeom`` reports for these enclosures is
#: already axis-aligned, so normalising and cross-multiplying it introduces no
#: rounding at all. This sits at float-epsilon scale above that measured
#: figure -- headroom for a future model whose face is not axis-aligned,
#: where normalising a kernel-reported direction can drift by a few ULPs --
#: and matches the tolerance `stompdrill`'s own kernel tests already assert
#: for these same frames (``test_cad_case.py::test_the_frame_is_orthonormal``,
#: ``::test_the_frame_basis_is_right_handed_about_the_outward_normal``).
_BASIS_TOLERANCE = 1e-9


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


@dataclass(frozen=True, slots=True)
class RigidTransform:
    """A rotation then a translation: one rigid motion of a body.

    Millimetre floats rather than nanometres. This is applied to kernel
    geometry, which is float millimetres throughout; a canonical length is
    what a document states, and a document never states this value.
    """

    rotation: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ]
    translation_mm: tuple[float, float, float]

    def apply_point(self, point_mm: tuple[float, float, float]) -> tuple[float, float, float]:
        """Rotate and translate a position."""
        return tuple(  # type: ignore[return-value]
            _dot(row, point_mm) + shift
            for row, shift in zip(self.rotation, self.translation_mm)
        )

    def apply_direction(
        self, direction: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        """Rotate an orientation. A direction has no origin to translate."""
        return tuple(_dot(row, direction) for row in self.rotation)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    """An origin and a right-handed basis.

    Carries no meaning about what it registers -- that is the point. The
    meaning is added by wrapping, not by a field here.

    Validated at construction like every other canonical value the document
    carries: whole-nanometre origin, three finite components each, an
    orthonormal and right-handed basis -- see ADR-0004.
    """

    origin_nm: tuple[Nanometre, Nanometre, Nanometre]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    w: tuple[float, float, float]

    def __post_init__(self) -> None:
        for name, vector in (
            ("origin_nm", self.origin_nm),
            ("u", self.u),
            ("v", self.v),
            ("w", self.w),
        ):
            if len(vector) != _COMPONENTS:
                raise ValueError(
                    f"CoordinateFrame.{name} must have exactly three components, "
                    f"not {len(vector)}"
                )
        check_nanometres(
            "CoordinateFrame",
            **{f"origin_nm[{i}]": value for i, value in enumerate(self.origin_nm)},
        )
        for name, vector in (("u", self.u), ("v", self.v), ("w", self.w)):
            if not all(isinstance(c, (int, float)) and math.isfinite(c) for c in vector):
                raise ValueError(f"CoordinateFrame.{name} must be finite, not {vector!r}")
        for name, vector in (("u", self.u), ("v", self.v), ("w", self.w)):
            length = math.sqrt(_dot(vector, vector))
            if abs(length - 1.0) > _BASIS_TOLERANCE:
                raise ValueError(
                    f"CoordinateFrame.{name} must be unit length, not {vector!r} "
                    f"(length {length!r})"
                )
        for first, second in (("u", "v"), ("u", "w"), ("v", "w")):
            if abs(_dot(getattr(self, first), getattr(self, second))) > _BASIS_TOLERANCE:
                raise ValueError(
                    f"CoordinateFrame.{first} and CoordinateFrame.{second} "
                    "must be orthogonal"
                )
        cross = _cross(self.u, self.v)
        if any(abs(c - w) > _BASIS_TOLERANCE for c, w in zip(cross, self.w)):
            raise ValueError(
                "CoordinateFrame.w must equal u cross v, a right-handed basis, "
                f"not {self.w!r}"
            )

    def to_model(
        self, x_nm: Nanometre, y_nm: Nanometre, depth_nm: Nanometre = Nanometre(0)
    ) -> tuple[Millimetre, Millimetre, Millimetre]:
        """Map canonical face coordinates, at an optional depth, into model mm.

        ``depth_nm`` runs along ``w``. Optional so that a caller stating a
        point on the frame's own plane -- which is what canonical means --
        need not say so.
        """
        x, y, z = mm_from_nm(x_nm), mm_from_nm(y_nm), mm_from_nm(depth_nm)
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        return (
            Millimetre(origin[0] + x * self.u[0] + y * self.v[0] + z * self.w[0]),
            Millimetre(origin[1] + x * self.u[1] + y * self.v[1] + z * self.w[1]),
            Millimetre(origin[2] + x * self.u[2] + y * self.v[2] + z * self.w[2]),
        )

    def to_canonical(
        self, point_mm: tuple[float, float, float]
    ) -> tuple[Millimetre, Millimetre, Millimetre]:
        """Project a model point onto all three of this frame's own axes.

        The third value is the signed depth along ``w``, zero for a point on
        the frame's plane. Symmetric with ``to_model``, which is already
        three-dimensional.

        Millimetres, not nanometres: ``region_bbox_nm`` projects four corners
        and rounds once after its own minimum and maximum, and rounding here
        would round each corner first instead.
        """
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        relative = tuple(p - o for p, o in zip(point_mm, origin))
        x = sum(r * c for r, c in zip(relative, self.u))
        y = sum(r * c for r, c in zip(relative, self.v))
        z = sum(r * c for r, c in zip(relative, self.w))
        return (Millimetre(x), Millimetre(y), Millimetre(z))

    def reframe(
        self, x_nm: Nanometre, y_nm: Nanometre, target: CoordinateFrame
    ) -> tuple[Nanometre, Nanometre]:
        """Restate a canonical point registered here in ``target``'s frame."""
        # The depth is dropped deliberately, not overlooked: it is the
        # separation of the two planes, non-zero whenever a box face and its
        # lid are reframed against each other, and a canonical point is
        # two-dimensional by definition. Widen this only with its callers.
        x_mm, y_mm, _depth_mm = target.to_canonical(self.to_model(x_nm, y_nm))
        return nm_from_mm(x_mm), nm_from_mm(y_mm)

    def translated_nm(
        self, du_nm: Nanometre, dv_nm: Nanometre, dw_nm: Nanometre
    ) -> CoordinateFrame:
        """A copy moved along this frame's own axes, basis unchanged."""
        shifted = tuple(
            origin + nm_from_mm(
                mm_from_nm(du_nm) * self.u[i]
                + mm_from_nm(dv_nm) * self.v[i]
                + mm_from_nm(dw_nm) * self.w[i]
            )
            for i, origin in enumerate(self.origin_nm)
        )
        return CoordinateFrame(
            origin_nm=(Nanometre(shifted[0]), Nanometre(shifted[1]), Nanometre(shifted[2])),
            u=self.u, v=self.v, w=self.w,
        )

    def rotated_about_w(self, radians: float) -> CoordinateFrame:
        """A copy turned about its own normal, origin and ``w`` unchanged."""
        cos, sin = math.cos(radians), math.sin(radians)
        turned_u = tuple(cos * a + sin * b for a, b in zip(self.u, self.v))
        turned_v = tuple(-sin * a + cos * b for a, b in zip(self.u, self.v))
        return CoordinateFrame(
            origin_nm=self.origin_nm,
            u=(turned_u[0], turned_u[1], turned_u[2]),
            v=(turned_v[0], turned_v[1], turned_v[2]),
            w=self.w,
        )

    def placement_onto(self, target: CoordinateFrame) -> RigidTransform:
        """The rigid motion carrying this frame onto ``target``.

        Not a coordinate restatement -- ``to_canonical`` composed with
        ``to_model`` is that. This moves a body; that renames a point.
        """
        # The inner tuple() must materialise immediately: a nested generator
        # left lazy would close over the outer loop's `i` by reference, so
        # every row would read back the final value of `i` once consumed.
        rotation = tuple(
            tuple(
                target.u[i] * self.u[j] + target.v[i] * self.v[j] + target.w[i] * self.w[j]
                for j in range(_COMPONENTS)
            )
            for i in range(_COMPONENTS)
        )
        here = tuple(mm_from_nm(value) for value in self.origin_nm)
        there = tuple(mm_from_nm(value) for value in target.origin_nm)
        translation = tuple(
            there[i] - sum(r * h for r, h in zip(rotation[i], here))
            for i in range(_COMPONENTS)
        )
        return RigidTransform(
            rotation=rotation,  # type: ignore[arg-type]
            translation_mm=(translation[0], translation[1], translation[2]),
        )


@dataclass(frozen=True, slots=True)
class FaceFrame:
    """A face's registration: a frame whose third axis is that face's normal.

    ``basis.origin_nm`` sits on the **inner** surface -- never the side the
    bit enters; see ADR-0007. ``basis.w``'s sense is unrelated to that datum
    and is a *stated* convention, not derivable: it is the **outward** normal,
    away from the material and out of the enclosure, and both senses satisfy
    ``CoordinateFrame``'s own checks equally, so no validator can recover it
    (ADR-0009). Composes rather than extends -- a subclass would pass wherever
    a bare ``CoordinateFrame`` is wanted, the leak ADR-0008 names as this risk.
    """

    basis: CoordinateFrame
