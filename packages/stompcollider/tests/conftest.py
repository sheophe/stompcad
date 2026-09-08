"""The ``--boards`` flag, and the marker it enables.

Modelled on ``stompdrill``'s ``--hammond``: a kernel-backed test that reads
the committed board fixture is opt-in, so a standard run stays quick. It is
not a kernel *availability* switch -- ``stompgeom`` is an unconditional
dependency, so a missing kernel is a failure here, never a silent pass.
"""

from __future__ import annotations

import pytest

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


@pytest.fixture(scope="session")
def tar_cavity(tar_document, tar_dock):
    """A ``CaseCavity`` over the fixture's own board solids and a stand-in wall.

    No case model is committed beside this fixture, so the enclosure is one
    plate: wide enough to span the whole panel and thick enough that every
    board's insertion search meets it partway through its travel, the same
    way ``test_insert.py``'s synthetic shells stand in for a case file.
    Board solids are the fixture's real geometry, grouped exactly as
    ``BoardSource.scan`` groups them and matched to a canonical ``Board`` by
    the designators the two share.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    from stompcollider.boards import group, substrates
    from stompcollider.insert import CaseCavity
    from stompgeom.step import StepSolid
    from stompmodel.units import nm_from_mm

    board_solids: dict[int, tuple[StepSolid, ...]] = {}
    for substrate, parts in group(tar_document, substrates(tar_document)):
        names = {part.name for part in parts}
        for board in tar_dock.boards:
            if names & set(board.designators):
                board_solids[board.ordinal] = (substrate, *parts)
                break

    wall = BRepPrimAPI_MakeBox(gp_Pnt(-80.0, -15.0, -50.0), 160.0, 30.0, 100.0).Shape()
    plate = StepSolid("WALL", wall)
    return CaseCavity((plate,), board_solids, nm_from_mm(2.0), nm_from_mm(0.05))
