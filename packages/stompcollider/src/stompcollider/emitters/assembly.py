"""Serialise ``DockData`` as the assembly model: the case, each board seated.

Satisfies ``stompmodel.protocols.Emitter[DockData]``: ``emit`` returns
bytes and never writes them (ADR-0005). **Collisions are left in place**
-- interference is not resolved away, and seeing the clash is the point.
The XCAF document is assembled by ``stompgeom.build``, never here
(ADR-0008 and ``stompcollider-technical.md``'s "The assembly model"), and
the placement is the one ``clash.placement_transform`` already states, so
the report and the model cannot disagree about where a board went.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from stompgeom.build import PlacedSolid, build_document, solid_colour
from stompgeom.step import StepSolid
from stompgeom.writer import render_step
from stompmodel.errors import EmitterError
from stompmodel.frames import CoordinateFrame
from stompmodel.units import Nanometre, nm_from_mm

from ..clash import board_solid_name, placement_transform, solid_name
from ..model import Board, DockData, Placement

__all__ = ["Solids", "AssemblyEmitter"]

#: Recorded in the header so a reader can tell which release seated the boards.
_VERSION = "0.1.0"

#: Named at the call site, never defaulted inside the shared writer.
_ORIGINATING_SYSTEM = f"stompcollider {_VERSION}"

#: The header name, when a caller states none.
_TITLE = "stompcollider"

#: Used when a caller supplies no source timestamp. Never a clock reading --
#: two runs over one input must agree byte for byte (ADR-0006).
_EPOCH = "1970-01-01T00:00:00+00:00"

#: A shape's bounding box in millimetres, as ``stompgeom`` reports one.
_Box = tuple[float, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class Solids:
    """Solids to write, and the document their colours are read from.

    Not a ``StepDocument``: that value states *every* solid a file holds,
    while a board's solids are the subset grouped onto one substrate.
    ``document`` is the XCAF document those solids were read from, which is
    what ``stompgeom.build.solid_colour`` resolves a colour through.
    """

    document: Any
    solids: Sequence[StepSolid]

    def __post_init__(self) -> None:
        object.__setattr__(self, "solids", tuple(self.solids))
        if not self.solids:
            raise ValueError("a group of solids to write needs at least one solid")


def _ordered(
    solids: Solids, name_of: Callable[[StepSolid, _Box], str]
) -> list[tuple[str, tuple[Nanometre, ...], StepSolid]]:
    """``solids`` named by ``name_of`` and sorted on their own geometry.

    Sorted rather than taken in the order they were supplied: two files
    listing the same solids differently must reach the same bytes, and the
    build order decides the written entity order (ADR-0006). The key is the
    whole bounding box, both corners: two solids can share a name and a
    least corner and differ only in extent, and a three-wide key would let
    those fall back to the order they arrived in. Whole nanometres, so the
    key holds no float.
    """
    entries = []
    for solid in solids.solids:
        box = solid.box_mm
        extent = tuple(nm_from_mm(value) for value in box)
        entries.append((name_of(solid, box), extent, solid))
    return sorted(entries, key=lambda entry: (entry[0], entry[1]))


def _chosen(placements: Sequence[Placement]) -> Placement | None:
    """The seating this board is written at: its rank-1 placement.

    Read by rank, never by tuple position -- a caller's placements need not
    arrive sorted, and the report reads the same field the same way.
    """
    if not placements:
        return None
    return min(placements, key=lambda placement: placement.rank)


class AssemblyEmitter:
    """Emit the case model's solids plus each board's, under its placement."""

    name: ClassVar[str] = "assembly"
    media_type: ClassVar[str] = "model/step"
    extension: ClassVar[str] = ".stp"

    def __init__(
        self,
        case: Solids,
        boards: Mapping[int, Solids],
        *,
        title: str = "",
        timestamp: str = _EPOCH,
    ) -> None:
        self._case = case
        self._boards = dict(boards)
        self._title = title or _TITLE
        self._timestamp = timestamp

    def emit(self, data: DockData) -> bytes:
        """One document from the case and every seated board, rendered to bytes.

        Boards are walked in ordinal order and their solids in geometry
        order, so nothing about the caller's own ordering reaches the bytes.
        """
        basis = data.case.frame.basis
        solids = self._case_solids()
        for board in sorted(data.boards, key=lambda board: board.ordinal):
            placement = _chosen(data.placements.get(board.ordinal, ()))
            if placement is not None:
                solids.extend(self._board_solids(board, placement, basis))
        return render_step(
            build_document(solids),
            title=self._title,
            timestamp=self._timestamp,
            originating_system=_ORIGINATING_SYSTEM,
        )

    def _case_solids(self) -> list[PlacedSolid]:
        """The case, unmoved: ``placement`` is ``None``, never an identity."""
        return [
            PlacedSolid(solid.shape, name, solid_colour(self._case.document, solid), None)
            for name, _extent, solid in _ordered(
                self._case, lambda solid, box: solid_name(solid, box, "case")
            )
        ]

    def _board_solids(
        self, board: Board, placement: Placement, basis: CoordinateFrame
    ) -> list[PlacedSolid]:
        """One board's solids, all of them, under the one motion it seats by.

        Refused rather than skipped when no geometry was supplied for it: a
        board silently left out of the assembly looks exactly like a board
        that is not there, the same reason ``Clashes`` refuses.
        """
        supplied = self._boards.get(board.ordinal)
        if supplied is None:
            raise EmitterError(
                f"board {board.ordinal} is placed but no solids were supplied for it"
            )
        group = f"board:{board.ordinal}"
        motion = placement_transform(board, placement, basis)
        return [
            PlacedSolid(solid.shape, name, solid_colour(supplied.document, solid), motion)
            for name, _extent, solid in _ordered(
                supplied, lambda solid, box: board_solid_name(solid, box, group)
            )
        ]
