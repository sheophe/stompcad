"""Refuse holes the supplied casting cannot take.

The model owns the geometry; this stage owns only the translation from a
rejection into a diagnostic, so it is testable against a fake model.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseRegistration, DrillData, EnclosureMatch, Hole, StageRun
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
        # The frame the most recent ``apply()`` actually evaluated holes in
        # -- the model's own frame until a rotated panel reconciles it.
        # ``describe()`` reads this back rather than recomputing a rotation
        # of its own, so the play area it reports is never stated in a frame
        # ``apply()`` did not use. Defaults to the model's own frame so a
        # ``describe()`` called with no preceding ``apply()`` still reports
        # today's figure. See ADR-0007.
        self._checked_frame: FaceFrame = model.frame

    def describe(self) -> StageRun:
        """Record the margin, the plate and the play area ``classify()`` used.

        The part, the face and the frame live on ``DrillData.case`` instead,
        a typed member with a codec inverse -- they must not exist in both
        places. The margin is the model's own: it already eroded the play
        area by it at construction, so this stage only reports what
        ``classify()`` used, restated in the frame ``apply()`` last checked.
        """
        return StageRun(
            self.name,
            (
                ("margin_nm", int(self.model.margin_nm)),
                ("plate_nm", int(self.model.plate_nm)),
                ("play_area_nm", tuple(int(v) for v in self._play_area_in(self._checked_frame))),
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        frame = self._reconciled_frame(data.enclosure)
        self._checked_frame = frame
        identity = frame is self.model.frame
        diagnostics = [
            d
            for d in (self._cross_check(data), self._orientation_notice(data.enclosure))
            if d is not None
        ]
        for hole in data.holes:
            # Ceiling, not floor: an odd-nanometre diameter must round the bit
            # radius up, never down. Floor division is optimistic by half a
            # nanometre, biasing a marginal hole towards passing -- the wrong
            # direction for a check whose job is to stop metal being cut.
            radius_nm = Nanometre(-(-hole.diameter_nm // 2))
            if identity:
                # No detour through the reframe arithmetic below: an
                # unrotated (or unidentified) panel is checked exactly as it
                # always was, byte for byte -- see ADR-0007.
                qx_nm, qy_nm = hole.x_nm, hole.y_nm
            else:
                qx_nm, qy_nm = frame.basis.reframe(hole.x_nm, hole.y_nm, self.model.frame.basis)
            rejection = self.model.classify(qx_nm, qy_nm, radius_nm)
            if rejection is not None:
                diagnostics.append(self._reject(hole, rejection))
        # Attached unconditionally, even when a diagnostic above errored: a
        # document must state what it was checked against either way. The
        # frame recorded is the one holes were actually checked in, so the
        # cutter reads it back rather than re-deriving its own.
        return data.with_diagnostics(*diagnostics).with_case(
            CaseRegistration(self.model.part, self.model.face, self.model.model_name, frame)
        )

    def _reconciled_frame(self, match: EnclosureMatch | None) -> FaceFrame:
        """Restate the model's own face frame in the panel's drawn orientation.

        ``EnclosureMatch.rotated`` records only *that* the panel is the
        catalogue footprint turned a quarter turn, never *which way*: both
        candidate turns are orthonormal, right-handed and preserve ``w``, so
        the direction is a stated convention (pinned in ADR-0007), not a
        derived value -- ``u`` takes the model's own ``v``, ``v`` its
        negated ``u``. Unidentified or unrotated returns the same object
        unchanged, so ``apply()`` can skip reframing.
        """
        if match is None or not match.rotated:
            return self.model.frame
        basis = self.model.frame.basis
        ux, uy, uz = basis.u
        return FaceFrame(
            basis=CoordinateFrame(
                origin_nm=basis.origin_nm,
                u=basis.v,
                v=(-ux, -uy, -uz),
                w=basis.w,
            )
        )

    def _play_area_in(
        self, frame: FaceFrame
    ) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre]:
        """Restate the model's own play-area rectangle in ``frame``.

        Every corner is carried through the model's own frame rather than
        assuming which axis moved, so one implementation covers the identity
        case and either quarter turn alike -- the same generality
        ``cad.region.region_bbox_nm`` already relies on for its own corners.
        The identity case is returned untouched rather than reframed: a
        reframe round-trips through millimetres, and a document that was
        never rotated must not gain a nanometre of drift it never earned.
        """
        if frame is self.model.frame:
            return self.model.play_area_nm
        x0_nm, y0_nm, x1_nm, y1_nm = self.model.play_area_nm
        basis = self.model.frame.basis
        corners = [
            basis.reframe(x_nm, y_nm, frame.basis)
            for x_nm in (x0_nm, x1_nm)
            for y_nm in (y0_nm, y1_nm)
        ]
        xs = [corner[0] for corner in corners]
        ys = [corner[1] for corner in corners]
        return (Nanometre(min(xs)), Nanometre(min(ys)), Nanometre(max(xs)), Nanometre(max(ys)))

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

    def _orientation_notice(self, match: EnclosureMatch | None) -> Diagnostic | None:
        """Warn where the panel-to-model axis correspondence cannot be told.

        Exactly two cases: no identified enclosure to reconcile the frame
        against, or an identified footprint whose two dimensions are equal,
        where ``cad.case.build_frame``'s own tie-break has no signal to
        confirm or contradict. WARNING, not ERROR, for the same reason
        ``case-model-unverified`` is not: the check could not run, which is
        not a wrong answer -- an error would refuse every square-enclosure
        user the tool serves today.
        """
        if match is None:
            return Diagnostic.warning(
                "case-orientation-unverifiable",
                "no enclosure was identified, so the panel's drawn orientation "
                "cannot be reconciled with the supplied model's axes; holes are "
                "checked against the model's own axes, unrotated",
            )
        if match.length_nm == match.width_nm:
            return Diagnostic.warning(
                "case-orientation-unverifiable",
                f"the identified {match.family} footprint is square and carries no "
                "preferred in-plane orientation, so the panel's drawn orientation "
                "cannot be confirmed against the supplied model's axes",
            )
        return None
