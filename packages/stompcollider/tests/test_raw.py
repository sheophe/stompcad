"""Construction guards on the raw, float-millimetre value objects.

Each clause below is exercised on its own, per the repository's rule that a
compound condition earns one test per clause -- a shared test could pass
with half the guard deleted.
"""

from __future__ import annotations

import pytest

from stompcollider.raw import RawBoard, RawBoards, RawComponent, RawCylinder
from stompmodel.diagnostics import Diagnostic

_CYLINDER = RawCylinder(radius_mm=1.0, depth_from_tip_min_mm=0.0, depth_from_tip_max_mm=1.0)


def test_a_component_needs_a_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        RawComponent(designator="", axis_xy_mm=None)


def test_a_component_with_no_axis_cannot_carry_a_stack() -> None:
    with pytest.raises(ValueError, match="no axis can carry no"):
        RawComponent(designator="R1", axis_xy_mm=None, stack=(_CYLINDER,))


def test_a_component_with_an_axis_needs_at_least_one_cylinder() -> None:
    with pytest.raises(ValueError, match="at least one cylinder"):
        RawComponent(designator="R1", axis_xy_mm=(1.0, 1.0), stack=(), tip_mm=1.0)


def test_a_component_axis_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawComponent(designator="R1", axis_xy_mm=(1, 1.0), stack=(_CYLINDER,), tip_mm=1.0)


def test_a_component_with_an_axis_states_the_tip_its_depths_are_measured_from() -> None:
    """Every depth in the stack is measured back from the tip, and a
    placement's travel is that depth less the tip's own stand-off, so a
    protrusion without one is measured against nothing."""
    with pytest.raises(TypeError):
        RawComponent(designator="R1", axis_xy_mm=(1.0, 1.0), stack=(_CYLINDER,))


def test_a_component_with_no_axis_has_no_tip_either() -> None:
    """The other half of the both-or-neither rule: a tip is a position on an
    axis, so a part with no axis stating one would be stating a position on
    a line nobody found."""
    with pytest.raises(ValueError, match="no tip"):
        RawComponent(designator="R1", axis_xy_mm=None, tip_mm=1.0)


def test_a_board_needs_at_least_one_component() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        RawBoard(
            corner_a_mm=(0.0, 0.0, 0.0),
            corner_b_mm=(1.0, 1.0, 1.0),
            carrier_origin_mm=(0.0, 0.0, 0.0),
            carrier_u=(1.0, 0.0, 0.0),
            carrier_v=(0.0, 1.0, 0.0),
            carrier_w=(0.0, 0.0, 1.0),
            components=(),
        )


def test_a_boards_scan_needs_at_least_one_board() -> None:
    with pytest.raises(ValueError, match="at least one board"):
        RawBoards(boards=())


def test_an_error_diagnostic_buys_a_scan_with_no_board() -> None:
    """An unreadable file is a reported finding, not a silently empty result."""
    scan = RawBoards(boards=(), diagnostics=(Diagnostic.error("unreadable-board", "no"),))
    assert scan.boards == ()


def test_a_warning_does_not_buy_a_scan_with_no_board() -> None:
    """The clause tested apart from the one above: warning is not error."""
    with pytest.raises(ValueError, match="at least one board"):
        RawBoards(boards=(), diagnostics=(Diagnostic.warning("multiple-boards", "two"),))


def test_a_cylinder_radius_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawCylinder(radius_mm=1, depth_from_tip_min_mm=0.0, depth_from_tip_max_mm=1.0)


def test_a_cylinder_depth_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawCylinder(radius_mm=1.0, depth_from_tip_min_mm=0, depth_from_tip_max_mm=1.0)


def test_a_board_corner_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawBoard(
            corner_a_mm=(0, 0.0, 0.0),
            corner_b_mm=(1.0, 1.0, 1.0),
            carrier_origin_mm=(0.0, 0.0, 0.0),
            carrier_u=(1.0, 0.0, 0.0),
            carrier_v=(0.0, 1.0, 0.0),
            carrier_w=(0.0, 0.0, 1.0),
            components=(RawComponent(designator="R1", axis_xy_mm=None),),
        )


def test_a_board_carrier_origin_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawBoard(
            corner_a_mm=(0.0, 0.0, 0.0),
            corner_b_mm=(1.0, 1.0, 1.0),
            carrier_origin_mm=(0, 0.0, 0.0),
            carrier_u=(1.0, 0.0, 0.0),
            carrier_v=(0.0, 1.0, 0.0),
            carrier_w=(0.0, 0.0, 1.0),
            components=(RawComponent(designator="R1", axis_xy_mm=None),),
        )
