"""Deriving the drill axis, the side, its faces and the canonical frame."""

from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="needs stompdrill[step]")

from stompdrill.cad.case import Faces, build_frame, drill_axis, find_faces, select_solid  # noqa: E402
from stompgeom.step import read_step  # noqa: E402
from stompmodel.units import Nanometre  # noqa: E402
from tests.hammond import MODELS  # noqa: E402

pytestmark = pytest.mark.hammond

FOOTPRINT = (Nanometre(119_500_000), Nanometre(94_000_000))

#: The fixture that supplies each catalogued model's cached STEP file.
_FIXTURE_OF = {
    "1590BB": "hammond_bb", "1590B": "hammond_b", "1590A": "hammond_a", "1590Y": "hammond_y",
}


@pytest.fixture(scope="module")
def document(hammond_bb):
    return read_step(hammond_bb)


def test_the_drill_axis_is_the_one_normal_to_the_footprint_plane(document):
    """1590BB is modelled Z-up but assembled Y-up, so the axis must be Y."""
    assert drill_axis(document, FOOTPRINT) == 1


def test_the_axis_is_derived_from_the_footprint_and_not_hard_coded(hammond_b):
    """A second enclosure with a different footprint must also resolve."""
    other = read_step(hammond_b)

    assert drill_axis(other, (Nanometre(112_400_000), Nanometre(60_500_000))) in (0, 1, 2)


def test_a_footprint_matching_nothing_is_rejected(document):
    from stompdrill.errors import StompdrillError

    with pytest.raises(StompdrillError, match="footprint"):
        drill_axis(document, (Nanometre(999_000_000), Nanometre(1_000_000)))


def test_the_box_and_lid_are_selected_by_name(document):
    assert "BOX" in select_solid(document, "box").name.upper()
    assert "LID" in select_solid(document, "lid").name.upper()


def test_the_selected_lid_is_the_thinner_solid(document):
    from stompgeom.step import bounding_box_mm

    axis = drill_axis(document, FOOTPRINT)
    box = bounding_box_mm(select_solid(document, "box").shape)
    lid = bounding_box_mm(select_solid(document, "lid").shape)

    assert (lid[axis + 3] - lid[axis]) < (box[axis + 3] - box[axis])


def test_an_unknown_face_name_is_rejected(document):
    from stompdrill.errors import StompdrillError

    with pytest.raises(StompdrillError):
        select_solid(document, "flange")


def test_the_box_plate_thickness_is_measured_from_the_two_faces(document):
    axis = drill_axis(document, FOOTPRINT)

    faces = find_faces(select_solid(document, "box"), axis)

    assert faces.plate_nm == 2_250_000


def test_the_lid_plate_thickness_is_measured_from_the_two_faces(document):
    axis = drill_axis(document, FOOTPRINT)

    faces = find_faces(select_solid(document, "lid"), axis)

    assert faces.plate_nm == 2_000_000


def test_the_outward_normal_points_away_from_the_solid(document):
    """same_sense, not the surface normal, decides which way is out."""
    axis = drill_axis(document, FOOTPRINT)
    box = select_solid(document, "box")
    faces = find_faces(box, axis)

    from stompgeom.step import bounding_box_mm
    lo, hi = bounding_box_mm(box.shape)[axis], bounding_box_mm(box.shape)[axis + 3]
    centre = (lo + hi) / 2
    drilled_at = faces.drilled_position_mm

    assert (drilled_at - centre) * faces.outward[axis] > 0


def test_the_box_and_lid_face_in_opposite_directions(document):
    axis = drill_axis(document, FOOTPRINT)

    box = find_faces(select_solid(document, "box"), axis)
    lid = find_faces(select_solid(document, "lid"), axis)

    assert box.outward[axis] == -lid.outward[axis]


def test_the_frame_basis_is_right_handed_about_the_outward_normal(document):
    axis = drill_axis(document, FOOTPRINT)
    faces = find_faces(select_solid(document, "box"), axis)

    frame = build_frame(faces, axis)
    u, v, w = frame.basis.u, frame.basis.v, frame.basis.w
    cross = (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )

    assert pytest.approx(cross, abs=1e-9) == w


def test_the_frame_is_orthonormal(document):
    axis = drill_axis(document, FOOTPRINT)
    frame = build_frame(find_faces(select_solid(document, "box"), axis), axis)

    for a in (frame.basis.u, frame.basis.v, frame.basis.w):
        assert pytest.approx(sum(c * c for c in a), abs=1e-9) == 1.0
    assert pytest.approx(sum(a * b for a, b in zip(frame.basis.u, frame.basis.v)), abs=1e-9) == 0.0


def _frame_for(request, part: str) -> tuple[int, Faces, Faces]:
    """The drill axis and box/lid ``Faces`` for a catalogued model, by designator."""
    model = MODELS[part]
    document = read_step(request.getfixturevalue(_FIXTURE_OF[part]))
    footprint = (
        Nanometre(round(model.footprint_mm[0] * 1_000_000)),
        Nanometre(round(model.footprint_mm[1] * 1_000_000)),
    )
    axis = drill_axis(document, footprint)
    box = find_faces(select_solid(document, "box"), axis)
    lid = find_faces(select_solid(document, "lid"), axis)
    return axis, box, lid


@pytest.mark.parametrize("part", sorted(MODELS))
def test_u_runs_along_the_wider_free_axis(request, part):
    """``u`` lands on whichever free kernel axis carries the larger footprint span.

    The 1590Y's 92 x 92 mm footprint ties at nanometre precision, so its
    expectation is the documented tie-break (the lower-indexed free axis)
    instead of a skip: a silent 90-degree rotation is geometrically
    invisible to the outline on this one model, so this is the test that
    must catch it, not one that steps aside for it.
    """
    axis, box, _lid = _frame_for(request, part)
    frame = build_frame(box, axis)

    free = [index for index in range(3) if index != axis]
    if MODELS[part].footprint_mm[0] == MODELS[part].footprint_mm[1]:
        expected = min(free)
    else:
        expected = max(free, key=lambda index: box.footprint_mm[index])

    assert abs(frame.basis.u[expected]) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("part", sorted(MODELS))
def test_v_lands_on_the_free_axis_u_did_not_take(request, part):
    """``v`` always takes the one free axis ``u`` left over, square or not."""
    axis, box, _lid = _frame_for(request, part)
    frame = build_frame(box, axis)

    free = [index for index in range(3) if index != axis]
    u_axis = next(index for index in free if abs(frame.basis.u[index]) > 0.5)
    v_axis = next(index for index in free if index != u_axis)

    assert abs(frame.basis.v[v_axis]) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("part", sorted(MODELS))
def test_box_and_lid_frames_face_opposite_ways(request, part):
    """Each face is drilled from its own outside, so the same canonical +X
    must land on opposite kernel directions for box and lid — including the
    square-footprint 1590Y, where the tie-break must still agree between them.
    """
    axis, box, lid = _frame_for(request, part)
    box_frame = build_frame(box, axis)
    lid_frame = build_frame(lid, axis)

    assert pytest.approx(box_frame.basis.u, abs=1e-6) == tuple(-c for c in lid_frame.basis.u)


@pytest.mark.parametrize("part", sorted(MODELS))
def test_the_plate_thickness_is_correct_for_every_catalogued_model(request, part):
    """Guards against a wrong-face selection that only the 1590BB would miss.

    1590Y has a square 92.0 x 92.0 footprint; its height (42.0 mm) differs
    from the footprint enough that ``drill_axis`` still resolves it to one
    axis without ambiguity — asserted below alongside the plate figures.
    """
    model = MODELS[part]
    path = request.getfixturevalue(_FIXTURE_OF[part])
    document = read_step(path)
    footprint = (
        Nanometre(round(model.footprint_mm[0] * 1_000_000)),
        Nanometre(round(model.footprint_mm[1] * 1_000_000)),
    )

    axis = drill_axis(document, footprint)
    box = find_faces(select_solid(document, "box"), axis)
    lid = find_faces(select_solid(document, "lid"), axis)

    assert box.plate_nm == round(model.box_plate_mm * 1_000_000)
    assert lid.plate_nm == round(model.lid_plate_mm * 1_000_000)
    assert box.outward[axis] == -lid.outward[axis]
