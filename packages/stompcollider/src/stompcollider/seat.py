"""``Seat``: how far a board travels along the face normal, and rank order.

The enclosure decides where a board comes to rest, by a search along the
insertion path; it arrives through a supplied
:class:`~stompcollider.insert.Cavity` and is absent without it, and the
hole geometry -- a reduction over what ``Match`` already found, with no
kernel query and no descent -- is what answers a board the enclosure never
touches, and what a shortfall is stated against. Anything else that would
foul at the resting depth is a clash for a later stage to report.
"""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame
from stompmodel.model import StageRun
from stompmodel.units import Nanometre, format_nm

from .insert import Cavity, Insertion
from .model import CLOSURE_KIND, Board, DockData, Placement

__all__ = ["Seat", "rank_key", "shortfall_nm"]


def rank_key(placement: Placement) -> tuple[int, int, int, int, float, int, int]:
    """The spec's lexicographic key, led by how far the board really went in.

    **Insertion shortfall first, and it dominates.** A board arrested well
    out of the enclosure fouls less of it precisely because it never
    entered, so a key led by the clash fields rewards the seating whose
    parts are nowhere near their holes -- measured on the tar assembly, by
    19 mm against the seating the operator assembles by hand.

    Behind it the clash fields, whole, so the clash stage feeds this
    comparator rather than replacing one: a clean placement scores zero on
    all four leading fields and orders on the transform alone. The volume
    compared is the material shared, never the box around it -- a box over
    a whole board overstates what meets by a factor the spec measures at
    fifty. Depth still comes from the box. What closes over the cavity is
    excluded: stage one filters on the enclosure a board is inserted into,
    and a lid that will not close is a finding rather than a reason to
    prefer one seating of that board to another.
    """
    counted = tuple(clash for clash in placement.clashes if clash.kind != CLOSURE_KIND)
    return (
        shortfall_nm(placement),
        len(counted),
        sum(clash.common_volume_nm3 for clash in counted),
        max((int(clash.depth_nm) for clash in counted), default=0),
        placement.theta_deg,
        int(placement.x_nm),
        int(placement.y_nm),
    )


def shortfall_nm(placement: Placement) -> int:
    """How far short of the seat its own holes fix this placement rests.

    A difference of two fields of the placement rather than a field of its
    own: the correspondences state the seat and ``z_nm`` states where the
    board came to rest, so nothing has to be carried through a stage to
    keep the two in step. Negative where the enclosure let the board
    further in than its profile predicted, which is not a failure of
    either -- see :class:`~stompcollider.insert.Insertion`.
    """
    return int(_seated_z_nm(placement)) - int(placement.z_nm)


def _seated_z_nm(placement: Placement) -> Nanometre:
    """Travel along the face normal: the least seating any pairing allows.

    Each correspondence states where that pairing alone would bring the
    board to rest, negative into the cavity; the board stops at the first
    of them, which is the least. ``Correspondence.seat_nm`` is ``None`` for
    a part the hole admits fully -- excluded here, never coerced to zero. A
    placement whose every correspondence is unbounded seats at the panel
    surface, ``z_nm = 0``.
    """
    bounded_nm = [
        correspondence.seat_nm
        for correspondence in placement.correspondence
        if correspondence.seat_nm is not None
    ]
    if not bounded_nm:
        return Nanometre(0)
    return Nanometre(min(bounded_nm))


def _where(placement: Placement) -> str:
    """One placement named by its transform, which no later stage renumbers.

    Not by rank: ``Clashes`` re-ranks every placement once its clashes are
    known, so a finding written here that cited a rank would be describing
    a different seating by the time anybody read it.
    """
    return (
        f"at x {format_nm(placement.x_nm)} y {format_nm(placement.y_nm)} mm, "
        f"theta {placement.theta_deg:.3f} deg"
    )


def _unmet(placement: Placement, depth_nm: Nanometre) -> tuple[str, ...]:
    """The pairings a board resting at ``depth_nm`` does not reach at all.

    Not simply "less inserted than intended", which a board stopped short
    makes true of every pairing it has and so says nothing. A pairing is
    unmet when its part no longer reaches the drilled plate: a part's tip
    stands ``insertion - seat`` above the board's own origin plane, so at
    depth ``d`` it reaches ``d + tip``, and a control that does not reach
    the face is not through its hole. A pairing whose part the hole admits
    entirely records neither depth and so states no tip to reduce.
    """
    return tuple(
        sorted(
            pairing.designator
            for pairing in placement.correspondence
            if pairing.insertion_nm is not None
            and pairing.seat_nm is not None
            and depth_nm + (pairing.insertion_nm - pairing.seat_nm) < 0
        )
    )


def _seated_short(
    ordinal: int, placement: Placement, found: Insertion, depth_nm: Nanometre
) -> Diagnostic:
    """``seated-short``: the enclosure arrested this board before its holes did."""
    short_nm = Nanometre(placement.z_nm - depth_nm)
    unmet = _unmet(placement, depth_nm)
    return Diagnostic.warning(
        "seated-short",
        f"board {ordinal} {_where(placement)}: {found.obstruction} stops it at "
        f"{format_nm(depth_nm)} mm, {format_nm(short_nm)} mm short of the "
        f"{format_nm(placement.z_nm)} mm its holes fix"
        + (f", so {', '.join(unmet)} do not seat" if unmet else ""),
        data=(
            ("board", ordinal),
            ("depth_nm", int(depth_nm)),
            ("shortfall_nm", int(short_nm)),
            ("part", found.part or ""),
            ("with", found.obstruction or ""),
            ("unmet", unmet),
        ),
    )


def _cannot_enter(ordinal: int, placement: Placement, found: Insertion) -> Diagnostic:
    """``cannot-enter``: no travel is defined, which is not a travel of zero."""
    return Diagnostic.error(
        "cannot-enter",
        f"board {ordinal} {_where(placement)}: {found.obstruction} is in the way at "
        f"the entry pose, so this board does not go into the enclosure at all",
        data=(
            ("board", ordinal),
            ("part", found.part or ""),
            ("with", found.obstruction or ""),
        ),
    )


def _too_shallow(
    ordinal: int, placement: Placement, found: Insertion, reach_nm: Nanometre
) -> Diagnostic:
    """``enclosure-too-shallow``: what closes over the cavity will not close."""
    return Diagnostic.warning(
        "enclosure-too-shallow",
        f"board {ordinal} {_where(placement)} reaches {format_nm(reach_nm)} mm into "
        f"{found.lid_solid}: the case will not close over this design",
        data=(
            ("board", ordinal),
            ("reach_nm", int(reach_nm)),
            ("with", found.lid_solid or ""),
        ),
    )


def _findings(ordinal: int, placement: Placement, found: Insertion) -> list[Diagnostic]:
    """Everything one placement's insertion is worth saying, worst first.

    ``seated-short`` needs a shortfall and not merely an obstruction: the
    enclosure arrests nearly every real board, frequently *beyond* the seat
    its own profile predicted, and a finding raised on contact alone would
    report a shortfall of less than nothing.
    """
    reported: list[Diagnostic] = []
    if found.depth_nm is None:
        reported.append(_cannot_enter(ordinal, placement, found))
    elif found.arrested and found.depth_nm < placement.z_nm:
        reported.append(_seated_short(ordinal, placement, found, found.depth_nm))
    if found.lid_nm is not None:
        reported.append(_too_shallow(ordinal, placement, found, found.lid_nm))
    return reported


class Seat:
    """Fills each placement's ``z_nm`` and assigns rank, per board.

    Satisfies ``stompmodel.protocols.Stage[DockData]``. With no cavity
    supplied it reads only ``DockData.placements``; with one it reads
    ``.boards`` as well, for the geometry a path is walked with. Either
    way it neither depends on nor asserts that any other stage ran first.
    Each board is ranked against the case alone -- ranking does not compare
    across boards. Recording this stage's own ``describe()`` into a
    document's processing history is ``Pipeline.run``'s job, not
    ``apply``'s -- a stage records nothing about itself.
    """

    name: ClassVar[str] = "seat"

    def __init__(self, cavity: Cavity | None = None) -> None:
        self._cavity = cavity

    def describe(self) -> StageRun:
        """Report the configuration this stage ran with.

        Parameterless without a cavity, because there was no search: a
        stage records what it did, and two pitches nothing was sampled at
        would read as a search that happened.
        """
        if self._cavity is None:
            return StageRun(self.name)
        return StageRun(self.name, self._cavity.parameters())

    def apply(self, data: DockData) -> DockData:
        boards = {board.ordinal: board for board in data.boards}
        basis = data.case.frame.basis
        placements: dict[int, tuple[Placement, ...]] = {}
        diagnostics: list[Diagnostic] = []
        for ordinal in sorted(data.placements):
            seated = [
                self._seat(ordinal, boards.get(ordinal), placement, basis, diagnostics)
                for placement in data.placements[ordinal]
            ]
            ranked = sorted(seated, key=rank_key)
            placements[ordinal] = tuple(
                replace(placement, rank=index)
                for index, placement in enumerate(ranked, start=1)
            )
        return replace(data, placements=placements).with_diagnostics(*diagnostics)

    def _seat(
        self,
        ordinal: int,
        board: Board | None,
        placement: Placement,
        basis: CoordinateFrame,
        diagnostics: list[Diagnostic],
    ) -> Placement:
        """One placement brought to rest, and what the enclosure did to it.

        A board this stage was handed no geometry for keeps the depth its
        holes fix: the pipeline supplies both together, and ``Clashes``
        refuses the same gap outright rather than checking half an
        assembly.
        """
        at_holes = replace(placement, z_nm=_seated_z_nm(placement))
        if self._cavity is None or board is None:
            return at_holes
        found = self._cavity.insertion(board, at_holes, basis)
        diagnostics.extend(_findings(ordinal, at_holes, found))
        if found.depth_nm is None:
            # No travel exists, so none is recorded: the depth stays the one
            # the holes fix, and the error withholds every artefact anyway.
            return at_holes
        return replace(at_holes, z_nm=found.depth_nm)

