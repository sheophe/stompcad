"""Refuse holes the supplied casting cannot take.

The model owns the geometry; this stage owns only the translation from a
rejection into a diagnostic, so it is testable against a fake model.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import CaseRegistration, DrillData, Hole, StageRun
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
        """Record the margin, the plate and the play area ``classify()`` used.

        The part, the face and the frame live on ``DrillData.case`` instead,
        a typed member with a codec inverse -- they must not exist in both
        places. The margin is the model's own: it already eroded the play
        area by it at construction, so this stage only reports what
        ``classify()`` used.
        """
        return StageRun(
            self.name,
            (
                ("margin_nm", int(self.model.margin_nm)),
                ("plate_nm", int(self.model.plate_nm)),
                ("play_area_nm", tuple(int(v) for v in self.model.play_area_nm)),
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
        # Attached unconditionally, even when a diagnostic above errored: a
        # document must state what it was checked against either way.
        return data.with_diagnostics(*diagnostics).with_case(
            CaseRegistration(
                self.model.part, self.model.face, self.model.model_name, self.model.frame
            )
        )

    def _reject(self, hole: Hole, rejection: Rejection) -> Diagnostic:
        return Diagnostic.error(
            rejection.value,
            f"⌀{format_nm(hole.diameter_nm)} mm hole at "
            f"({format_nm(hole.x_nm)}, {format_nm(hole.y_nm)}) "
            f"{_REASON[rejection]} of {self.model.part} {self.model.face.value}",
            location_nm=(hole.x_nm, hole.y_nm),
            data=(("diameter_nm", hole.diameter_nm), ("face", self.model.face.value)),
        )

    def _cross_check(self, data: DrillData) -> Diagnostic | None:
        """Compare the model's footprint with the identified enclosure.

        Unidentified: skipped with an INFO, not guessed at. Both footprints
        are reduced to the same descending order before comparing -- see
        ADR-0002 -- because the loader has already discarded the model's own
        length/width labelling, and the catalogue publishes its own pair in
        whatever order Hammond's drawing states (``1590LB`` smaller first).
        Still exact nanometre equality once reduced, stricter than
        ``case.py``'s 0.05 mm or ``enclosure.py``'s 1.5 mm tolerance.
        """
        match = data.enclosure
        if match is None:
            return Diagnostic.info(
                "case-model-unverified",
                f"the panel carries no identified enclosure, so the supplied "
                f"{self.model.part} model could not be checked against it",
            )
        length_nm, width_nm = self.model.footprint_nm
        model_pair = tuple(sorted((length_nm, width_nm), reverse=True))
        catalogue_pair = tuple(sorted((match.length_nm, match.width_nm), reverse=True))
        if model_pair == catalogue_pair:
            return None
        return Diagnostic.error(
            "wrong-case-model",
            f"the panel identifies {match.selected_part or '/'.join(match.candidates)} "
            f"({format_nm(match.length_nm)} x {format_nm(match.width_nm)} mm) but the "
            f"supplied model is {self.model.part} "
            f"({format_nm(length_nm)} x {format_nm(width_nm)} mm)",
            data=(("length_nm", length_nm), ("width_nm", width_nm)),
        )
