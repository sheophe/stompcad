"""The play area: relief versus structure, erosion, and containment."""

from __future__ import annotations

import pytest

pytest.importorskip("OCP", reason="needs aidrill[step]")

from aidrill.cad.case import build_frame, drill_axis, find_faces, select_solid  # noqa: E402
from aidrill.cad.region import build_region, classify_bounds, contains  # noqa: E402
from aidrill.cad.step import read_step  # noqa: E402
from aidrill.units import Nanometre  # noqa: E402

pytestmark = pytest.mark.hammond

FOOTPRINT = (Nanometre(119_500_000), Nanometre(94_000_000))
MM = 1_000_000


def nm(value_mm: float) -> Nanometre:
    """A canonical-millimetre probe point as whole nanometres."""
    return Nanometre(round(value_mm * MM))


@pytest.fixture(scope="module")
def box(hammond_bb):
    document = read_step(hammond_bb)
    axis = drill_axis(document, FOOTPRINT)
    faces = find_faces(select_solid(document, "box"), axis)
    return axis, faces, build_frame(faces, axis)


def test_the_cast_lettering_is_relief_at_the_default_margin(box):
    """13 letters stand 0.50 mm proud; at a 1.0 mm margin none is structure."""
    axis, faces, _ = box

    structure, relief = classify_bounds(faces.inner, axis, Nanometre(1 * MM))

    assert len(relief) == 13
    assert structure == []


def test_the_same_lettering_is_structure_below_its_own_height(box):
    """Sweeping the margin past 0.50 mm must flip every letter to structure.

    A real casting cannot place a feature at exactly `margin - 0.01`, so the
    parameter moves instead of the geometry. This is the boundary test.
    """
    axis, faces, _ = box

    structure, relief = classify_bounds(faces.inner, axis, nm(0.4))

    assert len(structure) == 13
    assert relief == []


def test_the_threshold_is_the_margin_and_not_a_hard_coded_height(box):
    axis, faces, _ = box

    lenient, _ = classify_bounds(faces.inner, axis, nm(0.6))
    strict, _ = classify_bounds(faces.inner, axis, nm(0.4))

    assert len(strict) > len(lenient)


def test_a_hole_in_clear_space_is_inside_the_region(box):
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, Nanometre(1 * MM))
    x, y = BB_PROBES["clear"]

    assert contains(region, frame, axis, nm(x), nm(y), Nanometre(3 * MM), Nanometre(1 * MM))


def test_a_hole_over_the_cast_lettering_is_inside_the_region(box):
    """Drilling away part of the word HAMMOND is legal; this is the false positive."""
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, Nanometre(1 * MM))
    x, y = BB_PROBES["relief"]

    assert contains(region, frame, axis, nm(x), nm(y), Nanometre(1 * MM), Nanometre(1 * MM))


def test_the_same_hole_is_outside_the_region_below_the_lettering_height(box):
    """Once the letters count as structure, the region must lose them."""
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, nm(0.4))
    x, y = BB_PROBES["relief"]

    assert not contains(region, frame, axis, nm(x), nm(y), Nanometre(1 * MM), nm(0.4))


def test_a_hole_in_a_notched_corner_is_outside_the_region(box):
    """The bosses notch the flat face, so no computation has to exclude them."""
    from tests.hammond import BB_PROBES

    axis, faces, frame = box
    region = build_region(faces.inner, axis, Nanometre(1 * MM))
    x, y = BB_PROBES["boss"]

    assert not contains(region, frame, axis, nm(x), nm(y), Nanometre(2 * MM), Nanometre(1 * MM))


def test_the_margin_and_not_only_the_radius_decides_the_edge(box):
    """A bit that fits geometrically must still be refused inside the margin.

    The floor's outline reaches x = 55.33; a 1 mm bit at x = 53.8 clears it by
    0.53 mm, so a 0.1 mm margin admits it and a 3 mm margin must not.
    """
    axis, faces, frame = box
    region = build_region(faces.inner, axis, Nanometre(1 * MM))
    x = nm(53.8)

    generous = contains(region, frame, axis, x, Nanometre(0), Nanometre(1 * MM), nm(0.1))
    tight = contains(region, frame, axis, x, Nanometre(0), Nanometre(1 * MM), Nanometre(3 * MM))

    assert generous
    assert not tight
