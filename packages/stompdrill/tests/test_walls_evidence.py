"""The measured wall populations, as assertions over the cached models.

A figure a design argues from is a figure a suite has to hold: these are the
measurements ADR-0007's wall rules reason from, and a drift in any of them makes that
reasoning stale rather than merely inaccurate. ``tools/measure_walls.py``
prints the same numbers for a human. See ``_model_path`` for why this reads
the cache directly rather than through ``hammond.require_model``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompdrill.cad import load_case_model
from stompdrill.cad.case import _facing, _plates, build_frame, find_faces, select_solid
from stompdrill.cad.region import build_region
from stompdrill.cad.walls import (
    Wall,
    _normalised,
    _projected_box,
    _wall_inner_level,
    build_wall_frame,
    draft_degrees,
    drilled_surface,
    find_walls,
    lateral_plates,
    nearest_axis,
    surface_key,
    wall_bounds_nm,
)
from stompgeom.levels import Direction, Level, direction_bin, levels
from stompgeom.step import StepSolid, assembly_spans, bounding_box_mm, read_step
from stompmodel.frames import CoordinateFrame, cross, dot
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm

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
    "1590B2": ((1.250,), 30, 8),
    "1590BB": ((2.500,), 29, 8),
    "1590BB2": ((1.150,), 30, 8),
    "1590BBS": ((1.250,), 31, 8),
    "1590BS": ((1.250, 1.400), 31, 8),
    "1590LB": ((1.300, 1.400), 28, 12),
    "1590Y": ((1.500,), 33, 8),
}


def _model_path(part: str) -> Path:
    """The cached model for ``part``, skipping rather than fetching or failing.

    ``hammond.require_model`` gates on ``hammond.MODELS``, the catalogue
    ``test_hammond_harness.py`` locks, and raises for any part outside it.
    The populations below are chosen for what each one measures and not for
    that gate, so several of them sit outside it and would raise where a
    missing model should only skip. This mirrors its cache-hit path without
    the gate.
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
#: millimetres. Every one positive is the corner argument: a ray through a
#: corner lands in no wall's region, so no cross-surface breakthrough check
#: is needed.
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
    """Perpendicular walls' outer levels stay apart, so a corner fillet belongs to no wall's level."""
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


def _centroid_mm(shape: object) -> tuple[float, float, float]:
    """``shape``'s own mass centroid, a mechanics quantity, not the datum (ADR-0007)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    centre = props.CentreOfMass()
    return (centre.X(), centre.Y(), centre.Z())


#: Each model's wall spans in its own frame, ``(u, v)`` in millimetres, sorted.
#: ``u`` is the longer on every wall of every model, which is why the panel's
#: "u is the longer span" convention survives unchanged on a wall.
SPANS: dict[str, tuple[tuple[float, float], ...]] = {
    "1590A": ((26.5000, 25.0609), (26.5000, 25.0609), (80.6000, 25.0609), (80.6000, 25.0609)),
    "1590B": ((48.5000, 26.0280), (48.5000, 26.0280), (100.4000, 26.0280), (100.4000, 26.0280)),
    "1590BB": ((83.0000, 29.0713), (83.0000, 29.0713), (108.5000, 29.0713), (108.5000, 29.0713)),
    "1590BB2": ((83.0000, 32.7767), (83.0000, 32.7767), (108.5000, 32.7767), (108.5000, 32.7767)),
    "1590BBS": ((82.0000, 37.1307), (82.0000, 37.1307), (107.5000, 37.1307), (107.5000, 37.1307)),
    "1590LB": ((40.6030, 25.5443),) * 4,
    "1590Y": ((88.0014, 37.0389),) * 4,
}

#: How far each model's outer wall region's own centroid sits from the centre
#: of its bounding box, in nanometres. Five models agree to under a nanometre
#: and two do not, so the datum being the box's centre and not the centroid
#: (ADR-0007) is observable.
CENTROID_OFFSETS: dict[str, int] = {
    "1590A": 0, "1590B": 1, "1590BB": 1, "1590BB2": 0,
    "1590BBS": 1, "1590LB": 66_461, "1590Y": 68_771,
}


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(SPANS))
def test_every_wall_spans_what_was_measured_in_its_own_frame(part: str) -> None:
    solid, axis = _box(part)
    drilled = find_faces(solid, axis)
    measured = []
    for wall in find_walls(solid, axis):
        frame = build_wall_frame(wall, drilled.outward)
        x0, _y0, x1, y1 = wall_bounds_nm(wall.outer_faces, frame)
        span_u = mm_from_nm(Nanometre(x1 - x0))
        span_v = mm_from_nm(Nanometre(y1 * 2))
        measured.append((round(span_u, 4), round(span_v, 4)))
    assert sorted(measured) == sorted(SPANS[part])


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(SPANS))
def test_u_is_the_longer_span_on_every_wall(part: str) -> None:
    solid, axis = _box(part)
    drilled = find_faces(solid, axis)
    for wall in find_walls(solid, axis):
        x0, y0, x1, y1 = wall_bounds_nm(wall.outer_faces, build_wall_frame(wall, drilled.outward))
        assert x1 - x0 > y1 - y0


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(CENTROID_OFFSETS))
def test_the_centroid_and_the_box_centre_differ_by_what_was_measured(part: str) -> None:
    """Two models make the centroid and the box centre disagree, by the measured amount.

    Asserted rather than merely recorded, because if every model agreed the
    choice of datum would be moot and it could be either -- and a future model
    that disagrees by more than these two is worth failing over.
    """
    solid, axis = _box(part)
    drilled = find_faces(solid, axis)
    offsets = set()
    for wall in find_walls(solid, axis):
        frame = build_wall_frame(wall, drilled.outward)
        centroid = frame.basis.to_canonical(_centroid_mm(wall.outer_faces))
        offsets.add(max(abs(nm_from_mm(centroid[0])), abs(nm_from_mm(centroid[1]))))
    assert max(offsets) == pytest.approx(CENTROID_OFFSETS[part], abs=2)


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(SPANS))
def test_every_wall_states_a_surface_the_document_accepts(part: str) -> None:
    """Confirms construction succeeds.

    ``wall_bounds_nm`` states bounds symmetrically about the datum, so this can
    never be the datum's own guard -- see
    ``test_the_datum_is_the_outer_box_s_own_centre_not_a_looser_pin``.
    """
    solid, axis = _box(part)
    drilled = find_faces(solid, axis)
    face_frame = build_frame(drilled, axis)
    keys = []
    for wall in find_walls(solid, axis):
        frame = build_wall_frame(wall, drilled.outward)
        region = build_region(wall.inner, axis, drilled.outward[axis])
        key = surface_key(wall, face_frame)
        surface = drilled_surface(wall, key, frame, wall.outer_faces)
        assert surface.key == key
        assert surface.thickness_nm == wall.plate_nm
        keys.append(key)
        assert region is not None
    assert sorted(keys) == ["bottom", "left", "right", "top"]


def _outer_box_centre_mm(wall: Wall, drilled_outward: Direction) -> tuple[float, float, float]:
    """The outer region's own bounding-box centre, in model millimetres.

    Redone from scratch -- the ``u``/``v``/``w`` construction and the box
    projection, not ``build_wall_frame``'s own origin arithmetic -- so the
    guard this feeds cannot pass by checking the frame against itself.
    """
    w = wall.outward
    u = _normalised(cross(drilled_outward, w))
    v = cross(w, u)
    provisional = CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)), u=u, v=v, w=w
    )
    box = _projected_box(wall.outer_faces, provisional)
    return provisional.to_model(
        nm_from_mm((box[0] + box[3]) / 2.0),
        nm_from_mm((box[1] + box[4]) / 2.0),
        nm_from_mm((box[2] + box[5]) / 2.0),
    )


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(SPANS))
def test_the_datum_is_the_outer_box_s_own_centre_not_a_looser_pin(part: str) -> None:
    """A hole at frame ``(0, 0)`` is where a marker finds it on the box.

    ``wall_bounds_nm`` cannot see the datum move (a wall's bounds are always
    stated symmetrically), so this checks the frame's own mapping against a
    centre computed afresh, not against ``build_wall_frame``'s own output --
    the guard that the datum is the box centre and not the centroid. 10 nm
    clears the real implementation's own round-trip noise, measured under
    0.5 nm on every cached model, by twenty times, while staying thousands
    of times below the tens-of-microns divergence a centroid datum produces.
    """
    solid, axis = _box(part)
    drilled = find_faces(solid, axis)
    for wall in find_walls(solid, axis):
        frame = build_wall_frame(wall, drilled.outward)
        mapped = frame.basis.to_model(Nanometre(0), Nanometre(0), wall.plate_nm)
        expected = _outer_box_centre_mm(wall, drilled.outward)
        assert mapped == pytest.approx(expected, abs=1e-5)


@pytest.mark.hammond
def test_a_casting_drafting_its_two_faces_alike_or_not_still_has_four_walls() -> None:
    """1590BS drafts a wall's outer face 1.400 degrees and its inner 1.250.

    Planes 0.15 degrees apart share no direction bin, so a pairing on exact
    parallelism finds nothing; this is the one catalogued model that shows it.
    """
    solid, axis = _box("1590BS")
    walls = find_walls(solid, axis)
    assert sorted(round(mm_from_nm(wall.plate_nm), 3) for wall in walls) == [
        1.996, 1.996, 1.998, 1.998
    ]


#: Each casting here discriminates a different wrong answer about which face
#: backs a wall, and each thickness is that casting's own measured plate rather
#: than a bound something falls under.
#: 1590BS drafts a wall's outer face 1.400 degrees and its inner 1.250 -- planes
#: 0.15 degrees apart, sharing no direction bin -- so a pairing on exact
#: parallelism finds no inner face at all, and one demanding the inner face
#: draft at least as much as the outer refuses the only inner face there is.
#: 1590B stands a 0.203 mm2 level drafted 7.545 degrees 1.489 mm nearer its
#: (0, 0, 1) wall's outer face than that wall's own inner face, so nearest on
#: its own takes the sliver; its two pairs of walls also measure 1.9995 and
#: 2.1495 mm, which is why this is a per-wall population.
#: 1590H stands a 113.011 mm2 level drafted 1.000 degrees -- exactly its outer
#: face's own draft -- 0.956 mm behind that face, nearer than the 1.4998 mm
#: plate, so no comparison of drafts can refuse it and the axis it leans on is
#: all that can. Its two long walls meet the box floor at 0.746 mm the same way.
DISCRIMINATING_PLATES: dict[str, tuple[float, ...]] = {
    "1590B": (2.000, 2.000, 2.149, 2.149),
    "1590BS": (1.996, 1.996, 1.998, 1.998),
    "1590H": (1.500, 1.500, 1.500, 1.500),
}


@pytest.mark.hammond
@pytest.mark.parametrize("part", sorted(DISCRIMINATING_PLATES))
def test_a_wall_pairs_with_the_face_that_backs_it(part: str) -> None:
    """Each wall of each discriminating casting measures that casting's own plate."""
    walls = find_walls(*_box(part))
    assert len(walls) == 4
    measured = tuple(sorted(round(mm_from_nm(wall.plate_nm), 3) for wall in walls))
    assert measured == tuple(sorted(DISCRIMINATING_PLATES[part]))


def _cached_castings() -> tuple[str, ...]:
    """Every casting the cache holds, in catalogue order.

    A draft or an area is quoted over the parts the Evidence covers, which is
    what ``EVIDENCE`` is for. A rule about what a wall *is* has to answer for
    every casting a workbench may fetch, so the pairing is asserted over
    whatever has been cached instead. An empty cache still yields one case, so
    the skip comes from ``_model_path`` rather than from an empty parameter
    list that would report nothing while checking nothing.
    """
    return tuple(sorted(path.stem for path in hammond.cache_dir().glob("*.stp"))) or (
        "1590B",
    )


def _opposed_axis(direction: Direction) -> Direction:
    """The signed kernel axis facing back along the one ``direction`` leans on."""
    axis = nearest_axis(direction)
    return (-axis[0], -axis[1], -axis[2])


def _behind(plates: list[Level], outer: Level) -> list[Level]:
    """Every plate level standing behind ``outer``: the pool a pairing chooses from.

    Rebuilt here from ``_facing`` and the offset sum rather than taken from
    the pairing, because the control below has to reach the state before the
    choice to disagree with it.
    """
    return [
        level
        for level in plates
        if _facing(level, outer) < 0 and level.offset_nm + outer.offset_nm > 0
    ]


def _nearest_behind(plates: list[Level], outer: Level) -> Level | None:
    """The nearest level behind ``outer``, larger area first: no axis clause at all.

    The control for the two assertions above, which both read the pairing's
    own answer and would become tautologies if the axis equality ever stopped
    deciding anything. Nothing in the tree pairs this way; it exists to
    disagree with the pairing that ships.
    """
    candidates = _behind(plates, outer)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda level: (level.offset_nm + outer.offset_nm, -level.area_mm2),
    )


#: How near a rival level has to stand to the face a wall paired with before
#: depth can no longer tell the two apart. A micron is four orders above the
#: nanometre the levels are keyed in and four below the millimetre a plate
#: measures, so it admits the zero-gap and 83 nm coincidences the castings
#: really present without reaching a second plate.
_RIVAL_WINDOW_NM = Nanometre(1_000)


@pytest.mark.hammond
@pytest.mark.parametrize("part", _cached_castings())
def test_a_wall_s_inner_face_is_the_level_on_its_own_back_axis(part: str) -> None:
    """A wall's inner face leans on the axis exactly opposed to its outer face's.

    Exact tuple equality and no tolerance, asserted of every wall of every
    cached casting: a wall has one inner plane and a plane has one leaning
    axis, so this is a statement about one wall's own geometry rather than
    about how many siblings a square box happens to tie. The second assertion
    is why the axis has to be what decides -- stated as an implication, so it
    is vacuous where no rival stands within a micron and does the work where
    one does, which on this catalogue is most of the square-walled castings.
    """
    solid, axis = _box(part)
    plates = _plates(list(levels(solid)))
    walls = find_walls(solid, axis)
    assert len(walls) == 4
    for wall in walls:
        inner = _wall_inner_level(plates, wall.outer)
        assert nearest_axis(inner.direction) == _opposed_axis(wall.outward)
        plate = inner.offset_nm + wall.outer.offset_nm
        for rival in _behind(plates, wall.outer):
            gap = abs(rival.offset_nm + wall.outer.offset_nm - plate)
            if rival is inner or gap > _RIVAL_WINDOW_NM:
                continue
            assert nearest_axis(rival.direction) != _opposed_axis(wall.outward), (
                f"{part} {wall.outward}: a second level {gap} nm from the face it "
                f"paired with leans on the same axis, so depth cannot tell them apart"
            )


@pytest.mark.hammond
def test_dropping_the_axis_clause_answers_differently_on_a_cached_casting() -> None:
    """The control: without the axis equality some cached casting pairs differently.

    Both assertions above read the pairing's own answer, so either could pass
    by stating nothing. This pairs the same walls by depth and area alone and
    fails if that agrees everywhere -- which would mean the axis is deciding
    nothing and the assertions above have gone vacuous. ``any`` rather than a
    count: how many walls disagree is a fact about the catalogue, and a
    catalogue that grew would make a count stale without making it wrong.
    """
    parts = _cached_castings()
    assert parts
    assert any(_the_axis_decides(part) for part in parts)


def _the_axis_decides(part: str) -> bool:
    """Whether any of ``part``'s walls pairs differently with the axis clause dropped."""
    solid, axis = _box(part)
    plates = _plates(list(levels(solid)))
    return any(
        _nearest_behind(plates, wall.outer) is not _wall_inner_level(plates, wall.outer)
        for wall in find_walls(solid, axis)
    )


def _lid(part: str) -> tuple[StepSolid, int]:
    document = read_step(_model_path(part))
    spans = assembly_spans(document)
    axis = min(range(3), key=lambda index: spans[index])
    return select_solid(document, CaseFace.LID), axis


def _own_draft(direction: Direction) -> float:
    """How far ``direction`` is drafted off the axis it leans on, in degrees.

    Computed here rather than imported: ``draft_degrees`` answers the tilt
    *out of* the plane perpendicular to the axis handed in, so against a
    level's own leaning axis it returns a right angle less the draft, and the
    assertions below are about the draft itself.
    """
    return 90.0 - draft_degrees(direction, nearest_axis(direction))


#: What a cached lid measures along the drill axis, in millimetres: its overall
#: depth, its own plate, and the closure rim that is the difference of the two.
#: A lid registers no walls because that rim is a flange nobody drills
#: (ADR-0007), and the figure that argument rests on is asserted here rather
#: than left to drift in a document nobody re-measures.
LID_DEPTH_MM = (5.500, 6.500)
LID_PLATE_MM = (1.900, 3.200)
LID_RIM_MM = (2.600, 4.000)


@pytest.mark.hammond
@pytest.mark.parametrize("part", _cached_castings())
def test_a_lid_is_a_plate_and_a_closure_rim_of_the_measured_height(part: str) -> None:
    """A lid's rim is the few millimetres the no-walls rule rests on.

    Held as an assertion and not merely printed, because ADR-0007 argues from
    these figures: a drift in them should fail a suite that can say so rather
    than quietly stale the reasoning in a document.
    """
    solid, axis = _lid(part)
    box = bounding_box_mm(solid.shape)
    depth = round(box[axis + 3] - box[axis], 3)
    plate = round(mm_from_nm(find_faces(solid, axis).plate_nm), 3)
    assert LID_DEPTH_MM[0] <= depth <= LID_DEPTH_MM[1]
    assert LID_PLATE_MM[0] <= plate <= LID_PLATE_MM[1]
    assert LID_RIM_MM[0] <= round(depth - plate, 3) <= LID_RIM_MM[1]


@pytest.mark.hammond
@pytest.mark.parametrize("part", _cached_castings())
def test_a_lid_registers_no_wall_and_states_why(part: str) -> None:
    """Every cached lid: no wall surface, no wall region, and a reason given.

    Asserted over the whole cache because the rim is in every casting's lid
    and ``find_walls`` answers four for every one of them, so a lid yielding
    nothing can only be a rule and never a property of the geometry.
    """
    model = load_case_model(
        _model_path(part), face=CaseFace.LID, margin_nm=Nanometre(500_000)
    )
    assert model.walls == ()
    assert dict(model.wall_regions) == {}
    assert model.walls_unavailable


@pytest.mark.hammond
@pytest.mark.parametrize("part", _cached_castings())
def test_a_wall_s_inner_face_drafts_no_more_than_its_outer_face_does(part: str) -> None:
    """The inequality, over every wall the program discovers.

    A bare comparison and no slack: both faces' drafts come out of the same
    arithmetic over mirrored direction keys, so a casting drafting its two
    faces alike reads exactly zero excess.
    """
    solid, axis = _box(part)
    plates = _plates(list(levels(solid)))
    for wall in find_walls(solid, axis):
        inner = _wall_inner_level(plates, wall.outer)
        assert _own_draft(inner.direction) <= _own_draft(wall.outward)


@pytest.mark.hammond
def test_the_one_casting_drafting_its_two_faces_unalike_drafts_the_inside_less() -> None:
    """1590BS reads 1.400 degrees outside and 1.250 inside, on all four walls.

    The known figure the inequality is checked against: it is the only cached
    casting whose two faces draft at all unalike, and it drafts them in the
    direction the inequality admits.
    """
    solid, axis = _box("1590BS")
    plates = _plates(list(levels(solid)))
    assert {
        (
            round(_own_draft(wall.outward), 3),
            round(_own_draft(_wall_inner_level(plates, wall.outer).direction), 3),
        )
        for wall in find_walls(solid, axis)
    } == {(1.400, 1.250)}


def _drafts_refused(part: str) -> int:
    """How many levels behind ``part``'s walls the draft clause turns away.

    Rebuilt from the pool rather than read off the pairing, so the control
    below reaches the state before the choice: a level leaning back at a wall,
    standing behind its outer face, and drafting further than it.
    """
    solid, axis = _box(part)
    plates = _plates(list(levels(solid)))
    refused = 0
    for wall in find_walls(solid, axis):
        outer = wall.outer
        for level in _behind(plates, outer):
            if nearest_axis(level.direction) != _opposed_axis(outer.direction):
                continue
            refused += _own_draft(level.direction) > _own_draft(outer.direction)
    return refused


@pytest.mark.hammond
def test_the_draft_clause_turns_a_level_away_on_a_cached_casting() -> None:
    """The control: the inequality above would pass by stating nothing.

    It reads the pairing's own answer, so it goes vacuous if the clause ever
    stops excluding anything. This counts the levels the clause refuses from
    the pool directly and fails if no cached casting presents one -- chamfer
    flats, fillet lands and drafted pockets lean back at a wall and draft far
    steeper than it does. ``any`` rather than a count: how many a catalogue
    presents is a fact about the catalogue.
    """
    parts = _cached_castings()
    assert parts
    assert any(_drafts_refused(part) for part in parts)
