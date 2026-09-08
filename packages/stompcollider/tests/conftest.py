"""The ``--boards`` flag, and the marker it enables.

Modelled on ``stompdrill``'s ``--hammond``: a kernel-backed test that reads
the committed board fixture is opt-in, so a standard run stays quick. It is
not a kernel *availability* switch -- ``stompgeom`` is an unconditional
dependency, so a missing kernel is a failure here, never a silent pass.
"""

from __future__ import annotations

import pytest

from stompcollider.insert import Insertion
from stompmodel.progress import NO_PROGRESS, Scope
from stompmodel.units import Nanometre

__all__: list[str] = []


def pytest_addoption(parser) -> None:
    """Add --boards, which enables tests that read the STEP board fixture."""
    parser.addoption(
        "--boards",
        action="store_true",
        default=False,
        help="run tests that read the committed STEP board fixture through the kernel",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "boards: reads the STEP board fixture; run with --boards"
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Skip boards-marked tests unless --boards was given.

    Deliberately not an ``addopts`` deselection: this repository's documented
    commands pass ``-o addopts=``, which would blank one and silently
    re-enable every one of these.
    """
    if config.getoption("--boards"):
        return
    skip = pytest.mark.skip(reason="reads the STEP board fixture; run: pytest --boards")
    for item in items:
        if "boards" in item.keywords:
            item.add_marker(skip)


class _Stopping:
    """A cavity that answers one fixed insertion, whatever it is asked.

    Shared between ``test_seat.py``, which drives it through most of
    ``Seat``'s ranking rules, and ``test_progress_tree.py``, which uses it
    as the cheapest possible search: it never touches the ``scope`` it is
    handed, so a placement closing at 1.0 around it proves the parent's own
    advance, not anything this double does.
    """

    def __init__(self, found: Insertion) -> None:
        self.found = found
        self.asked: list[tuple[int, Nanometre]] = []

    def insertion(
        self, board, placement, basis, scope: Scope = NO_PROGRESS
    ) -> Insertion:
        self.asked.append((board.ordinal, placement.z_nm))
        return self.found

    def parameters(self) -> tuple[tuple[str, int], ...]:
        return (("seat_pitch_max_nm", 2_000_000), ("seat_pitch_min_nm", 50_000))


@pytest.fixture(scope="session")
def tar_document():
    """The committed board fixture, read once for every suite that reads it.

    Session-scoped because two modules measure the same boards and the file
    is nine megabytes: reading it per module would be the same answer paid
    for twice. Deferred inside the fixture so a run without ``--boards``
    neither reads the file nor imports the kernel to do it.
    """
    from tests import tar

    return tar.read()


@pytest.fixture(scope="session")
def tar_dock(tar_document):
    """That fixture measured and canonicalised, filtered to its panel references."""
    from tests import tar

    return tar.dock(tar_document)


@pytest.fixture(scope="session")
def tar_matched(tar_dock):
    """``tar_dock`` after ``Match``: every board carries its own placements."""
    from stompcollider.match import Match
    from tests import tar

    return Match(tar.TOLERANCE).apply(tar_dock)


def _tar_wall():
    """The synthetic plate standing in for the case model this fixture has none of.

    Wide enough to span the whole panel and thick enough that every board's
    insertion search meets it partway through its travel, the same way
    ``test_insert.py``'s synthetic shells stand in for a case file.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    from stompgeom.step import StepSolid

    wall = BRepPrimAPI_MakeBox(gp_Pnt(-80.0, -15.0, -50.0), 160.0, 30.0, 100.0).Shape()
    return StepSolid("WALL", wall)


def _tar_board_solids(tar_document, tar_dock):
    """Each board's real geometry, grouped as ``BoardSource.scan`` groups it
    and matched to a canonical ``Board`` by the designators the two share."""
    from stompcollider.boards import group, substrates
    from stompgeom.step import StepSolid

    board_solids: dict[int, tuple[StepSolid, ...]] = {}
    for substrate, parts in group(tar_document, substrates(tar_document)):
        names = {part.name for part in parts}
        for board in tar_dock.boards:
            if names & set(board.designators):
                board_solids[board.ordinal] = (substrate, *parts)
                break
    return board_solids


@pytest.fixture(scope="session")
def tar_cavity(tar_document, tar_dock):
    """A ``CaseCavity`` over the fixture's own board solids and a stand-in wall.

    No case model is committed beside this fixture, so this is the one
    plate ``_tar_wall`` builds.
    """
    from stompcollider.insert import CaseCavity
    from stompmodel.units import nm_from_mm

    board_solids = _tar_board_solids(tar_document, tar_dock)
    return CaseCavity((_tar_wall(),), board_solids, nm_from_mm(2.0), nm_from_mm(0.05))


@pytest.fixture(scope="session")
def tar_solids(tar_document, tar_dock):
    """The case solids and board solids ``Clashes`` reads, over the same wall
    and the same real board geometry ``tar_cavity`` seats boards against."""
    return (_tar_wall(),), _tar_board_solids(tar_document, tar_dock)


@pytest.fixture(scope="session")
def tar_seated(tar_dock, tar_cavity):
    """``tar_dock`` matched and seated through the real insertion search."""
    from stompcollider.match import Match
    from stompcollider.seat import Seat
    from tests import tar

    return Seat(tar_cavity).apply(Match(tar.TOLERANCE).apply(tar_dock))
