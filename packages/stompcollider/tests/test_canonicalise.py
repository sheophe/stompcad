"""The canonicalisation boundary: representation only, never selection."""

from __future__ import annotations

import math

from stompcollider.canonicalise import _canonicalise_component, canonicalise
from stompcollider.model import DockData, Protrusion
from stompcollider.raw import RawBoard, RawBoards, RawComponent, RawCylinder
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration
from stompmodel.units import Nanometre


def _axis(raw: RawBoards, case: CaseRegistration) -> tuple[Nanometre, Nanometre]:
    """Canonicalise, then return the sole board's sole component's axis.

    A thin typed accessor so each test asserts on a concrete tuple rather
    than narrowing ``Protrusion | None`` inline three times over.
    """
    protrusion = canonicalise(raw, case).boards[0].components[0].protrusion
    assert isinstance(protrusion, Protrusion)
    return protrusion.axis_xy_nm


_IDENTITY = CoordinateFrame(
    origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
    u=(1.0, 0.0, 0.0),
    v=(0.0, 1.0, 0.0),
    w=(0.0, 0.0, 1.0),
)


def _case() -> CaseRegistration:
    return CaseRegistration(
        part="1590BB", face=CaseFace.BOX, model="test.stp", frame=FaceFrame(basis=_IDENTITY)
    )


def _raw_with_axis(x_mm: float, y_mm: float) -> RawBoards:
    component = RawComponent(
        designator="R1",
        axis_xy_mm=(x_mm, y_mm),
        stack=(RawCylinder(radius_mm=1.0, depth_from_tip_min_mm=0.0, depth_from_tip_max_mm=2.0),),
    )
    board = RawBoard(
        corner_a_mm=(0.0, 0.0, 0.0),
        corner_b_mm=(10.0, 10.0, 2.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(component,),
    )
    return RawBoards(boards=(board,))


def _two_boards(*, swapped: bool) -> RawBoards:
    """Two boards, geometrically ordered opposite to a naive list-index rule.

    ``far`` sits at greater x than ``near`` and must therefore be ordinal 2,
    but is placed *first* in the unswapped tuple -- an implementation that
    numbers boards by their position in ``raw.boards`` rather than by
    geometry would give ``far`` ordinal 1 here. Swapping the tuple must not
    change the result: this is the ADR-0006 control, built as two different
    input orders of the same geometry, not two calls on one input.
    """
    far = RawBoard(
        corner_a_mm=(100.0, 0.0, 0.0),
        corner_b_mm=(110.0, 10.0, 5.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(RawComponent(designator="R9", axis_xy_mm=None),),
    )
    near = RawBoard(
        corner_a_mm=(0.0, 0.0, 0.0),
        corner_b_mm=(10.0, 10.0, 5.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(RawComponent(designator="R1", axis_xy_mm=None),),
    )
    boards = (near, far) if swapped else (far, near)
    return RawBoards(boards=boards)


def test_a_measurement_scales_exactly_not_through_binary_float() -> None:
    """ADR-0003's rule. 0.1 mm has no exact binary form; the canonical value
    must be 100000 nm and not 99999 or 100001."""
    assert _axis(_raw_with_axis(0.1, 0.3), _case()) == (Nanometre(100_000), Nanometre(300_000))


def test_a_rounding_tie_scales_by_exact_decimal_not_naive_float_multiply() -> None:
    """0.1/0.3 above happen to agree with naive ``round(x * 1e6)`` -- they
    are not near a rounding boundary, so they cannot tell the two rules
    apart. 12.3456785 mm sits exactly on a half-nanometre tie: naive float
    multiplication gives 12345678 nm, but exact decimal scaling with ties
    away from zero (ADR-0003, ``nm_from_mm``) gives 12345679 nm. This is the
    fixture that actually distinguishes the two rules, not just restates
    one of them."""
    assert round(12.3456785 * 1_000_000) == 12_345_678

    assert _axis(_raw_with_axis(12.3456785, 0.0), _case()) == (Nanometre(12_345_679), Nanometre(0))


def test_canonicalise_selects_nothing() -> None:
    """The distinction from quantise(): an odd measurement stays odd. If this
    starts passing with a snapped value, a catalogue has crept in."""
    assert _axis(_raw_with_axis(3.141593, 2.718282), _case()) == (
        Nanometre(3_141_593),
        Nanometre(2_718_282),
    )


def test_boards_are_ordinalled_by_geometry_not_by_input_order() -> None:
    """ADR-0006. Two raw inputs listing the same boards in opposite orders
    must produce the same ordinals."""
    forward = canonicalise(_two_boards(swapped=False), _case())
    backward = canonicalise(_two_boards(swapped=True), _case())
    assert [b.ordinal for b in forward.boards] == [b.ordinal for b in backward.boards]
    assert [b.designators for b in forward.boards] == [b.designators for b in backward.boards]
    # Pin the actual answer, not just its stability: the nearer board (R1)
    # is ordinal 1 in both orderings, never the one that happened to be
    # listed first in ``raw.boards``.
    assert [b.designators for b in forward.boards] == [("R1",), ("R9",)]


def test_a_lone_board_has_no_ordinal_before_one() -> None:
    """A single board still gets ordinal 1 -- the smallest input a sort can
    take without a second element to compare it against."""
    data = canonicalise(_raw_with_axis(1.0, 1.0), _case())
    assert [b.ordinal for b in data.boards] == [1]


def test_every_component_and_every_cylinder_step_survives() -> None:
    """Multiple components on one board, and multiple cylinders in one
    stack, must all reach the canonical model -- an implementation that
    only handles the first of either would still pass a single-element
    fixture."""
    board = RawBoard(
        corner_a_mm=(0.0, 0.0, 0.0),
        corner_b_mm=(10.0, 10.0, 2.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(
            RawComponent(
                designator="R2",
                axis_xy_mm=(2.0, 2.0),
                stack=(
                    RawCylinder(0.5, 0.0, 1.0),
                    RawCylinder(1.0, 1.0, 3.0),
                ),
            ),
            RawComponent(designator="R1", axis_xy_mm=(1.0, 1.0), stack=(RawCylinder(0.25, 0.0, 0.5),)),
            RawComponent(designator="R3", axis_xy_mm=None),
        ),
    )
    data = canonicalise(RawBoards(boards=(board,)), _case())
    (result,) = data.boards
    assert result.designators == ("R1", "R2", "R3")
    assert [c.designator for c in result.components] == ["R1", "R2", "R3"]

    r1, r2, r3 = result.components
    assert r3.protrusion is None
    assert r1.protrusion is not None and r2.protrusion is not None
    assert len(r2.protrusion.profile.steps) == 2
    assert r2.protrusion.profile.steps == (
        (Nanometre(500_000), Nanometre(0), Nanometre(1_000_000)),
        (Nanometre(1_000_000), Nanometre(1_000_000), Nanometre(3_000_000)),
    )


def test_dockdata_carries_the_case_it_was_canonicalised_against() -> None:
    case = _case()
    data = canonicalise(_raw_with_axis(1.0, 1.0), case)
    assert isinstance(data, DockData)
    assert data.case is case


def _rotated_case() -> CaseRegistration:
    """A face frame turned -45 degrees about its own normal.

    Under the identity frame every other test in this module uses,
    projecting a bounding box's two raw extreme corners happens to agree
    with projecting all eight -- the rotation here is what makes them
    disagree, so a fixture built on it is the only way to exercise the
    eight-corner enumeration ``_sort_key`` actually performs.
    """
    theta = -math.pi / 4
    cos, sin = math.cos(theta), math.sin(theta)
    basis = CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(cos, sin, 0.0),
        v=(-sin, cos, 0.0),
        w=(0.0, 0.0, 1.0),
    )
    return CaseRegistration(
        part="1590BB", face=CaseFace.BOX, model="test.stp", frame=FaceFrame(basis=basis)
    )


def _tied_boards() -> RawBoards:
    """Two boards whose bounding boxes tie exactly on the sort key's leading
    three fields under ``_rotated_case()``, but differ in footprint.

    ``narrow`` is a 10x1 mm rectangle at the origin. ``wide`` is a 10x2 mm
    rectangle translated by (0.5, -0.5) mm -- chosen so that, once every one
    of its eight bounding-box corners is projected through the rotated
    frame, its least x and least y exactly match ``narrow``'s. Neither
    board's tying corner is one of its own two *raw* extreme corners: it
    only appears once the box's other six corners are generated and
    projected too. With the position genuinely tied, only the
    ``-footprint_nm2`` term can order them, and ``wide``'s footprint is the
    larger one, so it must be ordinal 1.
    """
    narrow = RawBoard(
        corner_a_mm=(0.0, 0.0, 0.0),
        corner_b_mm=(10.0, 1.0, 2.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(RawComponent(designator="R_NARROW", axis_xy_mm=None),),
    )
    wide = RawBoard(
        corner_a_mm=(0.5, -0.5, 0.0),
        corner_b_mm=(10.5, 1.5, 2.0),
        carrier_origin_mm=(0.0, 0.0, 0.0),
        carrier_u=(1.0, 0.0, 0.0),
        carrier_v=(0.0, 1.0, 0.0),
        carrier_w=(0.0, 0.0, 1.0),
        components=(RawComponent(designator="R_WIDE", axis_xy_mm=None),),
    )
    return RawBoards(boards=(narrow, wide))


def test_a_genuine_position_tie_breaks_on_footprint() -> None:
    """Both boards project to the same (min_x_nm, min_y_nm, min_z_nm) under
    the rotated frame -- confirmed by hand and in the fix report -- so only
    the footprint tie-break can separate them, and only the full
    eight-corner projection can discover that they are tied at all. The
    wider board must win ordinal 1."""
    data = canonicalise(_tied_boards(), _rotated_case())
    assert [b.designators for b in data.boards] == [("R_WIDE",), ("R_NARROW",)]


def _stacked(*cylinders: RawCylinder) -> tuple[tuple[Nanometre, Nanometre, Nanometre], ...]:
    """One component's canonical steps, built the way a source hands them over."""
    raw = RawComponent(designator="U1", axis_xy_mm=(0.0, 0.0), stack=cylinders)
    component = _canonicalise_component(raw)
    assert component.protrusion is not None
    return component.protrusion.profile.steps


def test_two_cylinders_that_scale_to_one_step_are_stated_once() -> None:
    """A cylinder split at its seam reaches here as two faces of one axis,
    one radius and one extent. The profile states that feature once: leaving
    both in changes the value's equality and its serialised form. Exact
    integer equality is what decides it, which is why the rule lives on this
    side of the scaling and not in the millimetres upstream.
    """
    twice = RawCylinder(1.0, 0.0, 10.0)

    assert _stacked(twice, twice) == (
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
    )


def test_two_cylinders_differing_only_below_a_nanometre_are_one_step() -> None:
    """The rule is equality of the canonical fact, not of the measurement:
    a difference the model cannot express is not a second feature."""
    assert _stacked(RawCylinder(1.0, 0.0, 10.0), RawCylinder(1.0000000004, 0.0, 10.0)) == (
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
    )


def test_two_cylinders_a_whole_nanometre_apart_are_two_steps() -> None:
    """The control beside it: a difference the model *can* express survives,
    so the rule above is deduplication and not rounding everything together."""
    assert len(_stacked(RawCylinder(1.0, 0.0, 10.0), RawCylinder(1.000001, 0.0, 10.0))) == 2


def test_the_steps_are_ordered_from_the_tip_and_not_by_the_stack() -> None:
    """The stack arrives in a kernel walk's order, which reaches no artefact
    (ADR-0006). Depth leads, so the profile reads from the tip; the deepest
    cylinder is handed over first here precisely so that preserving the
    stack's order would give a different answer.
    """
    ordered = _stacked(
        RawCylinder(3.0, 6.0, 10.0),
        RawCylinder(1.0, 0.0, 10.0),
    )

    assert ordered == (
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
        (Nanometre(3_000_000), Nanometre(6_000_000), Nanometre(10_000_000)),
    )


def test_steps_starting_at_one_depth_are_ordered_on_where_they_end() -> None:
    """The key's second component. Two steps sharing a depth-from-tip leave
    the first comparison tied, so a key of depth alone would fall back to
    whatever order the set happened to iterate in."""
    assert _stacked(
        RawCylinder(1.0, 0.0, 10.0),
        RawCylinder(3.0, 0.0, 4.0),
    ) == (
        (Nanometre(3_000_000), Nanometre(0), Nanometre(4_000_000)),
        (Nanometre(1_000_000), Nanometre(0), Nanometre(10_000_000)),
    )


def test_a_stack_handed_over_two_ways_round_gives_one_profile() -> None:
    """ADR-0006 stated directly: two spellings of one measurement agree."""
    a, b, c = RawCylinder(1.0, 0.0, 10.0), RawCylinder(3.0, 6.0, 10.0), RawCylinder(2.0, 2.0, 6.0)

    assert _stacked(a, b, c) == _stacked(c, a, b) == _stacked(b, c, a)
