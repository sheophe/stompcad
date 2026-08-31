"""The frame value's arithmetic, which the kernel layer above only builds."""

from __future__ import annotations

import math

import pytest

from stompmodel.frames import CoordinateFrame, RigidTransform
from stompmodel.units import Nanometre

#: A frame whose axes are deliberately not the kernel's own: ``u`` runs along
#: -Y and ``v`` along +Z, so a test cannot pass by ignoring the basis.
ROTATED = CoordinateFrame(
    origin_nm=(Nanometre(1_000_000), Nanometre(2_000_000), Nanometre(3_000_000)),
    u=(0.0, -1.0, 0.0),
    v=(0.0, 0.0, 1.0),
    w=(-1.0, 0.0, 0.0),
)


def _along_w(point: tuple[float, float, float], distance_mm: float) -> tuple[float, float, float]:
    """``point`` moved ``distance_mm`` off ``ROTATED``'s plane, along ``w``."""
    return (
        point[0] + distance_mm * ROTATED.w[0],
        point[1] + distance_mm * ROTATED.w[1],
        point[2] + distance_mm * ROTATED.w[2],
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
    """The round trip returns the coordinates it started from, at no depth.

    ``to_model`` places a canonical point on the frame's own plane, so the
    depth the round trip recovers must be exactly zero.
    """
    point = ROTATED.to_model(Nanometre(7_000_000), Nanometre(-4_000_000))

    assert ROTATED.to_canonical(point) == (7.0, -4.0, 0.0)


def test_to_canonical_reports_the_depth_of_a_point_above_the_plane() -> None:
    """A point displaced along ``w`` projects to that same displacement.

    Without this the depth could be hardcoded to zero and every on-plane
    test would still pass. The displacement is neither of the in-plane
    coordinates, so a projection onto the wrong axis fails here too.
    """
    on_plane = ROTATED.to_model(Nanometre(7_000_000), Nanometre(-4_000_000))
    above = _along_w(on_plane, 2.5)

    assert ROTATED.to_canonical(above) == (7.0, -4.0, 2.5)


def test_to_canonical_reports_a_negative_depth_below_the_plane() -> None:
    """Depth is signed: the opposite side of the plane reads negative.

    Checked apart from the case above, because an unsigned magnitude
    passes that one and would hide which side of the face a point sits on.
    """
    on_plane = ROTATED.to_model(Nanometre(7_000_000), Nanometre(-4_000_000))
    below = _along_w(on_plane, -2.5)

    assert ROTATED.to_canonical(below) == (7.0, -4.0, -2.5)


def test_to_canonical_returns_millimetres_not_nanometres() -> None:
    """The unit is load-bearing: ``region_bbox_nm`` rounds after its own
    minimum and maximum, so this must not round here."""
    assert ROTATED.to_canonical((1.0, 2.0, 3.5)) == (0.0, 0.5, 0.0)


def test_reframe_restates_a_point_on_another_frame() -> None:
    """A point measured against one face means something else on another.

    The target is a quarter turn about ``v`` from ``ROTATED`` and stands at
    a different origin, so the composed map is *not* its own inverse: swap
    the two frames in ``reframe`` and the answer changes. A half turn about
    a shared origin -- the pair this test used to carry -- is an involution,
    and an involution cannot fail on that swap.
    """
    target = CoordinateFrame(
        origin_nm=(Nanometre(4_000_000), Nanometre(6_000_000), Nanometre(10_000_000)),
        u=(0.0, 0.0, 1.0),
        v=(-1.0, 0.0, 0.0),
        w=(0.0, -1.0, 0.0),
    )
    here = (Nanometre(5_000_000), Nanometre(-2_000_000))
    there = (Nanometre(-9_000_000), Nanometre(3_000_000))

    assert ROTATED.reframe(*here, target) == there
    # The control on the fixture itself: the day this pair becomes its own
    # inverse again, the two directions agree and this line fails.
    assert target.reframe(*here, ROTATED) != there


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


# --------------------------------------------------------------------------
# construction guards -- each clause refused independently
# --------------------------------------------------------------------------


def test_a_non_integer_origin_component_is_refused() -> None:
    with pytest.raises(TypeError, match=r"origin_nm\[1\] must be a whole number of nanometres"):
        CoordinateFrame(
            origin_nm=(Nanometre(0), 1.5, Nanometre(0)),  # type: ignore[arg-type]
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_an_origin_with_two_components_is_refused() -> None:
    with pytest.raises(ValueError, match="origin_nm must have exactly three components"):
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0)),  # type: ignore[arg-type]
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_a_basis_vector_with_two_components_is_refused() -> None:
    with pytest.raises(ValueError, match=r"CoordinateFrame\.u must have exactly three components"):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(1.0, 0.0),  # type: ignore[arg-type]
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_a_zero_length_vector_is_refused() -> None:
    with pytest.raises(ValueError, match=r"CoordinateFrame\.u must be unit length"):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(0.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_a_non_unit_length_vector_is_refused() -> None:
    """Distinct from the zero-length case: this vector is merely too long."""
    with pytest.raises(ValueError, match=r"CoordinateFrame\.w must be unit length"):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 2.0),
        )


def test_a_non_finite_component_is_refused() -> None:
    with pytest.raises(ValueError, match=r"CoordinateFrame\.v must be finite"):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(1.0, 0.0, 0.0),
            v=(0.0, float("nan"), 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_a_non_orthogonal_pair_is_refused() -> None:
    """Both unit length, so only the orthogonality clause can catch this."""
    root_half = 2**-0.5
    with pytest.raises(
        ValueError, match=r"CoordinateFrame\.u and CoordinateFrame\.v must be orthogonal"
    ):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(1.0, 0.0, 0.0),
            v=(root_half, root_half, 0.0),
            w=(0.0, 0.0, 1.0),
        )


def test_an_otherwise_valid_left_handed_triple_is_refused() -> None:
    """Orthonormal in every pairwise sense, but ``w`` is the wrong sign --
    exactly the shape that would mirror every hole on the panel if let
    through silently."""
    with pytest.raises(ValueError, match="must equal u cross v"):
        CoordinateFrame(
            origin_nm=(Nanometre(0),) * 3,
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, -1.0),
        )


def test_a_well_formed_frame_is_the_control() -> None:
    """The guard refuses malformed frames and nothing else."""
    frame = CoordinateFrame(
        origin_nm=(Nanometre(1), Nanometre(2), Nanometre(3)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )

    assert frame.origin_nm == (1, 2, 3)


def _frame(
    origin_nm: tuple[int, int, int] = (0, 0, 0),
    u: tuple[float, float, float] = (1.0, 0.0, 0.0),
    v: tuple[float, float, float] = (0.0, 1.0, 0.0),
    w: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(origin_nm[0]), Nanometre(origin_nm[1]), Nanometre(origin_nm[2])),
        u=u, v=v, w=w,
    )


def test_to_model_depth_defaults_to_the_frame_plane() -> None:
    """The new argument is additive: omitting it must reproduce today's answer."""
    frame = _frame(origin_nm=(10_000_000, 20_000_000, 30_000_000))
    assert frame.to_model(Nanometre(1_000_000), Nanometre(2_000_000)) == (11.0, 22.0, 30.0)


def test_to_model_depth_moves_along_w_not_along_a_kernel_axis() -> None:
    """The clause the three patched call sites got right only by luck: on a
    frame whose w is not a kernel axis, a depth is a translation along w."""
    root = 2.0 ** -0.5
    frame = _frame(u=(0.0, 1.0, 0.0), v=(root, 0.0, -root), w=(-root, 0.0, -root))
    x, y, z = frame.to_model(Nanometre(0), Nanometre(0), Nanometre(1_000_000))
    assert round(x, 12) == round(-root, 12)
    assert round(y, 12) == 0.0
    assert round(z, 12) == round(-root, 12)


def test_apply_direction_ignores_the_translation() -> None:
    """A direction has no origin. to_canonical subtracting one is the defect
    Ruling 4 names; a rotation-only operation is the answer."""
    moved = _frame().translated_nm(Nanometre(10_000_000), Nanometre(0), Nanometre(0))
    motion = _frame().placement_onto(moved)
    assert motion.apply_direction((1.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)
    assert motion.apply_point((0.0, 0.0, 0.0)) == (10.0, 0.0, 0.0)


def test_placement_onto_carries_this_frame_onto_the_target() -> None:
    """The defining property, stated on all four of a frame's parts."""
    source = _frame(origin_nm=(1_000_000, 2_000_000, 3_000_000))
    target = _frame(
        origin_nm=(50_000_000, 0, 0), u=(0.0, 1.0, 0.0), v=(-1.0, 0.0, 0.0), w=(0.0, 0.0, 1.0)
    )
    motion = source.placement_onto(target)
    moved_origin = motion.apply_point((1.0, 2.0, 3.0))
    assert tuple(round(c, 9) for c in moved_origin) == (50.0, 0.0, 0.0)
    assert tuple(round(c, 9) for c in motion.apply_direction(source.u)) == target.u
    assert tuple(round(c, 9) for c in motion.apply_direction(source.w)) == target.w


def test_placement_onto_itself_is_the_identity() -> None:
    """The innocent probe: a frame already in place must not be moved."""
    frame = _frame(origin_nm=(7_000_000, 0, 0))
    motion = frame.placement_onto(frame)
    assert tuple(round(c, 12) for c in motion.apply_point((1.0, 2.0, 3.0))) == (1.0, 2.0, 3.0)


def test_placement_onto_composes_for_two_non_identity_frames() -> None:
    """The identity-self test above cannot catch an implementation that
    used only ``target`` and ignored ``self`` entirely: with an identity
    ``self``, ``R = U_target . U_self^T`` collapses to ``U_target``, so a
    buggy ``R = U_target`` implementation would pass it too. Neither frame
    here is the identity, ``self``'s basis is a 60-degree rotation about
    ``w`` (not an axis flip), and ``target``'s is a distinct axis cycle, so
    the resulting rotation is not symmetric and cannot be produced by
    dropping ``self`` from the formula."""
    root3over2 = 3.0 ** 0.5 / 2.0
    source = _frame(
        origin_nm=(1_000_000, 2_000_000, 3_000_000),
        u=(root3over2, 0.5, 0.0),
        v=(-0.5, root3over2, 0.0),
        w=(0.0, 0.0, 1.0),
    )
    target = _frame(
        origin_nm=(5_000_000, -1_000_000, 2_000_000),
        u=(0.0, 1.0, 0.0),
        v=(0.0, 0.0, 1.0),
        w=(1.0, 0.0, 0.0),
    )
    motion = source.placement_onto(target)
    moved_origin = motion.apply_point((1.0, 2.0, 3.0))
    assert tuple(round(c, 9) for c in moved_origin) == (5.0, -1.0, 2.0)
    assert tuple(round(c, 9) for c in motion.apply_direction(source.u)) == target.u
    assert tuple(round(c, 9) for c in motion.apply_direction(source.v)) == target.v
    assert tuple(round(c, 9) for c in motion.apply_direction(source.w)) == target.w


def test_rotated_about_w_keeps_the_normal_and_stays_right_handed() -> None:
    """Both clauses matter: a rotation that flipped w would still be unit."""
    turned = _frame().rotated_about_w(math.pi / 2)
    assert turned.w == (0.0, 0.0, 1.0)
    assert tuple(round(c, 12) for c in turned.u) == (0.0, 1.0, 0.0)
    # __post_init__ re-checks u x v == w, so construction proves handedness.


def test_translated_nm_moves_along_the_frames_own_axes() -> None:
    """Not along the kernel's. A frame turned 90 degrees moves sideways."""
    turned = _frame().rotated_about_w(math.pi / 2)
    moved = turned.translated_nm(Nanometre(1_000_000), Nanometre(0), Nanometre(0))
    assert tuple(int(c) for c in moved.origin_nm) == (0, 1_000_000, 0)


# --------------------------------------------------------------------------
# RigidTransform validates at construction, for CoordinateFrame's reason:
# this value reaches a kernel, and a malformed one raises there instead.
# --------------------------------------------------------------------------

_IDENTITY_ROTATION = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def test_a_well_formed_rigid_transform_is_the_control() -> None:
    """The anchor for the refusals below: this shape really does construct,
    so each one is refusing its own named defect rather than everything."""
    motion = RigidTransform(_IDENTITY_ROTATION, (1.0, 2.0, 3.0))
    assert motion.apply_point((0.0, 0.0, 0.0)) == (1.0, 2.0, 3.0)


def test_a_rotation_with_two_rows_is_refused() -> None:
    with pytest.raises(ValueError, match="three rows"):
        RigidTransform(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (0.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_a_rotation_row_with_two_components_is_refused() -> None:
    with pytest.raises(ValueError, match=r"rotation\[1\] must have exactly three"):
        RigidTransform(
            ((1.0, 0.0, 0.0), (0.0, 1.0), (0.0, 0.0, 1.0)),  # type: ignore[arg-type]
            (0.0, 0.0, 0.0),
        )


def test_a_translation_with_two_components_is_refused() -> None:
    with pytest.raises(ValueError, match="three components"):
        RigidTransform(_IDENTITY_ROTATION, (0.0, 0.0))  # type: ignore[arg-type]


def test_a_non_finite_translation_is_refused() -> None:
    with pytest.raises(ValueError, match="translation_mm must be finite"):
        RigidTransform(_IDENTITY_ROTATION, (float("nan"), 0.0, 0.0))


def test_a_non_finite_rotation_component_is_refused() -> None:
    """The one the review named: an infinity handed straight to a kernel."""
    with pytest.raises(ValueError, match=r"rotation\[0\] must be finite"):
        RigidTransform(
            ((float("inf"), 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            (0.0, 0.0, 0.0),
        )


def test_a_scaled_rotation_row_is_refused() -> None:
    """A uniform scale is not a rigid motion, however well-formed it reads."""
    with pytest.raises(ValueError, match="unit length"):
        RigidTransform(
            ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)
        )


def test_a_non_orthogonal_rotation_is_refused() -> None:
    """Each row unit length is not enough: a shear passes that clause alone."""
    root = 2.0**-0.5
    with pytest.raises(ValueError, match="must be orthogonal"):
        RigidTransform(
            ((1.0, 0.0, 0.0), (root, root, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0)
        )


def test_an_otherwise_valid_reflection_is_refused() -> None:
    """Orthonormal but left-handed: a mirror, which moves no rigid body."""
    with pytest.raises(ValueError, match="right-handed"):
        RigidTransform(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)), (0.0, 0.0, 0.0)
        )


def test_placement_onto_still_produces_a_transform_this_check_admits() -> None:
    """The production builder against the new gate: two real frames, one of
    them turned, and the motion between them constructs rather than raising."""
    source = _frame(origin_nm=(1_000_000, 2_000_000, 3_000_000))
    target = _frame(
        origin_nm=(50_000_000, 0, 0), u=(0.0, 1.0, 0.0), v=(-1.0, 0.0, 0.0), w=(0.0, 0.0, 1.0)
    )
    assert source.placement_onto(target).apply_direction(source.u) == target.u
