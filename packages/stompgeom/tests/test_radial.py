"""``radial_reach`` and ``axial_extent``: measuring a solid about an axis.

Shapes are built here rather than read from a file: the rule under test is
about geometry, not about STEP, and a hand-built stepped shaft states the
one case a hole cares about -- where material too wide to pass begins.
"""

from __future__ import annotations

import math

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from stompgeom.radial import axial_extent, radial_reach

__all__: list[str] = []

#: The axis every fixture below stands on: the model origin, pointing +Z.
_ORIGIN = (0.0, 0.0, 0.0)
_UP = (0.0, 0.0, 1.0)
_DOWN = (0.0, 0.0, -1.0)


def _cylinder(radius: float, low: float, high: float):
    """A cylinder of ``radius`` spanning ``low``..``high`` on the Z axis."""
    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(0.0, 0.0, low), gp_Dir(0.0, 0.0, 1.0)), radius, high - low
    ).Shape()


def _shaft():
    """A flange of radius 6 up to z=5, then a shaft of radius 3 up to z=15."""
    return BRepAlgoAPI_Fuse(_cylinder(6.0, 0.0, 5.0), _cylinder(3.0, 5.0, 15.0)).Shape()


def test_axial_extent_measures_along_the_direction_it_is_given() -> None:
    """Least first, and the same solid read the other way is the negation."""
    shaft = _shaft()

    assert axial_extent(shaft, _UP) == pytest.approx((0.0, 15.0), abs=1e-6)
    assert axial_extent(shaft, _DOWN) == pytest.approx((-15.0, 0.0), abs=1e-6)


def test_the_reach_outside_a_radius_is_where_the_wider_feature_ends() -> None:
    """A radius the shaft clears reaches to the flange, not to the shaft's tip."""
    shaft = _shaft()

    assert radial_reach(shaft, _ORIGIN, _UP, 3.5) == pytest.approx(5.0, abs=1e-6)
    assert radial_reach(shaft, _ORIGIN, _UP, 5.9) == pytest.approx(5.0, abs=1e-6)


def test_material_narrower_than_the_radius_reaches_nothing_at_all() -> None:
    """``None`` is the whole part passing, not a measurement that failed."""
    assert radial_reach(_shaft(), _ORIGIN, _UP, 6.5) is None


def test_a_radius_the_shaft_exceeds_reaches_the_shaft_s_own_tip() -> None:
    """The reach is the tipmost material, so a thin radius reads the very tip."""
    assert radial_reach(_shaft(), _ORIGIN, _UP, 2.0) == pytest.approx(15.0, abs=1e-6)


def test_material_exactly_at_the_radius_does_not_count_as_outside_it() -> None:
    """Strictness, which is what lets a bush exactly fill its bore and pass.

    The flange measures exactly 6, so a radius of 6 leaves only the shaft,
    which is narrower still: nothing is outside and the answer is ``None``.
    A rule using ``>=`` would report the flange here.
    """
    assert radial_reach(_shaft(), _ORIGIN, _UP, 6.0) is None


def test_the_reach_is_read_along_the_direction_given_not_the_model_z() -> None:
    """Turned round, the flange's far end is what reaches furthest.

    Read upwards the widest material ends at the flange's top, z=5; read
    downwards the same flange's greatest coordinate is its underside, z=0
    measured as 0 along ``-Z``. An implementation reading the model's own
    Z whatever it was asked would answer 5 both times.
    """
    assert radial_reach(_shaft(), _ORIGIN, _DOWN, 3.5) == pytest.approx(0.0, abs=1e-6)


def test_the_axis_is_the_line_asked_about_not_the_model_axis() -> None:
    """A shaft measured about a line beside it is wide everywhere along it.

    The control for every reading above: those all stand the axis through
    the solid's own centre, where an implementation ignoring
    ``axis_location_mm`` entirely would agree with them. Offset by 4 mm the
    radius-6 flange still reaches 5, but so does the radius-3 shaft, so the
    reach at 3.5 is the shaft's tip and no longer the flange's top.
    """
    beside = (4.0, 0.0, 0.0)

    assert radial_reach(_shaft(), beside, _UP, 3.5) == pytest.approx(15.0, abs=1e-6)


def test_a_radius_beyond_the_whole_solid_is_answered_without_a_boolean() -> None:
    """The short-circuit is an answer, not a shortcut: it must agree with one.

    A box reaches further along its diagonal than any radius about its
    centre line, so the bound is loose; the answer it gives has to be the
    answer the cut gives, and a radius comfortably outside both is where
    the two are compared.
    """
    box = BRepPrimAPI_MakeBox(gp_Pnt(-2.0, -2.0, 0.0), gp_Pnt(2.0, 2.0, 6.0)).Shape()
    diagonal = math.hypot(2.0, 2.0)

    assert radial_reach(box, _ORIGIN, _UP, diagonal + 1.0) is None
    assert radial_reach(box, _ORIGIN, _UP, diagonal - 0.5) == pytest.approx(
        6.0, abs=1e-6
    )


def test_a_radius_below_zero_is_refused_rather_than_measured() -> None:
    with pytest.raises(ValueError, match="needs a radius"):
        radial_reach(_shaft(), _ORIGIN, _UP, -1.0)
