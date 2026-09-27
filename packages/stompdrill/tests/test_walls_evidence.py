"""The wall-drilling spec's Evidence, as assertions over the cached models.

A figure a design argues from is a figure a suite has to hold: these are the
measurements decision 5 reasons about, and a drift in any of them makes that
reasoning stale rather than merely inaccurate. ``tools/measure_walls.py``
prints the same numbers for a human. See ``_model_path`` for why this reads
the cache directly rather than through ``hammond.require_model``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompdrill.cad.case import _plates, select_solid
from stompdrill.cad.walls import Wall, draft_degrees, find_walls, lateral_plates, nearest_axis
from stompgeom.levels import direction_bin, levels
from stompgeom.step import StepSolid, assembly_spans, read_step
from stompmodel.frames import dot
from stompmodel.model import CaseFace
from stompmodel.units import mm_from_nm

from . import hammond

__all__: list[str] = []


def _inner_area(wall: Wall) -> float:
    """A wall's inner bundle's own area, summed the way a ``Level``'s is."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(wall.inner, props)
    return props.Mass()

#: Every catalogued box's own wall draft, in degrees, and how many direction
#: bins its lateral plate levels fall into. Measured, not published: Hammond
#: states no draft. The bin count is a property of the casting's internal
#: features as much as its walls, which is why it varies and why nothing
#: reasons from it -- it is recorded so a change in the models is visible.
EVIDENCE: dict[str, tuple[tuple[float, ...], int, int]] = {
    "1590A": ((1.500,), 29, 8),
    "1590B": ((1.250,), 29, 8),
    "1590BB": ((2.500,), 29, 8),
    "1590BB2": ((1.150,), 30, 8),
    "1590BBS": ((1.250,), 31, 8),
    "1590LB": ((1.300, 1.400), 28, 12),
    "1590Y": ((1.500,), 33, 8),
}


def _model_path(part: str) -> Path:
    """The cached model for ``part``, skipping rather than fetching or failing.

    ``hammond.require_model`` gates on ``hammond.MODELS``, a four-part
    catalogue ``test_hammond_harness.py`` locks; three of the seven parts
    here (1590BB2, 1590BBS, 1590LB) sit outside it, so that gate would raise
    rather than skip. This mirrors its cache-hit path without the gate.
    """
    path = hammond.cache_dir() / f"{part}.stp"
    if not path.is_file():
        pytest.skip(f"{part} is not cached")
    return path


def _box(part: str) -> tuple[StepSolid, int]:
    document = read_step(_model_path(part))
    spans = assembly_spans(document)
    axis = min(range(3), key=lambda index: spans[index])
    return select_solid(document, CaseFace.BOX), axis


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_every_wall_level_sits_at_this_model_s_own_draft(part: str) -> None:
    drafts, _bins, _drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    found = {
        round(draft_degrees(level.direction, (unit[0], unit[1], unit[2])), 3)
        for level in _plates(list(levels(solid)))
    }
    assert found == {0.0, 90.0} | set(drafts)


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_nothing_sits_between_the_draft_and_a_right_angle(part: str) -> None:
    """The measured gap the 45-degree boundary is never asked to decide inside.

    The margin is 1e-3 degrees, not the brief's original 1e-6: every cached
    model's own drafted levels measure 3e-5 to 3e-6 degrees off their nominal
    figure (the STEP file's own normal is not exact), which false-failed the
    1e-6 margin though no third population exists. 1e-3 clears that noise by
    two to three orders while staying under 1 degree of the nearest real
    draft or the 87.5-88.85 degree gap to 90 -- so it still catches a real
    intermediate population if the kernel or a model ever produced one.
    """
    drafts, _bins, _drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    degrees = [
        draft_degrees(level.direction, (unit[0], unit[1], unit[2]))
        for level in _plates(list(levels(solid)))
    ]
    between = [value for value in degrees if max(drafts) + 1e-3 < value < 90.0 - 1e-3]
    assert between == []


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_the_lateral_plate_levels_fall_into_the_bins_recorded(part: str) -> None:
    _drafts, bins, drafted = EVIDENCE[part]
    solid, axis = _box(part)
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    lateral = lateral_plates(solid, axis)
    assert len({direction_bin(level.direction) for level in lateral}) == bins
    assert len(
        {
            direction_bin(level.direction)
            for level in lateral
            if draft_degrees(level.direction, (unit[0], unit[1], unit[2])) > 0.0
        }
    ) == drafted


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(EVIDENCE))
def test_the_drill_axis_is_the_shallowest_and_the_walls_are_not_on_it(part: str) -> None:
    solid, axis = _box(part)
    assert axis == 1
    for level in lateral_plates(solid, axis):
        assert abs(level.direction[axis]) < 0.05


#: Each model's four walls, as ``(outer area, inner area)`` in mm², sorted so
#: the pair order is the sort's and not the discovery's. Measured. 1590A's two
#: long walls differ from each other and 1590B's long and short walls differ in
#: plate thickness, so nothing here may assume a box's walls are alike.
WALLS: dict[str, tuple[tuple[float, float], ...]] = {
    "1590A": ((664.11, 494.65), (664.11, 494.65), (2019.91, 1841.67), (2019.91, 1844.16)),
    "1590B": ((1262.36, 1008.59), (1262.36, 1008.59), (2613.21, 2248.41), (2613.21, 2248.41)),
    "1590BB": ((2412.92, 2006.93), (2412.92, 2006.93), (3154.23, 2690.82), (3154.23, 2690.82)),
    "1590BB2": ((2720.46, 2301.30), (2720.46, 2301.30), (3556.27, 3079.72), (3556.27, 3079.72)),
    "1590BBS": ((3044.71, 2624.36), (3044.71, 2624.36), (3991.54, 3513.81), (3991.54, 3513.81)),
    "1590LB": ((1021.23, 789.74),) * 4,
    "1590Y": ((3223.56, 2507.22),) * 4,
}

#: Each model's plate thickness along each wall's own normal, in millimetres,
#: sorted. 1590B's two pairs genuinely differ, which is why this is per wall.
PLATES: dict[str, tuple[float, ...]] = {
    "1590A": (1.7494,) * 4,
    "1590B": (1.9995, 1.9995, 2.1495, 2.1495),
    "1590BB": (2.2479,) * 4,
    "1590BB2": (2.2495,) * 4,
    "1590BBS": (2.2495,) * 4,
    "1590LB": (1.9500,) * 4,
    "1590Y": (2.4991,) * 4,
}

#: The least distance between two perpendicular walls' outer levels, in
#: millimetres. Every one positive is decision 13's corner argument: a ray
#: through a corner lands in no wall's region, so no cross-surface
#: breakthrough check is needed and the findings vocabulary grows by two.
CORNER_GAPS: dict[str, float] = {
    "1590A": 7.5575, "1590B": 7.6823, "1590BB": 5.9849, "1590BB2": 6.8479,
    "1590BBS": 7.3398, "1590LB": 7.0690, "1590Y": 2.8275,
}


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(WALLS))
def test_every_box_has_four_walls_measuring_what_was_recorded(part: str) -> None:
    solid, axis = _box(part)
    walls = find_walls(solid, axis)
    assert len(walls) == 4
    measured = sorted(
        (round(wall.outer.area_mm2, 2), round(_inner_area(wall), 2)) for wall in walls
    )
    assert measured == sorted(WALLS[part])


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(PLATES))
def test_a_wall_s_plate_is_measured_along_its_own_normal(part: str) -> None:
    solid, axis = _box(part)
    walls = find_walls(solid, axis)
    assert sorted(round(mm_from_nm(wall.plate_nm), 4) for wall in walls) == sorted(PLATES[part])


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(WALLS))
def test_a_wall_s_outside_is_larger_than_its_inside_on_every_wall(part: str) -> None:
    """The draft's own signature, and a cheap check that the pairing is not inverted."""
    solid, axis = _box(part)
    for wall in find_walls(solid, axis):
        assert wall.outer.area_mm2 > _inner_area(wall)


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(CORNER_GAPS))
def test_two_perpendicular_walls_never_touch(part: str) -> None:
    """Decision 13, measured: a corner fillet belongs to no wall's level."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    solid, axis = _box(part)
    walls = find_walls(solid, axis)
    gaps = []
    for first in walls:
        for second in walls:
            if abs(dot(first.outward, second.outward)) > 0.5:
                continue
            measure = BRepExtrema_DistShapeShape(first.outer_faces, second.outer_faces)
            assert measure.IsDone()
            gaps.append(measure.Value())
    assert gaps
    assert min(gaps) == pytest.approx(CORNER_GAPS[part], abs=1e-3)
    assert min(gaps) > 0.0


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(WALLS))
def test_the_order_walls_come_back_in_is_the_geometry_s(part: str) -> None:
    solid, axis = _box(part)
    outward = [nearest_axis(wall.outward) for wall in find_walls(solid, axis)]
    assert outward == sorted(outward)
    assert len(set(outward)) == 4
