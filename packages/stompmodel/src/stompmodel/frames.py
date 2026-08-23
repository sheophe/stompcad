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

__all__ = ["CoordinateFrame", "FaceFrame"]

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
        self, x_nm: Nanometre, y_nm: Nanometre
    ) -> tuple[Millimetre, Millimetre, Millimetre]:
        """Map canonical face coordinates into model millimetres."""
        x, y = mm_from_nm(x_nm), mm_from_nm(y_nm)
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        return (
            Millimetre(origin[0] + x * self.u[0] + y * self.v[0]),
            Millimetre(origin[1] + x * self.u[1] + y * self.v[1]),
            Millimetre(origin[2] + x * self.u[2] + y * self.v[2]),
        )

    def to_canonical(
        self, point_mm: tuple[float, float, float]
    ) -> tuple[Millimetre, Millimetre]:
        """Project a model point onto this frame's own axes, in millimetres.

        Millimetres, not nanometres: ``region_bbox_nm`` projects four corners
        and rounds once after its own minimum and maximum, and rounding here
        would round each corner first instead.
        """
        origin = tuple(mm_from_nm(value) for value in self.origin_nm)
        relative = tuple(p - o for p, o in zip(point_mm, origin))
        x = sum(r * c for r, c in zip(relative, self.u))
        y = sum(r * c for r, c in zip(relative, self.v))
        return (Millimetre(x), Millimetre(y))

    def reframe(
        self, x_nm: Nanometre, y_nm: Nanometre, target: CoordinateFrame
    ) -> tuple[Nanometre, Nanometre]:
        """Restate a canonical point registered here in ``target``'s frame."""
        x_mm, y_mm = target.to_canonical(self.to_model(x_nm, y_nm))
        return nm_from_mm(x_mm), nm_from_mm(y_mm)


@dataclass(frozen=True, slots=True)
class FaceFrame:
    """A face's registration: a frame whose third axis is that face's normal.

    Composes rather than extends. A subclass would pass wherever a bare
    ``CoordinateFrame`` is wanted, which is exactly the universal-wrapped-in-a-
    meaning leak ADR-0008 names as this boundary's standing risk.
    """

    basis: CoordinateFrame
