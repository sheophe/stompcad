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
