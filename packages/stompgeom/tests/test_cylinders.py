"""Every cylindrical face a shape carries, and the tolerances that judge them.

The tolerance tests are written as pairs that straddle the kernel's own
declared figure, so a hand-picked epsilon substituted for either would move
one of the two and fail. See ADR-0008.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from stompgeom.cylinders import Cylinder, cylindrical_faces

# --------------------------------------------------------------------------
# Synthetic shapes. Built through OCP directly because that is what a
# fixture is; the package's own source reaches the kernel through its own
# modules, which ``test_package_boundary.py`` is what enforces.
# --------------------------------------------------------------------------


def _cylinder_shape(
    radius: float,
    height: float,
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    along: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*at), gp_Dir(*along)), radius, height
    ).Shape()


def _box_shape() -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 3.0, 4.0, 5.0).Shape()


def _moved_along_z(shape: Any, by: float) -> Any:
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    motion = gp_Trsf()
    motion.SetTranslation(gp_Vec(0.0, 0.0, by))
    return shape.Moved(TopLoc_Location(motion))


def _a_cylinder(
    location: tuple[float, float, float] = (0.0, 0.0, 0.0),
    direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
    radius: float = 1.0,
    extent: tuple[float, float] = (0.0, 4.0),
) -> Cylinder:
    return Cylinder(
        axis_location_mm=location,
        axis_direction=direction,
        radius_mm=radius,
        extent_mm=extent,
    )


def _ends_along(cylinder: Cylinder, axis: tuple[float, float, float]) -> tuple[float, float]:
    """Where the face's two ends sit along ``axis``, from the reported fields.

    Deliberately recomputed here rather than read off ``extent_mm``: it is
    the absolute position of the two end circles that a caller needs, and
    that is a claim about location and extent together.
    """
    base = sum(a * b for a, b in zip(cylinder.axis_location_mm, axis))
    step = sum(a * b for a, b in zip(cylinder.axis_direction, axis))
    ends = (base + cylinder.extent_mm[0] * step, base + cylinder.extent_mm[1] * step)
    return (min(ends), max(ends))


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------


def test_a_box_has_no_cylindrical_face() -> None:
    """The innocent half of the surface-type filter: a walk that returned
    every face would pass every test below by finding too much."""
    assert cylindrical_faces(_box_shape()) == ()


def test_a_cylinder_reports_its_radius_axis_and_axial_extent() -> None:
    """All four fields, because a reader missing any one of them is exactly
    the helper this module was published to replace."""
    found = cylindrical_faces(_cylinder_shape(3.0, 5.0, at=(1.0, 2.0, 7.0)))

    assert len(found) == 1
    only = found[0]
    assert only.radius_mm == 3.0
    assert only.axis_location_mm == (1.0, 2.0, 7.0)
    assert only.axis_direction == (0.0, 0.0, 1.0)
    assert _ends_along(only, (0.0, 0.0, 1.0)) == (7.0, 12.0)


def test_the_axial_extent_is_the_faces_own_trim() -> None:
    """Two cylinders sharing a location and differing only in height must
    differ in extent, or the extent is not being read at all."""
    short = cylindrical_faces(_cylinder_shape(3.0, 5.0))[0]
    tall = cylindrical_faces(_cylinder_shape(3.0, 11.0))[0]

    assert _ends_along(short, (0.0, 0.0, 1.0)) == (0.0, 5.0)
    assert _ends_along(tall, (0.0, 0.0, 1.0)) == (0.0, 11.0)


def test_a_faces_own_placement_reaches_the_reported_geometry() -> None:
    """A located face carries its surface somewhere else, and the walk must
    report where it actually is -- not where the untransformed surface was."""
    plain = cylindrical_faces(_cylinder_shape(3.0, 5.0, at=(1.0, 2.0, 7.0)))[0]
    moved = cylindrical_faces(
        _moved_along_z(_cylinder_shape(3.0, 5.0, at=(1.0, 2.0, 7.0)), 4.0)
    )[0]

    assert _ends_along(plain, (0.0, 0.0, 1.0)) == (7.0, 12.0)
    assert _ends_along(moved, (0.0, 0.0, 1.0)) == (11.0, 16.0)


def test_a_cylinder_reports_the_direction_it_was_built_along() -> None:
    """A reader that assumed Z would pass every test above."""
    only = cylindrical_faces(_cylinder_shape(2.0, 6.0, along=(0.0, 1.0, 0.0)))[0]

    assert only.axis_direction == (0.0, 1.0, 0.0)
    assert _ends_along(only, (0.0, 1.0, 0.0)) == (0.0, 6.0)


def test_two_cylinders_in_one_shape_are_both_reported() -> None:
    from stompgeom.shapes import compound

    found = cylindrical_faces(
        compound([_cylinder_shape(1.0, 4.0), _cylinder_shape(2.0, 4.0, at=(20.0, 0.0, 0.0))])
    )

    assert sorted(cylinder.radius_mm for cylinder in found) == [1.0, 2.0]


# --------------------------------------------------------------------------
# Validation at construction
# --------------------------------------------------------------------------


def test_a_cylinder_refuses_a_measurement_that_is_not_a_finite_float() -> None:
    with pytest.raises(TypeError):
        _a_cylinder(radius=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _a_cylinder(location=(0.0, 0.0, math.inf))
    with pytest.raises(TypeError):
        _a_cylinder(extent=(0.0, math.nan))


def test_a_cylinder_refuses_a_vector_of_the_wrong_width() -> None:
    with pytest.raises(ValueError, match="three components"):
        _a_cylinder(location=(0.0, 0.0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="three components"):
        _a_cylinder(direction=(0.0, 0.0, 1.0, 0.0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="two components"):
        _a_cylinder(extent=(0.0, 1.0, 2.0))  # type: ignore[arg-type]


def test_a_cylinder_refuses_a_radius_that_is_not_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        _a_cylinder(radius=0.0)
    with pytest.raises(ValueError, match="positive"):
        _a_cylinder(radius=-1.0)


def test_a_cylinder_refuses_an_inverted_extent() -> None:
    with pytest.raises(ValueError, match="extent_mm"):
        _a_cylinder(extent=(4.0, 0.0))


def test_a_cylinder_refuses_a_direction_that_is_not_a_unit_vector() -> None:
    with pytest.raises(ValueError, match="unit length"):
        _a_cylinder(direction=(0.0, 0.0, 2.0))
    with pytest.raises(ValueError, match="unit length"):
        _a_cylinder(direction=(0.0, 0.0, 0.0))


def test_a_cylinder_accepts_a_negative_extent_and_a_negative_location() -> None:
    """Both are ordinary geometry: the trim is signed along the axis and the
    axis may sit anywhere. A guard refusing them would refuse real parts."""
    accepted = _a_cylinder(location=(-1.0, -2.0, -3.0), extent=(-4.0, -1.0))

    assert accepted.extent_mm == (-4.0, -1.0)


# --------------------------------------------------------------------------
# The kernel's own tolerances
# --------------------------------------------------------------------------


def test_a_parallel_axis_is_parallel_either_way_round() -> None:
    """``gp_Dir.IsParallel`` is sign-agnostic, and it must stay so: which way
    a cylindrical surface's axis points is an export's convention."""
    along_z = _a_cylinder(direction=(0.0, 0.0, 1.0))

    assert along_z.is_parallel_to((0.0, 0.0, 1.0))
    assert along_z.is_parallel_to((0.0, 0.0, -1.0))


def test_an_axis_across_the_direction_is_not_parallel() -> None:
    assert not _a_cylinder(direction=(1.0, 0.0, 0.0)).is_parallel_to((0.0, 0.0, 1.0))


def test_parallelism_straddles_the_kernels_own_angular_tolerance() -> None:
    """``Precision::Angular()`` is 1e-12 radians. A tilt an order below it is
    parallel and one an order above it is not, so a substituted epsilon --
    every plausible one is far larger -- moves the second of these."""
    near = _a_cylinder(direction=_unit((1e-13, 0.0, 1.0)))
    far = _a_cylinder(direction=_unit((1e-11, 0.0, 1.0)))

    assert near.is_parallel_to((0.0, 0.0, 1.0))
    assert not far.is_parallel_to((0.0, 0.0, 1.0))


def test_two_cylinders_on_one_line_are_coaxial_however_far_apart() -> None:
    lower = _a_cylinder(location=(5.0, 6.0, 0.0), extent=(0.0, 1.0))
    upper = _a_cylinder(location=(5.0, 6.0, 90.0), extent=(0.0, 1.0))

    assert lower.is_coaxial_with(upper)


def test_two_cylinders_on_one_line_are_coaxial_facing_opposite_ways() -> None:
    """``gp_Ax1.IsCoaxial`` would refuse this pair -- it tests directions for
    equality, not parallelism -- and refusing it would drop real faces from a
    real stack. The rule is parallelism plus a position on the same line."""
    up = _a_cylinder(location=(5.0, 6.0, 0.0), direction=(0.0, 0.0, 1.0))
    down = _a_cylinder(location=(5.0, 6.0, 9.0), direction=(0.0, 0.0, -1.0))

    assert up.is_coaxial_with(down)


def test_a_parallel_cylinder_beside_the_line_is_not_coaxial() -> None:
    here = _a_cylinder(location=(0.0, 0.0, 0.0))
    beside = _a_cylinder(location=(0.5, 0.0, 0.0))

    assert not here.is_coaxial_with(beside)


def test_coaxiality_straddles_the_kernels_own_confusion() -> None:
    """``Precision::Confusion()`` is 1e-7 mm. Half of it is one line and twice
    it is two, which no epsilon anyone would pick by hand also does."""
    here = _a_cylinder(location=(0.0, 0.0, 0.0))

    assert here.is_coaxial_with(_a_cylinder(location=(5e-8, 0.0, 3.0)))
    assert not here.is_coaxial_with(_a_cylinder(location=(2e-7, 0.0, 3.0)))


def test_a_cylinder_across_the_line_is_not_coaxial_even_through_its_point() -> None:
    """Coaxiality is not "the other's location lies on my line": a crossing
    axis satisfies that and shares no axis at all."""
    here = _a_cylinder(location=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0))
    crossing = _a_cylinder(location=(0.0, 0.0, 3.0), direction=(1.0, 0.0, 0.0))

    assert not here.is_coaxial_with(crossing)


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    return (vector[0] / length, vector[1] / length, vector[2] / length)
