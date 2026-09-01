"""The tar build, as two test modules read it: its panel, its holes, its boards.

Uncollected: this is the setup ``test_registration`` and ``test_seating``
share, held once so that the panel two suites reason about is one panel.
The board geometry comes from the committed fixture through the real path
-- ``substrates``, ``group``, the board reader and ``canonicalise`` -- never
from values hand-written in the answer's own coordinates, which is how the
registration defect survived a careful suite once already.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from stompcollider.boards import group, substrates
from stompcollider.canonicalise import canonicalise
from stompcollider.cli import admit
from stompcollider.designators import parse_filter
from stompcollider.model import Board, DockData, Placement, admitting_radius
from stompcollider.raw import RawBoards
from stompcollider.sources.step import _board
from stompgeom.step import StepDocument, read_step
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, Hole
from stompmodel.units import Nanometre, nm_from_mm

__all__ = [
    "FIXTURE",
    "TOLERANCE",
    "PANEL_REFERENCE",
    "ADMITTED",
    "RV_CORRESPONDENCE",
    "SW_CORRESPONDENCE",
    "RV_SEATING",
    "SW_SEATING",
    "THETA_DEG",
    "holes",
    "case",
    "read",
    "dock",
    "carrying",
    "seating",
]

FIXTURE = Path(__file__).parent / "fixtures" / "tar-pcb.stp"

#: Half the 250000 nm pitch the tar panel's drill document records, which is
#: the recognition tolerance the command line derives for such a document.
TOLERANCE = Nanometre(125_000)

#: The panel references of the tar build: both pot columns, both switches and
#: the two indicator diodes, with the fifth pot deliberately struck out so a
#: negation is exercised beside the glob and the range.
PANEL_REFERENCE = "RV*,SW*,D(3..4),!RV5"

#: Every designator the expression above admits, and no other.
ADMITTED = frozenset({"RV1", "RV2", "RV3", "RV4", "SW1", "SW2", "D3", "D4"})

#: The tar panel's holes as its drill document states them: ``(index, x_mm,
#: y_mm, diameter_mm)``. Stored out of index order on purpose -- the fixture
#: rule -- so nothing here can pass by reading a tuple position for a drill
#: number.
_HOLES: tuple[tuple[int, float, float, float], ...] = (
    (8, -35.0, -18.75, 12.0),
    (3, -40.0, 18.0, 7.0),
    (1, -19.0, -18.75, 5.0),
    (6, 20.0, 18.0, 7.0),
    (2, 19.0, -18.75, 5.0),
    (9, 35.0, -18.75, 12.0),
    (4, -20.0, 18.0, 7.0),
    (7, 40.0, 18.0, 7.0),
    (5, 0.0, 18.0, 7.0),
)

#: What each board must come to rest as: the correspondences it owns, and the
#: seating in panel millimetres and degrees that carries its parts there.
RV_CORRESPONDENCE = frozenset({("RV1", 7), ("RV2", 6), ("RV3", 5), ("RV4", 3)})
SW_CORRESPONDENCE = frozenset({("SW1", 9), ("SW2", 8)})
RV_SEATING = (Nanometre(0), Nanometre(-10_250_000))
SW_SEATING = (Nanometre(0), Nanometre(10_250_000))
THETA_DEG = 90.0


def holes() -> tuple[Hole, ...]:
    """The panel's drilled holes, each carrying the number it was drilled as."""
    return tuple(
        Hole.from_measurement(
            nm_from_mm(x_mm), nm_from_mm(y_mm), nm_from_mm(diameter_mm)
        ).with_number(index)
        for index, x_mm, y_mm, diameter_mm in _HOLES
    )


def case() -> CaseRegistration:
    """The 1590B box face the tar panel was cut in, as its document records it."""
    return CaseRegistration(
        "1590B",
        CaseFace.BOX,
        "1590B.stp",
        FaceFrame(
            CoordinateFrame(
                origin_nm=(Nanometre(0), Nanometre(-25_000_000), Nanometre(0)),
                u=(1.0, 0.0, 0.0),
                v=(0.0, 0.0, 1.0),
                w=(0.0, -1.0, 0.0),
            )
        ),
    )


def read() -> StepDocument:
    """The committed board fixture, read once."""
    return read_step(FIXTURE)


def dock(document: StepDocument) -> DockData:
    """The fixture grouped, measured and canonicalised, then filtered.

    The reader is reached as ``sources.step._board`` rather than through
    ``BoardSource`` so that neither a drill document nor a case model has to
    be fabricated on disk to exercise the path a real run takes.
    """
    probes = tuple(
        sorted({admitting_radius(hole.diameter_nm) for hole in holes()})
    )
    boards = tuple(
        _board(substrate, parts, FIXTURE, probes)
        for substrate, parts in group(document, substrates(document))
    )
    data = canonicalise(RawBoards(boards=boards), case())
    return admit(replace(data, holes=holes()), parse_filter(PANEL_REFERENCE))


def carrying(boards: tuple[Board, ...], designator: str) -> Board:
    """The one board carrying ``designator``, identified by nothing else.

    Never by ordinal: which board is numbered first is a separate rule with
    its own tests, and reading it here would couple these suites to it.
    """
    found = [board for board in boards if designator in board.designators]
    assert len(found) == 1, f"expected exactly one board carrying {designator}"
    return found[0]


def seating(
    data: DockData, board: Board, expected: frozenset[tuple[str, int]]
) -> Placement:
    """The one returned seating carrying ``expected``, out of exactly two.

    Two is the answer, not one: each of these boards is carried onto its own
    holes by a second rigid motion as well -- a half turn about the pair the
    registration anchors on -- and both recognise as many parts as the other.
    Handing back one silently is how a pedal gets assembled mirror-imaged, so
    ``Match`` returns both and this reads the one it can name.
    """
    placements = data.placements.get(board.ordinal, ())
    assert len(placements) == 2, (
        f"board {board.ordinal} has {len(placements)} placements, not two: "
        f"{[d.code for d in data.diagnostics]}"
    )
    found = [
        placement
        for placement in placements
        if {(c.designator, c.hole_index) for c in placement.correspondence} == expected
    ]
    assert len(found) == 1, f"board {board.ordinal} does not seat as {sorted(expected)}"
    return found[0]
