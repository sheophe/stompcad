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
    Wall,
    build_wall_frame,
    draft_degrees,
    is_lateral,
    nearest_axis,
    surface_key,
    wall_bounds_nm,
)
from stompdrill.errors import StompdrillError
from stompgeom.levels import Direction, Level
from stompgeom.shapes import compound
from stompgeom.step import bounding_box_mm
from stompmodel.frames import CoordinateFrame, FaceFrame, cross, dot
from stompmodel.units import Nanometre

__all__: list[str] = []

_Y = (0.0, 1.0, 0.0)


def _perpendicular_pair(normal: Direction) -> tuple[Direction, Direction]:
    """Two unit directions completing ``normal`` into a right-handed basis.

    Picked by Gram-Schmidt against a reference not parallel to ``normal``,
    so this works for any wall's outward direction, not only an axis-aligned
    one -- the only way to build a rectangle whose plane is ``normal``'s own.
    """
    reference = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    raw = cross(reference, normal)
    length = math.sqrt(dot(raw, raw))
    a = (raw[0] / length, raw[1] / length, raw[2] / length)
    b = cross(normal, a)
    return a, b


def _synthetic_wall(outward: Direction, plate_mm: float = 1.0) -> Wall:
    """A ``Wall`` from two parallel kernel rectangles, for a rule no casting states.

    The outer rectangle is centred on the kernel origin so its bounding box's
    own centre is a point on its face, which is what ``_outer_point`` reads
    back; the inner one sits ``plate_mm`` behind it along ``outward``.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    axis_u, axis_v = _perpendicular_pair(outward)
    half_u, half_v = 40.0, 10.0

    def _face(offset_mm: float):
        centre = tuple(offset_mm * outward[i] for i in range(3))
        polygon = BRepBuilderAPI_MakePolygon()
        for su, sv in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
            point = tuple(
                centre[i] + su * half_u * axis_u[i] + sv * half_v * axis_v[i]
                for i in range(3)
            )
            polygon.Add(gp_Pnt(*point))
        polygon.Close()
        return BRepBuilderAPI_MakeFace(polygon.Wire()).Face()

    outer_face = _face(0.0)
    inner_face = _face(-plate_mm)
    outer_level = Level(
        direction=outward,
        offset_nm=Nanometre(0),
        area_mm2=(2 * half_u) * (2 * half_v),
        faces=(outer_face,),
    )
    return Wall(
        outer=outer_level,
        outer_faces=compound([outer_face]),
        inner=compound([inner_face]),
        plate_nm=Nanometre(round(plate_mm * 1_000_000)),
        outward=outward,
    )


def _outer_point(wall: Wall) -> tuple[float, float, float]:
    """A point on ``wall``'s own outer face, read from its bounding box centre."""
    box = bounding_box_mm(wall.outer_faces)
    return ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0, (box[2] + box[5]) / 2.0)


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


def test_the_frame_s_third_axis_is_the_wall_s_own_outward_normal() -> None:
    wall = _synthetic_wall(outward=(0.0, 0.0, -1.0))
    frame = build_wall_frame(wall, drilled_outward=(0.0, 1.0, 0.0))
    assert frame.basis.w == (0.0, 0.0, -1.0)


def test_up_on_a_wall_s_sheet_leads_towards_the_drilled_face() -> None:
    """Which is how a builder holds the pedal while marking its side."""
    wall = _synthetic_wall(outward=(0.0, 0.0, -1.0))
    frame = build_wall_frame(wall, drilled_outward=(0.0, 1.0, 0.0))
    assert dot(frame.basis.v, (0.0, 1.0, 0.0)) > 0.99


def test_the_frame_is_right_handed_about_the_outward_normal() -> None:
    wall = _synthetic_wall(outward=(0.0, 0.0, -1.0))
    basis = build_wall_frame(wall, drilled_outward=(0.0, 1.0, 0.0)).basis
    assert cross(basis.u, basis.v) == pytest.approx(basis.w, abs=1e-12)


def test_the_datum_sits_on_the_inner_plane_as_every_face_frame_s_does() -> None:
    """``FaceFrame``'s own contract, which the STEP emitter's wall branch relies on."""
    wall = _synthetic_wall(outward=(0.0, 0.0, -1.0), plate_mm=2.0)
    frame = build_wall_frame(wall, drilled_outward=(0.0, 1.0, 0.0))
    outer = frame.basis.to_canonical(_outer_point(wall))
    assert outer[2] == pytest.approx(2.0, abs=1e-6)


def test_a_wall_s_bounds_are_stated_about_its_own_datum() -> None:
    """Which is what ``DrilledSurface`` refuses a wall for not doing."""
    wall = _synthetic_wall(outward=(0.0, 0.0, -1.0))
    frame = build_wall_frame(wall, drilled_outward=(0.0, 1.0, 0.0))
    x0, y0, x1, y1 = wall_bounds_nm(wall.outer_faces, frame)
    assert x0 + x1 == 0
    assert y0 + y1 == 0


def test_the_surface_key_is_read_from_the_projection_and_not_from_a_list() -> None:
    """Six names, and which one is geometry: no ordering may decide it."""
    # w = u x v = (0, -1, 0), the only right-handed third axis for these
    # u/v; surface_key never reads w, so this keeps the frame valid without
    # touching what the test exercises.
    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 0.0, 1.0),
            w=(0.0, -1.0, 0.0),
        )
    )
    assert surface_key(_synthetic_wall(outward=(1.0, 0.0, 0.0)), face) == "right"
    assert surface_key(_synthetic_wall(outward=(-1.0, 0.0, 0.0)), face) == "left"
    assert surface_key(_synthetic_wall(outward=(0.0, 0.0, 1.0)), face) == "top"
    assert surface_key(_synthetic_wall(outward=(0.0, 0.0, -1.0)), face) == "bottom"


def test_a_slightly_drafted_wall_keys_the_same_as_an_undrafted_one() -> None:
    """The draft tilts out of the face plane, which the projection ignores."""
    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 0.0, 1.0),
            w=(0.0, -1.0, 0.0),
        )
    )
    tilt = math.radians(2.5)
    drafted = (0.0, -math.sin(tilt), -math.cos(tilt))
    assert surface_key(_synthetic_wall(outward=drafted), face) == "bottom"
