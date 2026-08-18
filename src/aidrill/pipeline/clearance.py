"""Refuse holes the supplied casting cannot take.

The model owns the geometry; this stage owns only the translation from a
rejection into a diagnostic, so it is testable against a fake model.
"""

from __future__ import annotations

from typing import ClassVar, cast

from ..cad import CaseModel, Rejection
from ..model import Diagnostic, DrillData, Hole, ParameterValue, StageRun
from ..units import Nanometre, format_nm

__all__ = ["CheckCaseClearance"]

_REASON: dict[Rejection, str] = {
    Rejection.OFF_FACE: "lies outside the drilled face",
    Rejection.THROUGH_BOSS: "meets a boss or rib in the plate",
    Rejection.OBSTRUCTED: "is obstructed behind the plate once assembled",
}


class CheckCaseClearance:
    """Diagnose every hole the supplied case model rejects. Drops nothing."""

    name: ClassVar[str] = "check-case-clearance"

    def __init__(self, model: CaseModel, margin_nm: Nanometre) -> None:
        self.model = model
        self.margin_nm = margin_nm

    def describe(self) -> StageRun:
        """Record the model, the face, the margin and the frame it registered.

        ``Frame.as_parameters()`` is typed against ``object`` because ``cad``
        knows nothing of ``ParameterValue``; the cast asserts what its own
        docstring already promises, that every element is StageRun-safe.
        """
        frame_parameters = cast(
            "tuple[tuple[str, ParameterValue], ...]", self.model.frame.as_parameters()
        )
        return StageRun(
            self.name,
            (
                ("part", self.model.part),
                ("face", self.model.face),
                ("margin_nm", int(self.margin_nm)),
                ("plate_nm", int(self.model.plate_nm)),
                ("play_area_nm", tuple(int(v) for v in self.model.play_area_nm)),
                *frame_parameters,
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        diagnostics = [d for d in (self._cross_check(data),) if d is not None]
        for hole in data.holes:
            rejection = self.model.classify(
                hole.x_nm, hole.y_nm, Nanometre(hole.diameter_nm // 2)
            )
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

        An unidentified panel has nothing to compare against, so the check is
        skipped with an INFO rather than guessed at.
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
