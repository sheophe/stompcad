"""The kernel-free contract a case model satisfies.

Nothing here imports OpenCASCADE, so the clearance stage can depend on this
module and a test can implement it with arithmetic. Coordinates are canonical
nanometres in the drilled face's own frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ..errors import StompdrillError
from ..model import ParameterValue
from ..units import Nanometre

__all__ = ["Rejection", "Frame", "CaseModel", "KernelUnavailable"]


class KernelUnavailable(StompdrillError):
    """The geometry kernel is needed and not installed."""


class Rejection(Enum):
    """Why a hole cannot be drilled. The value is the diagnostic code."""

    OFF_FACE = "hole-off-face"
    THROUGH_BOSS = "hole-through-boss"
    OBSTRUCTED = "hole-obstructed"


@dataclass(frozen=True, slots=True)
class Frame:
    """Canonical-to-model registration: an origin and a right-handed basis.

    ``w`` is the drilled face's outward normal, and ``(u, v, w)`` is
    right-handed, so ``u`` runs right and ``v`` up when the face is viewed from
    outside. Recorded as provenance, not consumed as an interface.
    """

    origin_nm: tuple[Nanometre, Nanometre, Nanometre]
    u: tuple[float, float, float]
    v: tuple[float, float, float]
    w: tuple[float, float, float]

    def as_parameters(self) -> tuple[tuple[str, ParameterValue], ...]:
        """Flatten to ``StageRun``-safe scalars and float tuples."""
        return (
            ("frame_origin_nm", tuple(self.origin_nm)),
            ("frame_u", self.u),
            ("frame_v", self.v),
            ("frame_w", self.w),
        )


@runtime_checkable
class CaseModel(Protocol):
    """A supplied enclosure, reduced to what clearance and cutting need.

    Declared as read-only properties, not plain attributes: a frozen,
    slotted implementation's fields are themselves read-only, and mypy
    only matches a Protocol's structural members when settability agrees.
    """

    @property
    def part(self) -> str: ...
    @property
    def face(self) -> str: ...
    @property
    def footprint_nm(self) -> tuple[Nanometre, Nanometre]: ...
    @property
    def plate_nm(self) -> Nanometre: ...
    @property
    def play_area_nm(self) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre]: ...
    @property
    def margin_nm(self) -> Nanometre:
        """Clearance the play area was already eroded by, at construction."""
        ...
    @property
    def frame(self) -> Frame: ...

    def classify(
        self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre
    ) -> Rejection | None: ...
