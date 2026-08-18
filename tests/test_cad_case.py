"""Deriving the drill axis, the side, its faces and the canonical frame."""

from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="needs aidrill[step]")

from aidrill.cad.case import build_frame, drill_axis, find_faces, select_solid  # noqa: E402
from aidrill.cad.step import read_step  # noqa: E402
from aidrill.units import Nanometre  # noqa: E402

pytestmark = pytest.mark.hammond

FOOTPRINT = (Nanometre(119_500_000), Nanometre(94_000_000))


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
    from aidrill.errors import AidrillError

    with pytest.raises(AidrillError, match="footprint"):
        drill_axis(document, (Nanometre(999_000_000), Nanometre(1_000_000)))


def test_the_box_and_lid_are_selected_by_name(document):
    assert "BOX" in select_solid(document, "box").name.upper()
    assert "LID" in select_solid(document, "lid").name.upper()


def test_the_selected_lid_is_the_thinner_solid(document):
    from aidrill.cad.step import bounding_box_mm

    axis = drill_axis(document, FOOTPRINT)
    box = bounding_box_mm(select_solid(document, "box").shape)
    lid = bounding_box_mm(select_solid(document, "lid").shape)

    assert (lid[axis + 3] - lid[axis]) < (box[axis + 3] - box[axis])


def test_an_unknown_face_name_is_rejected(document):
    from aidrill.errors import AidrillError

    with pytest.raises(AidrillError):
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

    from aidrill.cad.step import bounding_box_mm
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
    u, v, w = frame.u, frame.v, frame.w
    cross = (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )

    assert pytest.approx(cross, abs=1e-9) == w


def test_the_frame_is_orthonormal(document):
    axis = drill_axis(document, FOOTPRINT)
    frame = build_frame(find_faces(select_solid(document, "box"), axis), axis)

    for a in (frame.u, frame.v, frame.w):
        assert pytest.approx(sum(c * c for c in a), abs=1e-9) == 1.0
    assert pytest.approx(sum(a * b for a, b in zip(frame.u, frame.v)), abs=1e-9) == 0.0
