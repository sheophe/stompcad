"""A coordinate frame, and the face registration that wraps one.

A frame is a registration rather than an operation, so the value lives in the
leaf and the kernel code that builds one lives above it. That keeps the graph
linear and lets a consumer take a frame without taking a CAD kernel. See
ADR-0009.
"""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import ParameterValue
from .units import Millimetre, Nanometre, mm_from_nm, nm_from_mm

__all__ = ["CoordinateFrame", "FaceFrame"]


@dataclass(frozen=True, slots=True)
class CoordinateFrame:
    """An origin and a right-handed basis.

    Carries no meaning about what it registers -- that is the point. The
    meaning is added by wrapping, not by a field here.
    """

    origin_nm: tuple[Nanometre, Nanometre, Nanometre]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    w: tuple[float, float, float]

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

    def as_parameters(self) -> tuple[tuple[str, ParameterValue], ...]:
        """Flatten to ``StageRun``-safe scalars and float tuples."""
        return (
            ("frame_origin_nm", tuple(self.origin_nm)),
            ("frame_u", self.u),
            ("frame_v", self.v),
            ("frame_w", self.w),
        )


@dataclass(frozen=True, slots=True)
class FaceFrame:
    """A face's registration: a frame whose third axis is that face's normal.

    Composes rather than extends. A subclass would pass wherever a bare
    ``CoordinateFrame`` is wanted, which is exactly the universal-wrapped-in-a-
    meaning leak ADR-0008 names as this boundary's standing risk.
    """

    basis: CoordinateFrame
