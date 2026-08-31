"""``Seat``: how far a board travels along the face normal, and rank order.

Seating depth is fixed by the panel-reference correspondences alone -- a
closed-form reduction over what ``Match`` already found, with no kernel
query and no descent. Anything else that would foul at that depth is a
clash for a later stage to report, never a constraint this stage yields to.
Ranking is a reported field over the whole six-element key, not a filter:
every placement Seat is handed comes back. See "Seating depth" and
"Ranking" in ``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from stompmodel.model import StageRun
from stompmodel.units import Nanometre

from .model import DockData, Placement

__all__ = ["Seat", "rank_key"]


def rank_key(placement: Placement) -> tuple[int, int, int, float, int, int]:
    """The spec's lexicographic key, whole, from the first version.

    Six-wide whether or not any clash has been found, so that the clash
    stage feeds this comparator rather than replacing one: a placement with
    no clashes scores zero on the first three elements and orders on
    ``(theta_deg, x_nm, y_nm)`` alone.
    """
    return (
        len(placement.clashes),
        sum(clash.volume_nm3 for clash in placement.clashes),
        max((int(clash.depth_nm) for clash in placement.clashes), default=0),
        placement.theta_deg,
        int(placement.x_nm),
        int(placement.y_nm),
    )


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


class Seat:
    """Fills each placement's ``z_nm`` and assigns rank, per board.

    Satisfies ``stompmodel.protocols.Stage[DockData]``. Reads only
    ``DockData.placements``, so it neither depends on nor asserts that any
    other stage ran first. Each board is ranked against the case alone --
    ranking does not compare across boards. Recording this stage's own
    ``describe()`` into a document's processing history is ``Pipeline.run``'s
    job, not ``apply``'s -- a stage records nothing about itself.
    """

    name: ClassVar[str] = "seat"

    def describe(self) -> StageRun:
        """Report the (parameterless) configuration this stage ran with."""
        return StageRun(self.name)

    def apply(self, data: DockData) -> DockData:
        placements: dict[int, tuple[Placement, ...]] = {}
        for ordinal, board_placements in data.placements.items():
            seated = (
                replace(placement, z_nm=_seated_z_nm(placement))
                for placement in board_placements
            )
            ranked = sorted(seated, key=rank_key)
            placements[ordinal] = tuple(
                replace(placement, rank=index)
                for index, placement in enumerate(ranked, start=1)
            )
        return replace(data, placements=placements)
