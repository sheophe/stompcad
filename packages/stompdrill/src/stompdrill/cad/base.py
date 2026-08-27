"""The kernel-free contract a case model satisfies.

Nothing here imports OpenCASCADE, so the clearance stage can depend on this
module and a test can implement it with arithmetic. Coordinates are canonical
nanometres in the drilled face's own frame.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from stompmodel.frames import FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre

__all__ = ["Rejection", "CaseModel", "step_keyword"]


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
    def face(self) -> CaseFace: ...
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


#: The upper-cased product-name substring each face's solid is found by.
#: Published once, here, because this is the only module both the solid
#: selector and the STEP emitter can reach without importing the kernel --
#: keyed on the closed enumeration so a face with no entry raises rather
#: than falling through to a default.
_STEP_KEYWORD: dict[CaseFace, str] = {CaseFace.BOX: "BOX", CaseFace.LID: "LID"}


def step_keyword(face: CaseFace) -> str:
    """The upper-cased product-name substring this face's solid is found by."""
    return _STEP_KEYWORD[face]
