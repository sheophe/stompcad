"""The frame value's arithmetic, which the kernel layer above only builds."""

from __future__ import annotations

from stompmodel.frames import CoordinateFrame
from stompmodel.units import Nanometre

#: A frame whose axes are deliberately not the kernel's own: ``u`` runs along
#: -Y and ``v`` along +Z, so a test cannot pass by ignoring the basis.
ROTATED = CoordinateFrame(
    origin_nm=(Nanometre(1_000_000), Nanometre(2_000_000), Nanometre(3_000_000)),
    u=(0.0, -1.0, 0.0),
    v=(0.0, 0.0, 1.0),
    w=(1.0, 0.0, 0.0),
)


def test_to_model_returns_the_origin_for_the_frame_origin() -> None:
    """Canonical (0, 0) is the frame's own origin, in millimetres."""
    assert ROTATED.to_model(Nanometre(0), Nanometre(0)) == (1.0, 2.0, 3.0)


def test_to_model_walks_u_for_x() -> None:
    """A canonical x displaces along ``u``, not along the kernel's own X."""
    assert ROTATED.to_model(Nanometre(5_000_000), Nanometre(0)) == (1.0, -3.0, 3.0)


def test_to_model_walks_v_for_y() -> None:
    """A canonical y displaces along ``v``. Checked apart from x so that a
    formula using one axis for both still fails one of these two."""
    assert ROTATED.to_model(Nanometre(0), Nanometre(5_000_000)) == (1.0, 2.0, 8.0)


def test_to_canonical_inverts_to_model() -> None:
    """The round trip returns the coordinates it started from."""
    point = ROTATED.to_model(Nanometre(7_000_000), Nanometre(-4_000_000))

    assert ROTATED.to_canonical(point) == (7.0, -4.0)


def test_to_canonical_returns_millimetres_not_nanometres() -> None:
    """The unit is load-bearing: ``region_bbox_nm`` rounds after its own
    minimum and maximum, so this must not round here."""
    assert ROTATED.to_canonical((1.0, 2.0, 3.5)) == (0.0, 0.5)


def test_reframe_restates_a_point_on_another_frame() -> None:
    """A point measured against one face means something else on another.

    The target is the same origin viewed from the opposite side, so a
    canonical x of +5 mm on the source reads as -5 mm on the target.
    """
    target = CoordinateFrame(
        origin_nm=ROTATED.origin_nm, u=(0.0, 1.0, 0.0), v=(0.0, 0.0, 1.0), w=(-1.0, 0.0, 0.0)
    )

    assert ROTATED.reframe(Nanometre(5_000_000), Nanometre(0), target) == (
        Nanometre(-5_000_000),
        Nanometre(0),
    )


def test_reframe_onto_the_same_frame_is_the_identity() -> None:
    """The degenerate case, so the conversion cannot silently drop a term."""
    assert ROTATED.reframe(Nanometre(3_000_000), Nanometre(9_000_000), ROTATED) == (
        Nanometre(3_000_000),
        Nanometre(9_000_000),
    )


def test_the_frame_is_frozen() -> None:
    """A registration is a value; a transform returns a replacement."""
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        ROTATED.u = (1.0, 0.0, 0.0)  # type: ignore[misc]


def test_a_face_frame_wraps_a_basis() -> None:
    """The wrapping is visible at the call site, which is the point of it."""
    from stompmodel.frames import FaceFrame

    assert FaceFrame(basis=ROTATED).basis is ROTATED


def test_a_face_frame_is_not_a_coordinate_frame() -> None:
    """Composition, not inheritance: a face frame carries a meaning that a
    bare transform does not, so it must not substitute for one silently."""
    from stompmodel.frames import FaceFrame

    assert not isinstance(FaceFrame(basis=ROTATED), CoordinateFrame)
