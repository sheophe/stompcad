"""The profile and the radius a hole admits, read from the package that owns them.

Here rather than only in ``stompcollider``: a value the shared package
publishes is one ``stompdrill`` may import without importing the docking
tool, and a test that only exercised it through its old home would not
notice the day that stopped being true.
"""

from __future__ import annotations

import pytest

from stompmodel.model import Profile, admitting_radius
from stompmodel.units import Nanometre

__all__: list[str] = []


def test_the_radius_a_hole_admits_is_half_its_diameter() -> None:
    assert admitting_radius(Nanometre(12_000_000)) == 6_000_000


def test_an_odd_diameter_floors_rather_than_admitting_a_part_too_wide() -> None:
    assert admitting_radius(Nanometre(12_000_001)) == 6_000_000


def test_a_hole_with_no_diameter_admits_nothing_and_says_so() -> None:
    with pytest.raises(ValueError, match="positive diameter"):
        admitting_radius(Nanometre(0))


def test_the_widest_step_covering_a_depth_is_what_a_hole_must_admit() -> None:
    """Overlapping steps are the point: the widest at a depth governs there."""
    profile = Profile(
        steps=(
            (Nanometre(2_000_000), Nanometre(0), Nanometre(10_000_000)),
            (Nanometre(5_000_000), Nanometre(3_000_000), Nanometre(4_000_000)),
        )
    )
    assert profile.radius_at(Nanometre(1_000_000)) == 2_000_000
    assert profile.radius_at(Nanometre(3_500_000)) == 5_000_000
    assert profile.radius_at(Nanometre(20_000_000)) == 0


def test_a_profile_needs_a_step_because_a_part_with_no_axis_has_no_profile() -> None:
    with pytest.raises(ValueError, match="at least one step"):
        Profile(steps=())


def test_the_docking_tool_still_publishes_the_same_two_objects() -> None:
    """Re-exported, not copied: two implementations could disagree."""
    from stompcollider import model as dock

    assert dock.Profile is Profile
    assert dock.admitting_radius is admitting_radius
