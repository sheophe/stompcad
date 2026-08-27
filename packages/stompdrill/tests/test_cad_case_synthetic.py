"""Synthetic case.py tests that need OCP but no downloaded Hammond model.

Unmarked deliberately: ``tests/test_cad_case.py`` carries a module-level
``pytestmark = pytest.mark.hammond`` that would skip these by default, but
nothing here needs a cached model, so they belong in the default suite.
"""

from __future__ import annotations

import pytest

from stompdrill.cad.case import Faces, build_frame, find_faces
from stompdrill.errors import StompdrillError
from stompgeom.step import StepSolid
from stompmodel.units import Nanometre


def test_build_frame_puts_u_on_the_larger_of_1590lbs_two_catalogue_dimensions():
    """ADR-0007's narrowing paragraph (T15): the reconciliation assumes
    ``build_frame`` puts ``u`` on the model's larger measured in-plane span.
    Checked here against the catalogue's own asymmetric ``1590LB`` figures
    (50.55 x 50.60 mm) fed directly as ``Faces.footprint_mm`` -- the only
    inputs ``build_frame`` reads for axis selection -- because the real
    cached model does not resolve that 0.05 mm difference at all (see
    ``test_cad_case.py``'s real-model test, which is why this is fed rather
    than measured from a constructed solid).
    """
    faces = Faces(
        inner=None,
        plate_nm=Nanometre(0),
        outward=(0.0, -1.0, 0.0),
        drilled_position_mm=0.0,
        inner_position_mm=0.0,
        footprint_mm=(50.55, 0.0, 50.60),
    )

    frame = build_frame(faces, axis=1)

    free = [index for index in range(3) if index != 1]
    u_axis = next(index for index in free if abs(frame.basis.u[index]) > 0.5)
    assert faces.footprint_mm[u_axis] == pytest.approx(50.60)


def test_a_closed_solid_has_no_unambiguous_drilled_face():
    """A solid with no open end presents two candidate plates, not one.

    Both ends of a plain cuboid sit at the solid's own bounding-box extreme,
    each facing outward on its own side, so the solid-extreme test cannot
    single one out the way it does for a Hammond box or lid -- those narrow
    to one candidate only because their open end is a rim that ``_plates``
    removes first. A closed block has no rim to remove: refusing to guess
    which end is drilled is the correct answer here, not a gap to close.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    cube = BRepPrimAPI_MakeBox(100.0, 50.0, 20.0).Shape()
    solid = StepSolid(name="test-cube", shape=cube)

    with pytest.raises(StompdrillError, match=r"test-cube has 2 planar levels.*0\.0000, 50\.0000"):
        find_faces(solid, axis=1)


def test_a_normal_one_ulp_short_of_unit_faces_the_same_way_as_a_unit_normal():
    """OCC reports an axis-aligned normal as -0.9999999999999993 on real
    board geometry, against -1.0 for the neighbouring faces of the same
    plane. Both are the same direction, and the sign says so exactly, so
    neither a grouping key nor an equality test can treat them as two.
    """
    from stompdrill.cad.case import _outward_sign

    assert _outward_sign(-0.9999999999999993, False) == -1
    assert _outward_sign(-1.0, False) == -1
    assert _outward_sign(0.9999999999999993, False) == 1
    assert _outward_sign(1.0, False) == 1


def test_the_sign_turns_with_the_face_orientation_as_well_as_the_component():
    """Both inputs matter. A test fixing only the component would pass on
    an implementation that ignored orientation, and the reverse.
    """
    from stompdrill.cad.case import _outward_sign

    assert _outward_sign(1.0, True) == -1
    assert _outward_sign(-1.0, True) == 1
    assert _outward_sign(1.0, False) == 1
    assert _outward_sign(-1.0, False) == -1


def test_two_faces_of_one_plane_whose_normals_differ_in_the_last_bits_are_one_level():
    """The defect this guards: keying a level on the raw component split a
    single physical plane into two levels, so its area was reported in
    parts. Areas differ from each other and from their sum, so a split
    cannot pass by arithmetic coincidence.
    """
    from stompdrill.cad.case import _levels, _outward_sign

    planes = [
        (58.89, -37.5, _outward_sign(-1.0, False), object()),
        (39.26, -37.5, _outward_sign(-0.9999999999999993, False), object()),
    ]

    levels = _levels(planes)

    assert len(levels) == 1
    assert levels[0].area == 58.89 + 39.26
    assert levels[0].outward == -1


def test_the_outward_normal_a_frame_is_built_from_is_exactly_unit():
    """``Faces.outward`` reaches ``build_frame`` as the ``w`` basis vector,
    and ``CoordinateFrame`` checks unit length only to a tolerance far
    coarser than the drift a raw kernel component carries -- so the guard
    cannot catch it and the value must be exact at the source.
    """
    from stompdrill.cad.case import _outward_sign

    for component in (-0.9999999999999993, -1.0, 1.0, 0.9999999999999993):
        for reversed_face in (False, True):
            assert abs(float(_outward_sign(component, reversed_face))) == 1.0
