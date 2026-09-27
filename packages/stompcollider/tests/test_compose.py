"""Tests for reaching the dock composition phases without the CLI."""

from __future__ import annotations

from stompcollider.compose import admit_walls
from stompcollider.designators import NOTHING, parse_filter
from stompcollider.model import Board, Component, DockData
from stompmodel.diagnostics import Severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration
from stompmodel.units import Nanometre


def test_the_dock_composes_without_the_cli() -> None:
    """Every phase stompcad drives is reachable from the package, not argparse."""
    import stompcollider

    for name in (
        "registration", "docked", "derived_tolerance", "admit",
        "board_geometry", "build_pipeline", "parse_filter",
    ):
        assert hasattr(stompcollider, name), name
        assert name in stompcollider.__all__, name


# --------------------------------------------------------------------------
# admit_walls: which expression claims which designator.
# --------------------------------------------------------------------------


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _case() -> CaseRegistration:
    return CaseRegistration("1590B", CaseFace.BOX, "case.stp", FaceFrame(_identity_frame()))


def _dock_data_with(designators: tuple[str, ...]) -> DockData:
    """One board carrying these designators, and nothing a filter cannot read.

    Values rather than a board file: what is under test is which expression
    claims which designator, and a real board would settle that with its own
    geometry instead. Components are stored **reversed** per the fixture
    rule, so an ordering read off this list rather than sorted fails here.
    """
    components = tuple(
        Component(designator=designator, protrusion=None)
        for designator in reversed(designators)
    )
    board = Board(
        ordinal=1,
        designators=tuple(sorted(designators)),
        extent_nm=(Nanometre(30_000_000), Nanometre(20_000_000), Nanometre(1_600_000)),
        carrier=_identity_frame(),
        components=components,
    )
    return DockData(case=_case(), boards=(board,))


def test_the_wall_filter_admits_only_what_it_names() -> None:
    data = _dock_data_with(("J1", "J4", "RV1"))
    found = admit_walls(data, parse_filter("J*"), NOTHING)
    admitted = {c.designator for b in found.boards for c in b.components if c.wall_admitted}
    assert admitted == {"J1", "J4"}


def test_no_wall_filter_admits_nothing_and_raises_nothing() -> None:
    """Decision 11: nothing is cut into a wall unless a builder named the part."""
    data = _dock_data_with(("J1", "RV1"))
    found = admit_walls(data, NOTHING, parse_filter("RV*"))
    assert not any(c.wall_admitted for b in found.boards for c in b.components)
    assert found.diagnostics == data.diagnostics


def test_a_designator_both_filters_claim_is_an_error_naming_both_expressions() -> None:
    """The tool cannot know which hole the part is for, so it refuses to choose."""
    data = _dock_data_with(("J1", "RV1"))
    found = admit_walls(data, parse_filter("J1,RV1"), parse_filter("RV*"))
    claimed = [d for d in found.diagnostics if d.code == "component-claimed-twice"]
    assert len(claimed) == 1
    assert claimed[0].severity is Severity.ERROR
    assert "J1,RV1" in claimed[0].message
    assert "RV*" in claimed[0].message
    assert "RV1" in claimed[0].message


def test_a_designator_only_the_wall_filter_claims_is_no_finding() -> None:
    """The control: the test above must fail on the overlap, not on the wall
    filter naming anything at all."""
    data = _dock_data_with(("J1", "RV1"))
    found = admit_walls(data, parse_filter("J1"), parse_filter("RV*"))
    assert [d.code for d in found.diagnostics] == []


def test_one_finding_per_claimed_designator_and_in_a_fixed_order() -> None:
    """Sorted, because a set's iteration order must reach no artefact (ADR-0006)."""
    data = _dock_data_with(("J1", "J4", "RV1"))
    found = admit_walls(data, parse_filter("*"), parse_filter("*"))
    claimed = [d for d in found.diagnostics if d.code == "component-claimed-twice"]
    assert [d.data for d in claimed] == [
        (("designator", "J1"),), (("designator", "J4"),), (("designator", "RV1"),)
    ]
