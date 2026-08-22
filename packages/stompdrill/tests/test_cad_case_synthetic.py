"""Synthetic case.py tests that need OCP but no downloaded Hammond model.

Unmarked deliberately: ``tests/test_cad_case.py`` carries a module-level
``pytestmark = pytest.mark.hammond`` that would skip these by default, but
nothing here needs a cached model, so they belong in the default suite.
"""

from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="needs stompdrill[step]")

from stompdrill.cad.case import find_faces  # noqa: E402
from stompdrill.errors import StompdrillError  # noqa: E402
from stompgeom.step import StepSolid  # noqa: E402


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
    solid = StepSolid(name="test-cube", shape=cube, unit_mm=1.0)

    with pytest.raises(StompdrillError, match=r"test-cube has 2 planar levels.*0\.0000, 50\.0000"):
        find_faces(solid, axis=1)
