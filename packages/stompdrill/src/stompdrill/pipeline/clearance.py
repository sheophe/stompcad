"""Refuse holes the supplied casting cannot take.

The model owns the geometry; this stage owns only the translation from a
rejection into a diagnostic, so it is testable against a fake model.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData, Hole, StageRun
from stompmodel.units import Nanometre, format_nm

from ..cad import CaseModel, Rejection

__all__ = ["CheckCaseClearance"]

_REASON: dict[Rejection, str] = {
    Rejection.OFF_FACE: "lies outside the drilled face",
    Rejection.THROUGH_BOSS: "meets a boss or rib in the plate",
    Rejection.OBSTRUCTED: "is obstructed behind the plate once assembled",
}


class CheckCaseClearance:
    """Diagnose every hole the supplied case model rejects. Drops nothing."""

    name: ClassVar[str] = "check-case-clearance"

    def __init__(self, model: CaseModel) -> None:
        self.model = model

    def describe(self) -> StageRun:
        """Record the model, the face, the margin and the frame it registered.

        The margin is the model's own: it already eroded the play area by it
        at construction, so this stage only reports what ``classify()`` used.
        """
        return StageRun(
            self.name,
            (
                ("part", self.model.part),
                ("face", self.model.face),
                ("margin_nm", int(self.model.margin_nm)),
                ("plate_nm", int(self.model.plate_nm)),
                ("play_area_nm", tuple(int(v) for v in self.model.play_area_nm)),
                *self.model.frame.basis.as_parameters(),
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        diagnostics = [d for d in (self._cross_check(data),) if d is not None]
        for hole in data.holes:
            # Ceiling, not floor: an odd-nanometre diameter must round the bit
            # radius up, never down. Floor division is optimistic by half a
            # nanometre, biasing a marginal hole towards passing -- the wrong
            # direction for a check whose job is to stop metal being cut.
            radius_nm = Nanometre(-(-hole.diameter_nm // 2))
            rejection = self.model.classify(hole.x_nm, hole.y_nm, radius_nm)
            if rejection is not None:
                diagnostics.append(self._reject(hole, rejection))
        return data.with_diagnostics(*diagnostics)

    def _reject(self, hole: Hole, rejection: Rejection) -> Diagnostic:
        return Diagnostic.error(
            rejection.value,
            f"⌀{format_nm(hole.diameter_nm)} mm hole at "
            f"({format_nm(hole.x_nm)}, {format_nm(hole.y_nm)}) "
            f"{_REASON[rejection]} of {self.model.part} {self.model.face}",
            location_nm=(hole.x_nm, hole.y_nm),
            data=(("diameter_nm", hole.diameter_nm), ("face", self.model.face)),
        )

    def _cross_check(self, data: DrillData) -> Diagnostic | None:
        """Compare the model's footprint with the identified enclosure.

        Unidentified: skipped with an INFO, not guessed at. Exact nanometre
        equality, stricter than ``case.py``'s 0.05 mm or ``enclosure.py``'s
        1.5 mm, because this gates an exit-2 error withholding every
        artefact. Safe because it is measured: all four cached Hammond
        models' in-plane spans round to their catalogue nanometre exactly.
        Revisit if a future model's bbox carries a nanometre of noise.
        """
        match = data.enclosure
        if match is None:
            return Diagnostic.info(
                "case-model-unverified",
                f"the panel carries no identified enclosure, so the supplied "
                f"{self.model.part} model could not be checked against it",
            )
        length_nm, width_nm = self.model.footprint_nm
        if (match.length_nm, match.width_nm) == (length_nm, width_nm):
            return None
        return Diagnostic.error(
            "wrong-case-model",
            f"the panel identifies {match.selected_part or '/'.join(match.candidates)} "
            f"({format_nm(match.length_nm)} x {format_nm(match.width_nm)} mm) but the "
            f"supplied model is {self.model.part} "
            f"({format_nm(length_nm)} x {format_nm(width_nm)} mm)",
            data=(("length_nm", length_nm), ("width_nm", width_nm)),
        )
