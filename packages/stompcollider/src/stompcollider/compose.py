"""Dock composition: registration, canonicalisation and pipeline assembly.

Moved out of ``cli.py`` so a library caller -- ``stompcad``'s headless
orchestrator among them -- can drive every phase without importing an
argparse module. ``registration``, ``docked`` and ``derived_tolerance``
lost the leading underscore that marked them CLI-private; nothing else
about their behaviour changed. See ADR-0009 and CLAUDE.md's purpose note.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from stompgeom.step import StepSolid
from stompmodel.diagnostics import Diagnostic
from stompmodel.model import CaseRegistration, DrillData
from stompmodel.protocols import Pipeline
from stompmodel.units import Nanometre

from .canonicalise import board_order, canonicalise
from .clash import Clashes
from .designators import Filter
from .errors import UsageError
from .insert import CaseCavity
from .match import Match
from .model import DockData
from .seat import Seat
from .sources import BoardGeometry, BoardScan

__all__ = [
    "registration",
    "docked",
    "derived_tolerance",
    "admit",
    "board_geometry",
    "build_pipeline",
]


def registration(scan: BoardScan, path: Path) -> CaseRegistration:
    """The face frame the drill document registered, never a face chosen here.

    A document that registered no case model carries no frame, and
    inventing one would seat every board somewhere plausible and wrong.
    """
    case = scan.drill.case
    if case is None:
        raise UsageError(
            f"{path}: this drill document registers no case model, so it carries no "
            f"face frame to dock against"
        )
    return case


def docked(scan: BoardScan, case: CaseRegistration) -> DockData:
    """Canonicalise the measurements, then give them the document's own holes.

    Every hole arrives numbered or not at all: ``stompmodel``'s codec
    refuses a document holding a hole with no drill number, so nothing is
    re-checked here -- ``DockData`` states the same requirement and would
    have no better answer than the reader's own.
    """
    return replace(canonicalise(scan.raw, case), holes=scan.drill.holes)


def derived_tolerance(data: DrillData, drill: Path) -> Nanometre:
    """Half the grid pitch the drill document records.

    Derived rather than chosen: holes are quantised to that grid, so two
    distinct holes lie at least one pitch apart and any offset under half a
    pitch identifies exactly one. Halving is exact for every pitch
    ``stompdrill`` writes -- a whole number of microns is even in nanometres
    -- and floors otherwise, which narrows recognition rather than inventing
    a pairing. A document recording no usable pitch is a usage failure: a
    guessed tolerance would silently decide which hole belongs to which part.
    """
    grid_nm = data.grid_nm
    if grid_nm is None:
        raise UsageError(
            f"{drill} records no drill grid pitch, so the recognition tolerance "
            f"cannot be derived from it: pass --match-tolerance MM"
        )
    return Nanometre(grid_nm // 2)


def admit(data: DockData, panel_reference: Filter) -> DockData:
    """Withhold the protrusion of every component the filter does not admit.

    Withheld rather than dropped: a part the expression passes over is
    still the board's, still named in the report and still a solid the
    clash check must place. ``admitted`` is cleared beside it so ``Match``
    can tell such a part from one it kept that yielded no cylinder: only
    the second is ``unmatched-part``. A board the expression admits nothing
    of earns ``empty-group`` -- a flag that does not fit this board, which
    is a finding and not a parse failure.
    """
    admitted = panel_reference.admit(
        designator for board in data.boards for designator in board.designators
    )
    boards = []
    diagnostics = []
    for board in data.boards:
        boards.append(
            replace(
                board,
                components=tuple(
                    component
                    if component.designator in admitted
                    else replace(component, protrusion=None, admitted=False)
                    for component in board.components
                ),
            )
        )
        if not admitted.intersection(board.designators):
            diagnostics.append(
                Diagnostic.error(
                    "empty-group",
                    f"board {board.ordinal}: the panel-reference expression admits none "
                    f"of its designators",
                    data=(("board", board.ordinal),),
                )
            )
    return replace(data, boards=tuple(boards)).with_diagnostics(*diagnostics)


def board_geometry(scan: BoardScan, case: CaseRegistration) -> dict[int, BoardGeometry]:
    """Each board's ordinal paired with the solids that board was measured from.

    The ordinal comes from ``canonicalise``'s own ordering rule, read
    through :func:`~stompcollider.canonicalise.board_order` rather than
    restated: a second statement of it here would pair a board with another
    board's geometry the day either copy changed.
    """
    order = board_order(scan.raw.boards, case.frame.basis)
    return {ordinal: scan.geometry[index] for ordinal, index in enumerate(order, start=1)}


def build_pipeline(
    tolerance_nm: Nanometre,
    case_solids: Sequence[StepSolid],
    board_solids: dict[int, tuple[StepSolid, ...]],
    pitch_max_nm: Nanometre,
    pitch_min_nm: Nanometre,
) -> Pipeline[DockData]:
    """Match, then seat, then clashes: the one statement of this order.

    Matching decides which face points at the panel and which holes each
    protrusion pairs with; seating reduces those correspondences to a depth
    and then walks the enclosure to see whether the board really gets
    there; clashes need a seated placement to check. No stage asserts that
    another ran, which is why the order lives here and not in a stage.
    """
    cavity = CaseCavity(case_solids, board_solids, pitch_max_nm, pitch_min_nm)
    return Pipeline(
        [
            Match(tolerance_nm),
            Seat(cavity),
            Clashes(case_solids, board_solids),
        ]
    )
