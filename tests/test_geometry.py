"""Tests for :mod:`aidrill.geometry`.

Written before the module exists, per the TDD method in docs/PLAN.md.

The interesting tests here are the *negative* ones. Recovering a circle from
four cubics is easy; the whole value of ``fit_circle`` is that it refuses
ellipses and rounded rectangles, which are the two things a panel drawing is
full of and which a naive bounding-box fit happily mistakes for holes.
"""

from __future__ import annotations

import math

import pytest

from aidrill.geometry import (
    IDENTITY,
    KAPPA,
    PT_PER_MM,
    Circle,
    ClosePath,
    CurveTo,
    LineTo,
    Matrix,
    MoveTo,
    SubPath,
    fit_circle,
    multiply,
    pt_to_mm,
    transform,
)
from aidrill.tolerance import SLACK, within

Point = tuple[float, float]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def circle_path(
    cx: float,
    cy: float,
    r: float,
    *,
    ry: float | None = None,
    kappa: float = KAPPA,
    closed: bool = True,
) -> SubPath:
    """Build the four-cubic path Illustrator writes for a circle.

    ``ry`` different from ``r`` gives an ellipse; ``kappa`` different from
    :data:`KAPPA` gives a rounded square (controls pushed out towards the
    corners). Both are the shapes ``fit_circle`` has to reject, and generating
    them from the same code as the good case keeps the negative tests honest.
    """
    b = r if ry is None else ry
    kx, ky = kappa * r, kappa * b
    right = (cx + r, cy)
    top = (cx, cy + b)
    left = (cx - r, cy)
    bottom = (cx, cy - b)
    segments: list[object] = [
        MoveTo(right),
        CurveTo((cx + r, cy + ky), (cx + kx, cy + b), top),
        CurveTo((cx - kx, cy + b), (cx - r, cy + ky), left),
        CurveTo((cx - r, cy - ky), (cx - kx, cy - b), bottom),
        CurveTo((cx + kx, cy - b), (cx + r, cy - ky), right),
    ]
    if closed:
        segments.append(ClosePath())
    return SubPath(tuple(segments))  # type: ignore[arg-type]


def cusp_path(cx: float, cy: float, r: float, *, outward: bool = True) -> SubPath:
    """Four cubics whose controls are the right *length* and the wrong direction.

    Every control sits exactly ``KAPPA * r`` from its anchor — where a circle
    puts it — but rotated 90 degrees, so the offset runs along the radius
    instead of along the tangent. The anchors are a circle's anchors and the
    offsets are a circle's offsets; only their direction differs, and what it
    draws is a four-cornered cusp, not a hole.

    This is the shape the perpendicularity half of the kappa check exists for:
    varying the offset *length* (a rounded square) never exercises it.
    """
    k = (KAPPA * r) if outward else -(KAPPA * r)
    right, top = (cx + r, cy), (cx, cy + r)
    left, bottom = (cx - r, cy), (cx, cy - r)

    def radial(anchor: Point) -> Point:
        dx, dy = anchor[0] - cx, anchor[1] - cy
        scale = k / math.hypot(dx, dy)
        return (anchor[0] + dx * scale, anchor[1] + dy * scale)

    return SubPath(
        (
            MoveTo(right),
            CurveTo(radial(right), radial(top), top),
            CurveTo(radial(top), radial(left), left),
            CurveTo(radial(left), radial(bottom), bottom),
            CurveTo(radial(bottom), radial(right), right),
            ClosePath(),
        )
    )


def star_path(r: float, cx: float = 0.0, cy: float = 0.0) -> SubPath:
    """A circle's four cubics with *both* control offsets reflected through their anchor.

    Every offset keeps its length and its (zero) radial component, so the length
    half and the perpendicularity half of the kappa check both see a perfect
    circle. Only the sense along the tangent is reversed, which turns each
    quarter arc inside out and draws a four-petal star with a cusp at every
    anchor. It is the shape that gets through when the check never asks which
    way the tangential component points.
    """
    base = circle_path(cx, cy, r)
    segments: list[object] = [base.segments[0]]
    current: Point = base.segments[0].point  # type: ignore[union-attr]
    for segment in base.segments[1:]:
        if isinstance(segment, CurveTo):
            segments.append(
                CurveTo(
                    (2 * current[0] - segment.c1[0], 2 * current[1] - segment.c1[1]),
                    (2 * segment.end[0] - segment.c2[0], 2 * segment.end[1] - segment.c2[1]),
                    segment.end,
                )
            )
            current = segment.end
        else:
            segments.append(segment)
    return SubPath(tuple(segments))  # type: ignore[arg-type]


def control_offsets(path: SubPath) -> list[float]:
    """Distance from each control point to the anchor it belongs to."""
    offsets: list[float] = []
    current: Point | None = None
    for segment in path.segments:
        if isinstance(segment, MoveTo):
            current = segment.point
        elif isinstance(segment, CurveTo):
            assert current is not None
            offsets.append(math.dist(current, segment.c1))
            offsets.append(math.dist(segment.end, segment.c2))
            current = segment.end
    return offsets


def _offset_vectors(path: SubPath) -> list[Point]:
    """Each control point as a vector from the anchor it belongs to."""
    vectors: list[Point] = []
    current: Point | None = None
    for segment in path.segments:
        if isinstance(segment, MoveTo):
            current = segment.point
        elif isinstance(segment, CurveTo):
            assert current is not None
            vectors.append((segment.c1[0] - current[0], segment.c1[1] - current[1]))
            vectors.append((segment.c2[0] - segment.end[0], segment.c2[1] - segment.end[1]))
            current = segment.end
    return vectors


def mapped(path: SubPath, m: Matrix) -> SubPath:
    """Push every point of ``path`` through ``m``, as a CTM would."""

    def seg(s):
        if isinstance(s, MoveTo):
            return MoveTo(transform(m, *s.point))
        if isinstance(s, LineTo):
            return LineTo(transform(m, *s.point))
        if isinstance(s, CurveTo):
            return CurveTo(
                transform(m, *s.c1), transform(m, *s.c2), transform(m, *s.end)
            )
        return s

    return SubPath(tuple(seg(s) for s in path.segments))


def rotation(degrees: float) -> Matrix:
    t = math.radians(degrees)
    return (math.cos(t), math.sin(t), -math.sin(t), math.cos(t), 0.0, 0.0)


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------


class TestMatrix:
    def test_identity_is_the_identity_matrix(self) -> None:
        assert IDENTITY == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def test_identity_is_neutral_on_both_sides(self) -> None:
        m: Matrix = (2.0, 0.5, -0.25, 3.0, 10.0, -4.0)
        assert multiply(m, IDENTITY) == pytest.approx(m)
        assert multiply(IDENTITY, m) == pytest.approx(m)

    def test_identity_leaves_a_point_alone(self) -> None:
        assert transform(IDENTITY, 3.0, -7.0) == pytest.approx((3.0, -7.0))

    def test_transform_uses_pdf_component_order(self) -> None:
        # (a, b, c, d, e, f) -> (a*x + c*y + e, b*x + d*y + f)
        m: Matrix = (2.0, 3.0, 5.0, 7.0, 11.0, 13.0)
        assert transform(m, 1.0, 1.0) == pytest.approx((2 + 5 + 11, 3 + 7 + 13))

    def test_multiply_applies_the_left_matrix_first(self) -> None:
        m: Matrix = (2.0, 0.0, 0.0, 2.0, 0.0, 0.0)  # scale x2
        n: Matrix = (1.0, 0.0, 0.0, 1.0, 10.0, 20.0)  # translate
        # m then n: scale first, then translate -> (2*3 + 10, 2*4 + 20)
        assert transform(multiply(m, n), 3.0, 4.0) == pytest.approx((16.0, 28.0))

    def test_multiply_agrees_with_applying_the_two_transforms_in_turn(self) -> None:
        m: Matrix = (1.5, 0.25, -0.5, 2.0, 3.0, -1.0)
        n: Matrix = (0.5, -1.0, 2.0, 0.75, -6.0, 8.0)
        for x, y in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (-13.5, 42.25)]:
            assert transform(multiply(m, n), x, y) == pytest.approx(
                transform(n, *transform(m, x, y))
            )

    def test_multiplication_does_not_commute(self) -> None:
        scale: Matrix = (2.0, 0.0, 0.0, 2.0, 0.0, 0.0)
        translate: Matrix = (1.0, 0.0, 0.0, 1.0, 10.0, 0.0)
        assert multiply(scale, translate) != multiply(translate, scale)

    def test_cm_concatenates_before_the_existing_ctm(self) -> None:
        """A PDF ``cm`` prepends: new_ctm = multiply(cm_matrix, current_ctm).

        This is the operator semantics task C depends on. With a page CTM that
        scales by 2, a nested ``cm`` translating by (5, 0) must move a point by
        10 device units, not 5 -- the translation happens in the *inner* space.
        """
        page_ctm: Matrix = (2.0, 0.0, 0.0, 2.0, 0.0, 0.0)
        cm: Matrix = (1.0, 0.0, 0.0, 1.0, 5.0, 0.0)
        ctm = multiply(cm, page_ctm)
        assert transform(ctm, 0.0, 0.0) == pytest.approx((10.0, 0.0))
        assert transform(ctm, 1.0, 1.0) == pytest.approx((12.0, 2.0))

    def test_nested_cm_stack_composes(self) -> None:
        ctm = IDENTITY
        ctm = multiply((1.0, 0.0, 0.0, 1.0, 100.0, 50.0), ctm)  # q .. cm translate
        ctm = multiply((3.0, 0.0, 0.0, 3.0, 0.0, 0.0), ctm)  # q .. cm scale
        # the point is scaled in the inner space, then translated by the outer
        assert transform(ctm, 2.0, 1.0) == pytest.approx((106.0, 53.0))


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


class TestSubPath:
    def test_anchors_are_on_curve_points_only(self) -> None:
        path = SubPath(
            (
                MoveTo((0.0, 0.0)),
                CurveTo((1.0, 9.0), (2.0, 9.0), (3.0, 0.0)),
                LineTo((4.0, 1.0)),
                ClosePath(),
            )
        )
        assert path.anchors == ((0.0, 0.0), (3.0, 0.0), (4.0, 1.0))

    def test_bbox_of_a_rectangle(self) -> None:
        path = SubPath(
            (
                MoveTo((10.0, 20.0)),
                LineTo((30.0, 20.0)),
                LineTo((30.0, 45.0)),
                LineTo((10.0, 45.0)),
                ClosePath(),
            )
        )
        assert path.bbox == pytest.approx((10.0, 20.0, 30.0, 45.0))

    def test_bbox_of_a_circle_path_is_its_extremes(self) -> None:
        assert circle_path(-40.0, 18.0, 3.5).bbox == pytest.approx(
            (-43.5, 14.5, -36.5, 21.5)
        )

    def test_bbox_ignores_control_points(self) -> None:
        """Control points sit outside the curve; counting them inflates the box.

        The four anchors of an Illustrator circle already sit on its extremes,
        so anchors alone give the exact box for every shape this library reads.
        """
        path = SubPath((MoveTo((0.0, 0.0)), CurveTo((0.0, 100.0), (10.0, 100.0), (10.0, 0.0))))
        assert path.bbox == pytest.approx((0.0, 0.0, 10.0, 0.0))

    def test_bbox_of_a_pathless_subpath_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            SubPath(()).bbox

    def test_subpath_is_frozen(self) -> None:
        path = circle_path(0.0, 0.0, 1.0)
        with pytest.raises(Exception):
            path.segments = ()  # type: ignore[misc]


# --------------------------------------------------------------------------
# circle fitting
# --------------------------------------------------------------------------


class TestFitCircle:
    def test_recovers_a_synthetic_circle_exactly(self) -> None:
        found = fit_circle(circle_path(-40.0, 18.0, 3.5))
        assert found is not None
        assert found.cx == pytest.approx(-40.0, abs=1e-9)
        assert found.cy == pytest.approx(18.0, abs=1e-9)
        assert found.diameter == pytest.approx(7.0, abs=1e-9)

    def test_returns_a_frozen_circle_value(self) -> None:
        found = fit_circle(circle_path(0.0, 0.0, 1.0))
        assert isinstance(found, Circle)
        with pytest.raises(Exception):
            found.cx = 5.0  # type: ignore[misc]

    def test_recovers_a_circle_through_a_translate_and_scale_ctm(self) -> None:
        ctm: Matrix = (PT_PER_MM, 0.0, 0.0, PT_PER_MM, 200.0, 400.0)
        found = fit_circle(mapped(circle_path(-40.0, 18.0, 3.5), ctm))
        assert found is not None
        assert (found.cx, found.cy) == pytest.approx(transform(ctm, -40.0, 18.0), abs=1e-9)
        assert found.diameter == pytest.approx(7.0 * PT_PER_MM, abs=1e-9)

    def test_recovers_a_circle_under_rotation(self) -> None:
        """A rotated circle is still a circle.

        Fitting from the *axis-aligned* bounding box would report a diameter of
        2r*cos(45 deg) here. Anchor radii are rotation invariant, so they don't.
        """
        ctm = rotation(37.0)
        found = fit_circle(mapped(circle_path(10.0, -5.0, 2.5), ctm))
        assert found is not None
        assert (found.cx, found.cy) == pytest.approx(transform(ctm, 10.0, -5.0), abs=1e-9)
        assert found.diameter == pytest.approx(5.0, abs=1e-9)

    def test_recovers_a_circle_drawn_the_other_way_round(self) -> None:
        """A mirroring CTM reverses the direction of travel; a circle survives it.

        Illustrator writes its circles anticlockwise, but a ``cm`` with a
        negative determinant — a flipped placed group, an ``-1 0 0 1`` mirror —
        hands the fitter a clockwise one. Every control offset then points the
        other way, so a direction check that assumes one sense would reject a
        perfectly good hole.
        """
        mirror: Matrix = (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        found = fit_circle(mapped(circle_path(10.0, -5.0, 2.5), mirror))
        assert found is not None
        assert (found.cx, found.cy) == pytest.approx((-10.0, -5.0), abs=1e-9)
        assert found.diameter == pytest.approx(5.0, abs=1e-9)

    def test_open_circle_path_without_closepath_still_fits(self) -> None:
        assert fit_circle(circle_path(0.0, 0.0, 4.0, closed=False)) is not None

    # -- rejections --------------------------------------------------------

    def test_rejects_an_ellipse(self) -> None:
        assert fit_circle(circle_path(0.0, 0.0, 10.0, ry=9.0)) is None

    def test_rejects_a_circle_squashed_by_a_non_uniform_ctm(self) -> None:
        squash: Matrix = (1.0, 0.0, 0.0, 0.8, 0.0, 0.0)
        assert fit_circle(mapped(circle_path(0.0, 0.0, 5.0), squash)) is None

    def test_rejects_a_four_cubic_rounded_square(self) -> None:
        """The important negative case.

        A rounded square drawn as four cubics has square anchors on a square
        bounding box -- identical to a circle by every test except the control
        point offsets. Only the kappa check separates them.
        """
        assert fit_circle(circle_path(0.0, 0.0, 5.0, kappa=0.75)) is None

    def test_rejects_a_rounded_square_with_understated_controls(self) -> None:
        assert fit_circle(circle_path(0.0, 0.0, 5.0, kappa=0.35)) is None

    def test_rejects_controls_rotated_into_the_radius(self) -> None:
        """The other half of the kappa check: direction, not just length.

        A rounded square gets caught on offset *length*. This shape does not:
        its controls are ``KAPPA * r`` from their anchors to the last bit, and
        its anchors are literally a circle's anchors. Only the perpendicularity
        test separates the arc from the cusp.
        """
        path = cusp_path(0.0, 0.0, 5.0)

        # the length half of the check sees nothing wrong here
        assert len(control_offsets(path)) == 8
        assert all(within(d, KAPPA * 5.0, SLACK) for d in control_offsets(path))
        # nor does anything before it: same anchors as the real circle
        assert path.anchors == circle_path(0.0, 0.0, 5.0).anchors

        assert fit_circle(path) is None

    def test_rejects_controls_rotated_into_the_radius_pointing_inward(self) -> None:
        """Same cusp, controls folded towards the centre instead of away."""
        path = cusp_path(0.0, 0.0, 5.0, outward=False)
        assert all(within(d, KAPPA * 5.0, SLACK) for d in control_offsets(path))
        assert fit_circle(path) is None

    def test_rejects_a_cusped_star(self) -> None:
        """The third half of the kappa check: direction *along* the tangent.

        ``cusp_path`` turns the offsets onto the radius, which the
        perpendicularity test catches. This shape does not touch the radius at
        all — it reverses the offsets, so each one stays exactly ``KAPPA * r``
        long and exactly perpendicular to its anchor's radius, and only its
        sense along the direction of travel is wrong. Every test before this
        one sees a textbook circle; what it draws is a four-petal star with an
        inward cusp at every anchor, and drilling it would be a 7 mm hole that
        is not there.
        """
        path = star_path(3.5)
        real = circle_path(0.0, 0.0, 3.5)

        # nothing before the direction test can tell the two apart
        assert path.anchors == real.anchors
        assert control_offsets(path) == pytest.approx(control_offsets(real))
        for offset, reference in zip(_offset_vectors(path), _offset_vectors(real)):
            # same length, same (zero) radial component: exactly negated
            assert offset == pytest.approx((-reference[0], -reference[1]))

        assert fit_circle(real) is not None
        assert fit_circle(path) is None

    def test_rejects_a_cusped_star_wherever_it_is_drawn(self) -> None:
        """Not an artefact of sitting on the origin, and not of one radius."""
        assert fit_circle(star_path(12.5, cx=-40.0, cy=18.0)) is None
        assert fit_circle(mapped(star_path(3.5), rotation(37.0))) is None

    def test_rejects_a_square_encoded_as_four_cubics(self) -> None:
        """Controls collapsed onto their anchors: four straight diagonals."""
        real = circle_path(0.0, 0.0, 5.0)
        starts = [(5.0, 0.0), (0.0, 5.0), (-5.0, 0.0), (0.0, -5.0)]
        flat = SubPath(
            (real.segments[0],)
            + tuple(
                CurveTo(start, s.end, s.end)  # type: ignore[union-attr]
                for start, s in zip(starts, real.segments[1:5])
            )
            + (ClosePath(),)
        )
        assert flat.anchors == real.anchors
        assert fit_circle(flat) is None

    def test_rejects_a_circle_sheared_by_a_ctm(self) -> None:
        shear: Matrix = (1.0, 0.0, 0.5, 1.0, 0.0, 0.0)
        assert fit_circle(mapped(circle_path(0.0, 0.0, 5.0), shear)) is None

    def test_rejects_an_ellipse_anchored_on_the_diagonals(self) -> None:
        """An axis test would miss this one; the anchor radii do not."""
        oval = mapped(circle_path(0.0, 0.0, 10.0, ry=8.0), rotation(45.0))
        assert fit_circle(oval) is None

    def test_rejects_a_trailing_second_subpath(self) -> None:
        """Two subpaths in one ``SubPath`` are the caller's bug, not a circle.

        The four cubics on their own fit perfectly; without the guard the stray
        move would be ignored and a compound shape would be drilled as a hole.
        """
        path = circle_path(0.0, 0.0, 5.0, closed=False)
        assert fit_circle(path) is not None
        assert fit_circle(SubPath(path.segments + (MoveTo((99.0, 99.0)),))) is None

    def test_rejects_a_curve_before_any_moveto(self) -> None:
        """A stream fragment that starts mid-path has no start point to pair."""
        path = circle_path(0.0, 0.0, 5.0)
        assert fit_circle(SubPath(path.segments[1:])) is None

    def test_rejects_an_eight_segment_rounded_rectangle(self) -> None:
        r, k = 2.0, KAPPA * 2.0
        x0, y0, x1, y1 = -20.0, -10.0, 20.0, 10.0
        path = SubPath(
            (
                MoveTo((x0 + r, y0)),
                LineTo((x1 - r, y0)),
                CurveTo((x1 - r + k, y0), (x1, y0 + r - k), (x1, y0 + r)),
                LineTo((x1, y1 - r)),
                CurveTo((x1, y1 - r + k), (x1 - r + k, y1), (x1 - r, y1)),
                LineTo((x0 + r, y1)),
                CurveTo((x0 + r - k, y1), (x0, y1 - r + k), (x0, y1 - r)),
                LineTo((x0, y0 + r)),
                CurveTo((x0, y0 + r - k), (x0 + r - k, y0), (x0 + r, y0)),
                ClosePath(),
            )
        )
        assert fit_circle(path) is None

    def test_rejects_three_cubics(self) -> None:
        path = circle_path(0.0, 0.0, 5.0)
        assert fit_circle(SubPath(path.segments[:4])) is None

    def test_rejects_five_cubics(self) -> None:
        path = circle_path(0.0, 0.0, 5.0)
        extra = CurveTo((5.0, 1.0), (5.0, 2.0), (5.0, 3.0))
        assert fit_circle(SubPath(path.segments[:5] + (extra,))) is None

    def test_rejects_a_rectangle(self) -> None:
        path = SubPath(
            (
                MoveTo((0.0, 0.0)),
                LineTo((10.0, 0.0)),
                LineTo((10.0, 10.0)),
                LineTo((0.0, 10.0)),
                ClosePath(),
            )
        )
        assert fit_circle(path) is None

    def test_rejects_four_cubics_mixed_with_a_line(self) -> None:
        path = circle_path(0.0, 0.0, 5.0)
        assert fit_circle(SubPath(path.segments + (LineTo((99.0, 99.0)),))) is None

    def test_rejects_a_four_cubic_path_that_does_not_close(self) -> None:
        path = circle_path(0.0, 0.0, 5.0, closed=False)
        last = path.segments[4]
        assert isinstance(last, CurveTo)
        broken = CurveTo(last.c1, last.c2, (12.0, 3.0))
        assert fit_circle(SubPath(path.segments[:4] + (broken,))) is None

    def test_rejects_a_degenerate_zero_size_path(self) -> None:
        assert fit_circle(circle_path(7.0, 7.0, 0.0)) is None

    def test_rejects_an_empty_path(self) -> None:
        assert fit_circle(SubPath(())) is None

    # -- tolerance ---------------------------------------------------------

    def test_tolerance_is_relative_and_admits_measurement_noise(self) -> None:
        """Real coordinates arrive rounded to the PDF's decimal places."""
        noisy = SubPath(
            tuple(
                CurveTo(
                    (round(s.c1[0], 2), round(s.c1[1], 2)),
                    (round(s.c2[0], 2), round(s.c2[1], 2)),
                    (round(s.end[0], 2), round(s.end[1], 2)),
                )
                if isinstance(s, CurveTo)
                else s
                for s in circle_path(3.14159, -2.71828, 3.5).segments
            )
        )
        found = fit_circle(noisy)
        assert found is not None
        assert found.diameter == pytest.approx(7.0, abs=0.02)

    def test_a_tight_tolerance_rejects_what_a_loose_one_accepts(self) -> None:
        slightly_oval = circle_path(0.0, 0.0, 10.0, ry=10.05)
        assert fit_circle(slightly_oval, tolerance=0.05) is not None
        assert fit_circle(slightly_oval, tolerance=0.001) is None

    def test_default_tolerance_is_one_percent(self) -> None:
        import inspect

        assert inspect.signature(fit_circle).parameters["tolerance"].default == 0.01


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


class TestUnits:
    def test_kappa_constant(self) -> None:
        assert KAPPA == pytest.approx(0.5522847498)

    def test_pt_per_mm(self) -> None:
        assert PT_PER_MM == pytest.approx(72.0 / 25.4)

    def test_pt_to_mm_round_numbers(self) -> None:
        assert pt_to_mm(72.0) == pytest.approx(25.4)
        assert pt_to_mm(PT_PER_MM) == pytest.approx(1.0)
        assert pt_to_mm(0.0) == 0.0

    def test_pt_to_mm_is_linear(self) -> None:
        assert pt_to_mm(-10.0) == pytest.approx(-pt_to_mm(10.0))
