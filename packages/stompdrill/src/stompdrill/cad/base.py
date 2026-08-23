"""The kernel-free contract a case model satisfies.

Nothing here imports OpenCASCADE, so the clearance stage can depend on this
module and a test can implement it with arithmetic. Coordinates are canonical
nanometres in the drilled face's own frame.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from stompmodel.frames import FaceFrame
from stompmodel.units import Nanometre

__all__ = ["Rejection", "CaseModel"]


class Rejection(Enum):
    """Why a hole cannot be drilled. The value is the diagnostic code."""

    OFF_FACE = "hole-off-face"
    THROUGH_BOSS = "hole-through-boss"
    OBSTRUCTED = "hole-obstructed"


@runtime_checkable
class CaseModel(Protocol):
    """The kernel-free clearance contract: what ``CheckCaseClearance`` needs.

    Cutting needs a live kernel document and is typed against the
    kernel-backed model directly, never against this protocol — see
    ADR-0007. Declared as read-only properties, not plain attributes: a
    frozen, slotted implementation's fields are themselves read-only, and
    mypy only matches a Protocol's structural members when settability
    agrees.
    """

    @property
    def part(self) -> str: ...
    @property
    def face(self) -> str: ...
    @property
    def model_name(self) -> str:
        """The supplied model file's name, e.g. ``"1590BB.stp"`` -- a name,
        not a path, not a checksum."""
        ...
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
    def frame(self) -> FaceFrame: ...

    def classify(
        self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre
    ) -> Rejection | None: ...
