"""Construction guards on the raw, float-millimetre value objects.

Each clause below is exercised on its own, per the repository's rule that a
compound condition earns one test per clause -- a shared test could pass
with half the guard deleted.
"""

from __future__ import annotations

import pytest

from stompcollider.raw import RawBoard, RawBoards, RawComponent, RawCylinder

_CYLINDER = RawCylinder(radius_mm=1.0, depth_from_tip_min_mm=0.0, depth_from_tip_max_mm=1.0)


def test_a_component_needs_a_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        RawComponent(designator="", axis_xy_mm=None)


def test_a_component_with_no_axis_cannot_carry_a_stack() -> None:
    with pytest.raises(ValueError, match="no axis can carry no"):
        RawComponent(designator="R1", axis_xy_mm=None, stack=(_CYLINDER,))


def test_a_component_with_an_axis_needs_at_least_one_cylinder() -> None:
    with pytest.raises(ValueError, match="at least one cylinder"):
        RawComponent(designator="R1", axis_xy_mm=(1.0, 1.0), stack=())


def test_a_component_axis_must_be_finite_millimetres() -> None:
    with pytest.raises(TypeError):
        RawComponent(designator="R1", axis_xy_mm=(1, 1.0), stack=(_CYLINDER,))


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
