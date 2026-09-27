"""Telling a wall from the floor, and from a rib.

Synthetic levels where the rule is the subject and kernel-built solids where
the geometry is: a hand-built ``Level`` can state an angle no casting has,
which is the only way to reach the boundary the definition draws.
"""

from __future__ import annotations

import math

import pytest

from stompdrill.cad.walls import (
    LATERAL_LIMIT,
    draft_degrees,
    is_lateral,
    nearest_axis,
)
from stompdrill.errors import StompdrillError
from stompgeom.levels import Level
from stompmodel.units import Nanometre

__all__: list[str] = []

_Y = (0.0, 1.0, 0.0)


def _level(direction: tuple[float, float, float], offset_mm: float = 10.0) -> Level:
    """One level stating a plane, with an area and a face a partition would give it."""
    return Level(
        direction=direction,
        offset_nm=Nanometre(int(offset_mm * 1_000_000)),
        area_mm2=100.0,
        faces=(object(),),
    )


def test_a_plane_perpendicular_to_the_drill_axis_is_drafted_by_nothing() -> None:
    assert draft_degrees((0.0, 0.0, 1.0), _Y) == pytest.approx(0.0)


def test_a_plane_normal_to_the_footprint_is_at_a_right_angle_to_it() -> None:
    assert draft_degrees(_Y, _Y) == pytest.approx(90.0)


def test_a_drafted_wall_measures_its_own_draft() -> None:
    """1590B's own figure, stated as a direction rather than read off a model."""
    tilt = math.radians(1.25)
    assert draft_degrees((0.0, -math.sin(tilt), -math.cos(tilt)), _Y) == pytest.approx(1.25)


def test_the_two_populations_are_lateral_and_axial_and_nothing_else() -> None:
    for degrees in (0.0, 1.15, 2.5, 44.999):
        tilt = math.radians(degrees)
        assert is_lateral(_level((0.0, math.sin(tilt), math.cos(tilt))), _Y) is True
    for degrees in (45.001, 60.0, 90.0):
        tilt = math.radians(degrees)
        assert is_lateral(_level((0.0, math.sin(tilt), math.cos(tilt))), _Y) is False


def test_the_boundary_is_where_the_two_meanings_meet_and_not_a_tuned_figure() -> None:
    assert LATERAL_LIMIT == pytest.approx(math.sin(math.radians(45.0)))


def test_a_direction_leans_on_the_axis_it_leans_on_most_with_its_own_sign() -> None:
    assert nearest_axis((0.0, -0.0218, -0.9998)) == (0.0, 0.0, -1.0)
    assert nearest_axis((0.9998, -0.0218, 0.0)) == (1.0, 0.0, 0.0)
    assert nearest_axis((-0.9998, 0.0218, 0.0)) == (-1.0, 0.0, 0.0)


def test_an_exact_tie_between_two_axes_breaks_on_the_lower_index() -> None:
    """Arbitrary but total: a level at exactly 45 degrees in plan has no lean."""
    root = 1.0 / math.sqrt(2.0)
    assert nearest_axis((root, 0.0, root)) == (1.0, 0.0, 0.0)


def test_a_direction_leaning_on_the_drill_axis_is_refused() -> None:
    """Ruling 8: a lateral level's own filter should already keep it off the
    drill axis, so landing there anyway is a construction failure to raise,
    not a wall grouping to make silently."""
    with pytest.raises(StompdrillError):
        nearest_axis((0.01, 0.01, 0.9999), (0.0, 0.0, 1.0))


def _grouped(levels_: list[Level], axis: int) -> object:
    """Drive the grouping without a solid, so a synthetic level can reach it."""
    from stompdrill.cad.walls import _grouped_by_axis

    return _grouped_by_axis(levels_, axis)


def test_a_lateral_level_leaning_on_the_drill_axis_is_refused_and_not_grouped() -> None:
    """Ruling 8: lateral by the definition, yet it would bin to the axis itself.

    Unreachable on every catalogued model -- nothing measures between 2.500°
    and 90.000° -- and here so a custom model cannot pass through it unseen.
    """
    root = 0.6
    rest = math.sqrt((1.0 - root * root) / 2.0)
    with pytest.raises(StompdrillError, match="leans on the drill axis"):
        _grouped([_level((rest, root, rest))], axis=1)


def test_four_groups_or_it_is_not_an_enclosure_this_drills() -> None:
    with pytest.raises(StompdrillError, match="four walls"):
        _grouped([_level((0.0, 0.0, 1.0)), _level((0.0, 0.0, -1.0))], axis=1)
