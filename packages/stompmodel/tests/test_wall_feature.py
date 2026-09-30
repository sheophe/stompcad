"""One seated feature as a ray, in the frame the case's own holes are stated in.

In ``stompmodel`` because ``stompcollider`` writes it and ``stompdrill``
reads it, which is the rule ADR-0009 states for where a value lives.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from stompmodel.model import Profile, WallFeature
from stompmodel.units import Nanometre

__all__: list[str] = []

_PROFILE = Profile(steps=((Nanometre(3_000_000), Nanometre(0), Nanometre(10_000_000)),))


def _a_feature(**changes: object) -> WallFeature:
    base = WallFeature(
        designator="J1",
        board=1,
        origin_nm=(Nanometre(20_000_000), Nanometre(5_000_000), Nanometre(-1_000_000)),
        direction=(1.0, 0.0, 0.0),
        profile=_PROFILE,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_a_feature_names_the_part_it_came_from() -> None:
    with pytest.raises(ValueError, match="designator"):
        _a_feature(designator="")


def test_boards_are_numbered_from_one_here_as_everywhere() -> None:
    with pytest.raises(ValueError, match="numbered from 1"):
        _a_feature(board=0)


def test_the_direction_is_a_unit_vector_because_it_is_a_ray_and_not_a_length() -> None:
    with pytest.raises(ValueError, match="unit length"):
        _a_feature(direction=(1.0, 1.0, 0.0))


def test_an_origin_is_three_whole_nanometre_coordinates() -> None:
    with pytest.raises(TypeError):
        _a_feature(origin_nm=(20_000_000.5, 0, 0))  # type: ignore[arg-type]


def test_a_stated_bore_is_positive_because_it_is_a_radius() -> None:
    with pytest.raises(ValueError, match="positive"):
        _a_feature(bore_nm=Nanometre(0))


def test_a_feature_with_no_bore_says_none_rather_than_zero() -> None:
    assert _a_feature().bore_nm is None


def test_depths_run_back_from_the_origin_which_is_the_tip() -> None:
    """The convention every consumer depends on, asserted rather than assumed."""
    feature = _a_feature()
    assert feature.profile.radius_at(Nanometre(5_000_000)) == 3_000_000
    assert feature.profile.radius_at(Nanometre(20_000_000)) == 0
