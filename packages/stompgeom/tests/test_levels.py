"""The coplanar-face partition, its granularity, and its control."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stompgeom.levels import Direction, Level, levels
from stompgeom.shapes import compound
from stompgeom.step import StepDocument, StepSolid, read_step
from stompmodel.units import nm_from_mm

#: The board this package's fixture folder does not yet hold; Task 16 homes it.
_PCB = Path(__file__).parents[3] / "fixtures" / "tar-pcb.stp"


def _box(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> StepSolid:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return StepSolid(name="box", shape=BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape())


def _cylinder(radius: float, height: float) -> StepSolid:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    return StepSolid(name="rod", shape=BRepPrimAPI_MakeCylinder(radius, height).Shape())


def _tilted_slab(radians: float) -> StepSolid:
    """A 10 x 10 x 2 slab turned about x, so its z faces are off axis by ``radians``."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    shape = BRepPrimAPI_MakeBox(10.0, 10.0, 2.0).Shape()
    turn = gp_Trsf()
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), radians)
    return StepSolid(name="tilted", shape=shape.Moved(TopLoc_Location(turn)))


def _faces(shape: Any, planar_only: bool = False) -> list[Any]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    found = []
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if not planar_only or adaptor.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
            found.append(face)
        explorer.Next()
    return found


def _summary(found: tuple[Level, ...]) -> list[tuple[Direction, int, float]]:
    """What each level says about the geometry, with the faces left out.

    ``Level`` equality would reach the kernel faces, and two walks of one
    shape hand back distinct wrappers for the same face.
    """
    return [
        (level.direction, int(level.offset_nm), round(level.area_mm2, 9))
        for level in found
    ]


def _facing(found: tuple[Level, ...], direction: tuple[int, int, int]) -> Level:
    return next(
        level for level in found
        if tuple(round(component) for component in level.direction) == direction
    )


@pytest.fixture(scope="module")
def pcb() -> StepDocument:
    return read_step(_PCB)


def test_a_cuboid_partitions_into_six_levels() -> None:
    """Six faces, six directions, no two coplanar. The edge lengths differ so a
    partition keyed on anything but direction and offset cannot coincide."""
    assert len(levels(_box(10.0, 20.0, 30.0, (0.0, 0.0, 0.0)))) == 6


def test_every_planar_face_lands_in_exactly_one_level() -> None:
    """The partition property: nothing dropped, nothing counted twice."""
    solid = _box(10.0, 20.0, 30.0, (0.0, 0.0, 0.0))

    assert sum(len(level.faces) for level in levels(solid)) == 6


def test_a_curved_face_is_no_level_of_its_own() -> None:
    """A plane is what a level is. The control is the face count: a cuboid's
    every face is planar, so it could not tell keeping from dropping.
    """
    solid = _cylinder(5.0, 12.0)
    assert len(_faces(solid.shape)) == 3
    assert len(_faces(solid.shape, planar_only=True)) == 2

    assert sum(len(level.faces) for level in levels(solid)) == 2


def test_an_offset_is_signed_along_its_own_levels_direction() -> None:
    """Not a coordinate: the slab sits between z = 5 and z = 8, and its lower
    level faces ``-z``, so that level's offset is the negation of its height.
    """
    found = levels(_box(10.0, 20.0, 3.0, (0.0, 0.0, 5.0)))

    assert _facing(found, (0, 0, -1)).offset_nm == nm_from_mm(-5.0)
    assert _facing(found, (0, 0, 1)).offset_nm == nm_from_mm(8.0)


def test_opposed_offsets_sum_to_the_thickness() -> None:
    """Offset runs along each face's OWN outward normal, so the pair adds.

    The slab is deliberately off the origin: a level whose offset were a
    coordinate along a fixed axis would give 5 + 8 here, and only a slab
    resting on z = 0 would let the two arithmetics agree.
    """
    found = levels(_box(10.0, 20.0, 3.0, (0.0, 0.0, 5.0)))
    down, up = _facing(found, (0, 0, -1)), _facing(found, (0, 0, 1))

    assert float(down.offset_nm + up.offset_nm) / 1e6 == 3.0


def test_the_axis_filter_keeps_both_facings() -> None:
    """An axis is unsigned: a caller asking for z wants the top and the bottom."""
    found = levels(_box(10.0, 20.0, 30.0, (0.0, 0.0, 0.0)), axis=(0.0, 0.0, 1.0))

    assert len(found) == 2
    assert {tuple(round(c) for c in level.direction) for level in found} == {
        (0, 0, 1), (0, 0, -1),
    }


def test_the_axis_filter_admits_a_face_tilted_within_the_inherited_tolerance() -> None:
    """``stompdrill``'s parallelism test, carried across unchanged. Exact
    equality on the quantised direction would reject this and narrow the
    acceptance the shipped code has always had.
    """
    found = levels(_tilted_slab(1e-5), axis=(0.0, 0.0, 1.0))

    # The control: the tilt is coarser than the grouping granularity, so the
    # quantised direction really is off axis and equality really would refuse it.
    assert all(level.direction != (0.0, 0.0, 1.0) for level in found)
    assert len(found) == 2


def test_the_axis_filter_refuses_a_face_tilted_beyond_that_tolerance() -> None:
    """The guilty half: a filter that admitted anything would pass the test
    above by never refusing at all. 1e-3 radians is well outside 1e-9.
    """
    assert levels(_tilted_slab(1e-3), axis=(0.0, 0.0, 1.0)) == ()


def test_faces_of_one_plane_separated_by_export_noise_stay_one_level(
    pcb: StepDocument,
) -> None:
    """The granularity's INNOCENT probe.

    ``fixtures/tar-pcb.stp`` carries a face tilted 3.846e-08 off axis --
    export noise, not geometry -- which the shipped acceptance test admits.
    At the ruled millionth granularity it stays with its plane.
    """
    walls = [
        level
        for solid in pcb.solids if not solid.name
        for level in levels(solid)
        if level.direction == (0.0, -1.0, 0.0) and level.offset_nm == nm_from_mm(37.5)
    ]

    assert len(walls) == 1
    assert len(walls[0].faces) == 3
    assert round(walls[0].area_mm2, 2) == 98.15


def test_a_billionth_granularity_would_split_that_wall(pcb: StepDocument) -> None:
    """The granularity's GUILTY probe.

    A control, not a behaviour: it re-runs the partition at the rejected
    granularity and asserts the split the ruling measured, so the constant
    the module states is evidence rather than a number nothing exercises.
    """
    from stompgeom.levels import _partition

    fine = [
        level
        for solid in pcb.solids if not solid.name
        for level in _partition(solid.shape, scale=1e9)
        if round(level.direction[1], 6) == -1.0 and level.offset_nm == nm_from_mm(37.5)
    ]

    assert len(fine) == 2
    assert sorted(round(level.area_mm2, 2) for level in fine) == [39.26, 58.89]


def test_the_partition_does_not_depend_on_traversal_order() -> None:
    """ADR-0006: no rule may consult input order. Keying, not clustering, is
    what makes this true by construction rather than by luck.
    """
    walk = _faces(_box(10.0, 20.0, 30.0, (0.0, 0.0, 0.0)).shape)
    forward = _summary(levels(StepSolid(name="forward", shape=compound(walk))))
    backward = _summary(levels(StepSolid(name="backward", shape=compound(reversed(walk)))))

    # The control: the two shapes really do present the same faces in
    # different orders, so agreement below is not agreement about one walk.
    assert forward != backward
    assert sorted(forward) == sorted(backward)


def test_a_published_direction_is_exactly_unit() -> None:
    """``CoordinateFrame``'s 1e-9 unit-length check must have margin, so the
    quantised key is re-normalised rather than handed back as it rounds.
    """
    for level in levels(_tilted_slab(1e-5)):
        assert abs(math.sqrt(sum(c * c for c in level.direction)) - 1.0) < 1e-15
