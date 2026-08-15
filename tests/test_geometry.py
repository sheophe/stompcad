"""Tests for :mod:`aidrill.geometry`.

The interesting tests here are the *negative* ones. Recovering a circle from
four cubics is easy; the whole value of ``fit_circle`` is that it refuses
ellipses and rounded rectangles, which are the two things a panel drawing is
full of and which a naive bounding-box fit happily mistakes for holes.

A negative test alone is not enough, and this file learned that the hard way.
``fit_circle`` rejects with a bare ``None``, so ``assert fit_circle(x) is None``
passes for the *union* of every rejection path — and every negative fixture
written from ``circle_path`` trips two or three guards at once. Three guards
were each deleted with the whole suite still green, and each then admitted a
shape reported at 10.0 or 11.0 mm: real metric bits, so the drill table waves
them through and a tool is loaded for a hole the artwork never contained.

The cure is the shape of ``test_rejects_controls_rotated_into_the_radius``, and
every test under "one guard at a time" follows it: build a shape that defeats
one guard, assert *positively* that the others are satisfied, and only then
assert the rejection. ``kappa_correct_path`` exists to make that possible for
arbitrary anchors.

Everything a path is made of here is a floating-point PDF point, and only what
``fit_circle`` returns is nanometres. That is the module boundary, so the
assertions come in two currencies: an expectation about a control offset or an
anchor radius is a float in points and is compared with ``PT_SLACK``, while an
expectation about a recovered ``Circle`` is a whole number of nanometres and is
compared with ``units.nm_from_pt``. ``tolerance.within`` belongs to neither: it
takes whole nanometres, and loosening it to take a float would move the model's
boundary to suit a test at the one place a float is legitimate.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from aidrill.geometry import (
    IDENTITY,
    KAPPA,
    Circle,
    ClosePath,
    CurveTo,
    LineTo,
    Matrix,
    MoveTo,
    SubPath,
    # private, and imported on purpose: isolating one guard means asserting
    # positively that the others passed, and two of them are whole predicates
    _cubics,
    _kappa_consistent,
    _quarter_turns,
    fit_circle,
    multiply,
    transform,
)
from aidrill.units import nm_from_pt

Point = tuple[float, float]

#: PDF user space is 1/72 inch, so this is the scale between a stated point and
#: a millimetre. It is here, in the file that wants it, and not exported from
#: ``geometry``: the only thing that needs it is a CTM fixture magnifying a path
#: by a realistic amount, and the conversion itself is ``units.nm_from_pt``,
#: which divides one exact rational rather than multiplying by this ratio.
PT_PER_MM = 72.0 / 25.4

#: Slack for the float assertions, in points. These sit on the *inside* of the
#: fitter, where the maths is genuinely fractional, so they are the one thing in
#: the suite that a nanometre cannot express.
PT_SLACK = 1e-9

#: Slack for the nanometre assertions, in nanometres. A centroid is a mean of
#: four coordinates and a radius a mean of four distances, so a scaled or
#: rotated fixture can land on the nanometre either side of the closed form; one
#: nanometre is the narrowest slack there is and every exact case below asserts
#: equality instead.
NM_SLACK = 1


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def pt_from_nm(nm: float) -> float:
    """A length in (possibly fractional) nanometres, stated as PDF points.

    The inverse of ``units.nm_from_pt``, and deliberately not in ``units``:
    nothing in the library wants it, because a nanometre is where a length
    *arrives* and never where one starts. The one caller is a fixture that has
    to place an anchor a stated fraction of a nanometre away from a whole one,
    so it lives here, in the file that needs it.
    """
    return nm * 72.0 / 25_400_000.0


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


def kappa_correct_path(anchors: tuple[Point, ...], *, tilt: float = 0.0) -> SubPath:
    """Four cubics on *arbitrary* anchors, carrying the controls a circle would carry.

    ``circle_path`` can only vary one thing at a time and always puts its
    anchors on the axes, which is why every shipped negative fixture trips two
    or three guards at once and none of them is pinned. This builder separates
    the anchors from the controls: give it any four anchors and it fits each
    quarter with an offset of ``KAPPA * r`` — ``r`` being the mean anchor
    radius, which is exactly what ``fit_circle`` will measure — perpendicular
    to *that anchor's own* radius and pointing the way the anchors travel. The
    kappa check therefore passes by construction whatever the anchors do, so a
    shape built here fails the one guard it was built to fail and no other.

    ``tilt`` rotates every offset by that many degrees out of the tangent and
    towards the radius. The length is unchanged and the tangential component
    stays positive, so only the radial clause of the kappa check can object.
    """
    n = len(anchors)
    cx = sum(p[0] for p in anchors) / n
    cy = sum(p[1] for p in anchors) / n
    radius = sum(math.dist((cx, cy), p) for p in anchors) / n
    offset = KAPPA * radius
    ax, ay = anchors[0][0] - cx, anchors[0][1] - cy
    bx, by = anchors[1][0] - cx, anchors[1][1] - cy
    travel = 1.0 if (ax * by - ay * bx) >= 0.0 else -1.0
    theta = math.radians(tilt)

    def control(anchor: Point, sense: float) -> Point:
        rx, ry = anchor[0] - cx, anchor[1] - cy
        norm = math.hypot(rx, ry)
        ux, uy = rx / norm, ry / norm  # unit radius
        tx, ty = -uy * travel * sense, ux * travel * sense  # unit tangent, the way we travel
        dx = tx * math.cos(theta) + ux * math.sin(theta)
        dy = ty * math.cos(theta) + uy * math.sin(theta)
        return (anchor[0] + offset * dx, anchor[1] + offset * dy)

    segments: list[object] = [MoveTo(anchors[0])]
    for i, start in enumerate(anchors):
        end = anchors[(i + 1) % n]
        segments.append(CurveTo(control(start, 1.0), control(end, -1.0), end))
    segments.append(ClosePath())
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
            SubPath(()).bbox  # noqa: B018  the bare access is the assertion: bbox is a property

    def test_subpath_is_frozen(self) -> None:
        path = circle_path(0.0, 0.0, 1.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            path.segments = ()  # type: ignore[misc]


# --------------------------------------------------------------------------
# circle fitting
# --------------------------------------------------------------------------


class TestFitCircle:
    def test_recovers_a_synthetic_circle_exactly(self) -> None:
        """Exactly, and in whole nanometres: the fitter's own boundary.

        The path is in points, the answer is not. Nothing is approximate here
        because nothing needs to be — the anchors are exact halves, so the
        centroid and the radius are exact and the only rounding left is the one
        ``nm_from_pt`` performs, which is the answer.
        """
        found = fit_circle(circle_path(-40.0, 18.0, 3.5))
        assert found is not None
        assert found.cx_nm == nm_from_pt(-40.0)
        assert found.cy_nm == nm_from_pt(18.0)
        assert found.diameter_nm == nm_from_pt(7.0)
        assert {type(v) for v in (found.cx_nm, found.cy_nm, found.diameter_nm)} == {int}

    def test_the_conversion_happens_once_and_on_the_diameter(self) -> None:
        """Pins *where* the crossing into nanometres happens, not merely that it does.

        A 3 pt radius is 1 058 333.33 nm and the 6 pt diameter it implies is
        2 116 666.67 — which round to 1 058 333 and 2 116 667. So rounding the
        radius first and doubling gives 2 116 666: a nanometre short, because a
        half-length was rounded and then had its error doubled along with it.

        The circle is centred on the origin deliberately, which makes this fixture
        refuse the other spelling of the same mistake too. Its four anchors sit at
        ``(+-3, 0)`` and ``(0, +-3)``, so converting each anchor as it is collected
        gives a centroid of exactly zero and a mean anchor radius of exactly
        ``nm_from_pt(3.0)`` — a per-anchor conversion *is* a rounded radius here,
        and lands on the same 2 116 666.

        A fixture whose true value sits far from a half-nanometre cannot say any of
        this: the fixture in ``test_ai_pdf`` drifts by up to 0.56 nm under a
        per-anchor conversion and still rounds to the same integer, coming within
        0.0011 nm of noticing on its closest hole. Exactness needs a fixture chosen
        to sit on the boundary, and this is it.
        """
        # the two orders genuinely disagree here — the fixture is not a coincidence
        assert nm_from_pt(6.0) != 2 * nm_from_pt(3.0)

        found = fit_circle(circle_path(0.0, 0.0, 3.0))
        assert found is not None
        assert found.diameter_nm == nm_from_pt(6.0) == 2_116_667

    def test_the_centre_converts_after_the_centroid_and_not_before(self) -> None:
        """The same crossing, for the two fields the diameter fixture cannot see.

        ``test_the_conversion_happens_once_and_on_the_diameter`` sits on the
        origin, where a centroid of four converted anchors is zero however it is
        assembled — so it says nothing at all about ``cx_nm`` or ``cy_nm``.

        A *symmetric* circle cannot say it either, and that is the trap this
        fixture exists to leave behind. Put the anchors antipodally and the mean
        of the four converted anchors lands exactly on a half-nanometre, so
        which integer it becomes is settled by a tie-break rule rather than by
        the order of the arithmetic — and a tie is decidable four ways. Half-up,
        half-even, round-half-to-odd and truncation each pick one, so a tied
        fixture can only ever refute the rules that pick the far side, and
        whichever rule picks the near side survives it. Rotating the fixture
        does not help; it only moves the tie.

        So this path is *asymmetric*, and legally so: ``fit_circle`` measures a
        1% relative tolerance precisely to admit measurement noise, and a circle
        whose anchors are a nanometre out of true on a one-millimetre radius is
        noise a thousand times finer than any artwork. The assertion below
        states the margin — the worst anchor is off the mean radius by less than
        a thousandth of the budget — so this is ordinary accepted input and not
        a shape the fitter is being talked into.

        Every one of the eight anchor coordinates sits 0.26 nm above a whole
        nanometre. Converting an anchor therefore throws 0.26 nm away, and doing
        it four times before averaging drops the mean by 0.26 nm: from N + 0.51,
        which rounds to N + 1, to N + 0.25, which rounds to N under half-up,
        half-even, half-to-odd and truncation alike. On x, N is 0 and the answer
        is 1 nm; on y, N is 2 and the answer is 3 nm. ``% 4 == 1`` states that
        the mean is a quarter and not a tie, which is the whole difference.

        The two axes carry different anchor sums and different answers on
        purpose: where they coincide, one assertion stands in for the other and
        a mutation to ``cx_nm`` alone is indistinguishable from one to ``cy_nm``
        alone.

        One thing no fixture can do, and this docstring will not claim it does:
        take the *ceiling* of the converted-anchor mean and the answer comes
        back right. It has to. Each conversion loses under half a nanometre, so
        the mean of four of them is always within half a nanometre of the real
        centroid, whose own nearest integer is therefore always one of that
        mean's two neighbours — some directed rounding of the wrong arithmetic
        always agrees, on every fixture that could ever be built. A ceiling is
        not a rule anyone writes for a measurement, which is why the four that
        are stay refuted.
        """
        radius_nm = 1_000_000.0
        anchors = tuple(
            (pt_from_nm(x), pt_from_nm(y))
            for x, y in (
                (radius_nm + 1.26, 3.26),
                (0.26, radius_nm + 3.26),
                (-radius_nm + 0.26, 3.26),
                (0.26, -radius_nm + 0.26),
            )
        )
        path = kappa_correct_path(anchors)

        pairs = _cubics(path)
        assert pairs is not None and len(pairs) == 4
        assert tuple(start for start, _ in pairs) == anchors

        # asymmetric, and far inside the tolerance that makes it legal input
        cx = sum(p[0] for p in anchors) / 4.0
        cy = sum(p[1] for p in anchors) / 4.0
        radius = sum(math.dist((cx, cy), p) for p in anchors) / 4.0
        worst = max(abs(math.dist((cx, cy), p) - radius) for p in anchors)
        assert worst > 0.0  # not the symmetric case ...
        assert worst < 0.01 * radius / 1000.0  # ... and nowhere near the 1% budget

        for axis, answer in ((0, 1), (1, 3)):
            converted = sum(nm_from_pt(a[axis]) for a in anchors)
            assert converted % 4 == 1  # the mean is exactly N + 0.25, not a tie ...
            assert converted // 4 == answer - 1  # ... and N is one short, round it how you like

        found = fit_circle(path)
        assert found is not None
        assert found.cx_nm == 1
        assert found.cy_nm == 3

    def test_the_centre_takes_the_upper_nanometre_where_the_anchor_mean_ties(self) -> None:
        """A tied centre fixture, which can speak about the tie-break and no more.

        This circle is turned 45 degrees and centred off both axes, on a pair of
        points chosen so that the mean of its converted anchors lands exactly on
        the half-nanometre *below* the answer: 2 116 666.5 on x, 2 751 666.5 on
        y. ``% 4 == 2`` states the tie without picking a rule to settle it —
        which is the limit of what this fixture can do. Half-even and truncation
        take the tie down and are a nanometre short, so both die here; half-up
        and half-to-odd take it up and land on the right integer by luck.
        ``test_recovers_a_circle_under_rotation`` ties the other way and kills
        half-up in turn, and the ordering itself is pinned by
        ``test_the_centre_converts_after_the_centroid_and_not_before``, whose
        anchor mean is not a tie at all.

        The two coordinates are pinned to different integers on purpose. A
        fixture centred on the diagonal would let one assertion stand in for the
        other, and a mutation to ``cx_nm`` alone would be indistinguishable from
        one to ``cy_nm`` alone.
        """
        placed: Matrix = (1.0, 0.0, 0.0, 1.0, 6.0, 7.8)
        turned = mapped(circle_path(0.0, 0.0, 5.0), multiply(rotation(45.0), placed))

        pairs = _cubics(turned)
        assert pairs is not None and len(pairs) == 4
        anchors = [start for start, _ in pairs]
        for axis, answer in ((0, nm_from_pt(6.0)), (1, nm_from_pt(7.8))):
            converted = sum(nm_from_pt(a[axis]) for a in anchors)
            assert converted % 4 == 2  # the mean is exactly N + 0.5 ...
            assert converted // 4 == answer - 1  # ... and N is one short

        found = fit_circle(turned)
        assert found is not None
        assert found.cx_nm == nm_from_pt(6.0) == 2_116_667
        assert found.cy_nm == nm_from_pt(7.8) == 2_751_667

    def test_returns_a_frozen_circle_value(self) -> None:
        found = fit_circle(circle_path(0.0, 0.0, 1.0))
        assert isinstance(found, Circle)
        with pytest.raises(dataclasses.FrozenInstanceError):
            found.cx_nm = 5  # type: ignore[misc]

    def test_recovers_a_circle_through_a_translate_and_scale_ctm(self) -> None:
        ctm: Matrix = (PT_PER_MM, 0.0, 0.0, PT_PER_MM, 200.0, 400.0)
        found = fit_circle(mapped(circle_path(-40.0, 18.0, 3.5), ctm))
        assert found is not None
        expected = transform(ctm, -40.0, 18.0)
        assert (found.cx_nm, found.cy_nm) == pytest.approx(
            (nm_from_pt(expected[0]), nm_from_pt(expected[1])), abs=NM_SLACK
        )
        assert found.diameter_nm == pytest.approx(nm_from_pt(7.0 * PT_PER_MM), abs=NM_SLACK)

    def test_recovers_a_circle_under_rotation(self) -> None:
        """A rotated circle is still a circle.

        Fitting from the *axis-aligned* bounding box would report a diameter of
        2r*cos(45 deg) here. Anchor radii are rotation invariant, so they don't.

        Exact, and not within ``NM_SLACK``: a nanometre of slack is the whole
        margin between converting the finished centroid and averaging four
        converted anchors, so it is precisely the one nanometre this fixture is
        able to speak about. The four converted anchors mean exactly
        3 878 943.5 and 714 365.5 here — a tie whose *upper* side is wrong on
        both axes — so allowing a nanometre accepted 3 878 944 and 714 366 as
        readily as the right pair. Rounding that tie up is half-up and half-even
        alike, which is what makes this the fixture that kills them;
        ``test_the_centre_takes_the_upper_nanometre_where_the_anchor_mean_ties``
        ties the other way and kills truncation.
        """
        ctm = rotation(37.0)
        found = fit_circle(mapped(circle_path(10.0, -5.0, 2.5), ctm))
        assert found is not None
        expected = transform(ctm, 10.0, -5.0)
        assert (found.cx_nm, found.cy_nm) == (
            nm_from_pt(expected[0]),
            nm_from_pt(expected[1]),
        )
        assert found.diameter_nm == nm_from_pt(5.0)

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
        assert (found.cx_nm, found.cy_nm) == (nm_from_pt(-10.0), nm_from_pt(-5.0))
        assert found.diameter_nm == nm_from_pt(5.0)

    def test_open_circle_path_without_closepath_still_fits(self) -> None:
        assert fit_circle(circle_path(0.0, 0.0, 4.0, closed=False)) is not None

    def test_the_anchor_builder_draws_a_circle_the_fitter_accepts(self) -> None:
        """``kappa_correct_path`` on a circle's anchors is a circle.

        Every isolation test below feeds this builder anchors that are wrong in
        exactly one way and asserts the rest of ``fit_circle`` sees nothing
        amiss. That argument is only worth anything if the builder itself makes
        holes the fitter takes, so it is asserted here rather than assumed.
        """
        found = fit_circle(kappa_correct_path(((3.5, 0.0), (0.0, 3.5), (-3.5, 0.0), (0.0, -3.5))))
        assert found is not None
        assert found.diameter_nm == pytest.approx(nm_from_pt(7.0), abs=NM_SLACK)

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
        assert control_offsets(path) == pytest.approx([KAPPA * 5.0] * 8, abs=PT_SLACK)
        # nor does anything before it: same anchors as the real circle
        assert path.anchors == circle_path(0.0, 0.0, 5.0).anchors

        assert fit_circle(path) is None

    def test_rejects_controls_rotated_into_the_radius_pointing_inward(self) -> None:
        """Same cusp, controls folded towards the centre instead of away."""
        path = cusp_path(0.0, 0.0, 5.0, outward=False)
        assert control_offsets(path) == pytest.approx([KAPPA * 5.0] * 8, abs=PT_SLACK)
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

    def test_rejects_a_path_whose_radius_overflows(self) -> None:
        """The other clause of the degeneracy guard: unbounded, not vanishing.

        ``radius <= 0.0`` catches the point a zero-size path collapses to. An
        anchor radius that overflows to infinity is the opposite failure and
        sails past that clause, and every guard after it then measures against
        an infinite slack — so nothing objects and the fitter reports a hole of
        infinite diameter, which snaps to no bit and drops a real hole with it.
        """
        huge = kappa_correct_path(((1e308, 0.0), (0.0, 1e308), (-1e308, 0.0), (0.0, -1e308)))
        pairs = _cubics(huge)
        assert pairs is not None
        radius = sum(math.dist((0.0, 0.0), start) for start, _ in pairs) / 4.0
        # the sign clause sees nothing wrong: this radius is positive
        assert radius > 0.0
        assert math.isinf(radius)

        assert fit_circle(huge) is None

    def test_rejects_an_empty_path(self) -> None:
        assert fit_circle(SubPath(())) is None

    # -- one guard at a time -----------------------------------------------
    #
    # Each shape below defeats exactly one guard and satisfies the others, and
    # says so with a positive assertion before it asserts the rejection. Delete
    # the guard a test names and that test — and only that test — fails.

    def test_rejects_an_oval_carrying_a_circles_controls(self) -> None:
        """Isolates the equidistant-anchor guard.

        A 12 x 10 oval, its controls built for the 11 mm circle ``fit_circle``
        will measure. The path closes, the anchors are a quarter turn apart and
        every control is where a circle puts it, so only the anchor radii
        disagree. Without that guard this is drilled at 11.0 mm, which is a real
        metric bit and passes the drill table without a murmur.
        """
        oval = kappa_correct_path(((6.0, 0.0), (0.0, 5.0), (-6.0, 0.0), (0.0, -5.0)))
        pairs = _cubics(oval)
        assert pairs is not None and len(pairs) == 4

        # everything except the anchor radii sees a circle of radius 5.5
        assert math.dist(pairs[0][0], pairs[-1][1].end) == pytest.approx(0.0, abs=1e-9)
        assert _quarter_turns([start for start, _ in pairs], (0.0, 0.0), 5.5, 0.055)
        assert _kappa_consistent(pairs, (0.0, 0.0), 5.5, 0.055)

        assert fit_circle(oval) is None

    def test_rejects_four_cubics_that_end_short_of_their_start(self) -> None:
        """Isolates the path-closure guard.

        The four anchors are a circle's, and the last curve is displaced along
        its own radius so that it ends 1.2 mm out beyond the start — which
        leaves its control offset the same length, still perpendicular to the
        same radius and still running the way the path travels. Only the gap
        betrays it. Without the guard this is drilled at 10.0 mm.
        """
        base = kappa_correct_path(((5.0, 0.0), (0.0, 5.0), (-5.0, 0.0), (0.0, -5.0)))
        last = base.segments[4]
        assert isinstance(last, CurveTo)
        spiral = SubPath(
            base.segments[:4]
            + (CurveTo(last.c1, (last.c2[0] + 1.2, last.c2[1]), (last.end[0] + 1.2, last.end[1])),)
        )
        pairs = _cubics(spiral)
        assert pairs is not None and len(pairs) == 4

        # the anchors are still a circle's, and the controls are still a circle's
        assert [math.dist((0.0, 0.0), start) for start, _ in pairs] == pytest.approx([5.0] * 4)
        assert _quarter_turns([start for start, _ in pairs], (0.0, 0.0), 5.0, 0.05)
        assert _kappa_consistent(pairs, (0.0, 0.0), 5.0, 0.05)
        assert math.dist(pairs[0][0], pairs[-1][1].end) == pytest.approx(1.2)

        assert fit_circle(spiral) is None

    def test_rejects_controls_tilted_off_the_tangent(self) -> None:
        """Isolates the radial clause of the kappa check.

        ``cusp_path`` turns each offset a full 90 degrees onto the radius, which
        also reverses what the tangential clause looks at on half of them. This
        one tilts by 20 degrees: every offset keeps its length exactly, keeps a
        positive component along the direction of travel, and only picks up a
        radial component. Both other clauses of the check are asserted here, so
        the rejection can only be the radial one. Without it this is drilled at
        10.0 mm.
        """
        tilted = kappa_correct_path(
            ((5.0, 0.0), (0.0, 5.0), (-5.0, 0.0), (0.0, -5.0)), tilt=20.0
        )
        pairs = _cubics(tilted)
        assert pairs is not None and len(pairs) == 4

        # anchors untouched, so the guards before the kappa check see a circle
        assert [math.dist((0.0, 0.0), start) for start, _ in pairs] == pytest.approx([5.0] * 4)
        assert math.dist(pairs[0][0], pairs[-1][1].end) == pytest.approx(0.0, abs=1e-9)
        assert _quarter_turns([start for start, _ in pairs], (0.0, 0.0), 5.0, 0.05)

        for start, curve in pairs:
            for anchor, control, sense in ((start, curve.c1, 1.0), (curve.end, curve.c2, -1.0)):
                ox, oy = control[0] - anchor[0], control[1] - anchor[1]
                rx, ry = anchor  # the centre is the origin
                # right length ...
                assert math.hypot(ox, oy) == pytest.approx(KAPPA * 5.0, abs=PT_SLACK)
                # ... and running the way the path travels (anticlockwise here)
                assert (ox * -ry + oy * rx) * sense > 0.0
                # only the radial component is wrong, and it is far out
                assert abs(ox * rx + oy * ry) / 5.0 > 0.05

        assert fit_circle(tilted) is None

    def test_rejects_anchors_that_are_not_a_quarter_turn_apart(self) -> None:
        """Isolates the quarter-turn guard.

        Four anchors at 0, 45, 180 and 225 degrees, all 10 mm from a centroid
        that still lands on the origin. They are equidistant, they close, and
        their controls are ``KAPPA * r`` long, perpendicular and running the way
        the path travels — so the kappa check passes too, because ``KAPPA`` is
        the offset for a *quarter* arc and nothing was checking that these
        quarters are quarters. What it draws is a lopsided blob; what it was
        reported as is a 20.0 mm hole.
        """
        d = 10.0 / math.sqrt(2.0)
        blob = kappa_correct_path(((10.0, 0.0), (d, d), (-10.0, 0.0), (-d, -d)))
        pairs = _cubics(blob)
        assert pairs is not None and len(pairs) == 4

        # every guard except the quarter turn sees a circle of radius 10
        assert [math.dist((0.0, 0.0), start) for start, _ in pairs] == pytest.approx([10.0] * 4)
        assert math.dist(pairs[0][0], pairs[-1][1].end) == pytest.approx(0.0, abs=1e-9)
        assert _kappa_consistent(pairs, (0.0, 0.0), 10.0, 0.1)

        assert fit_circle(blob) is None

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
        assert found.diameter_nm == pytest.approx(nm_from_pt(7.0), abs=nm_from_pt(0.02))

    def test_a_tight_tolerance_rejects_what_a_loose_one_accepts(self) -> None:
        slightly_oval = circle_path(0.0, 0.0, 10.0, ry=10.05)
        assert fit_circle(slightly_oval, tolerance=0.05) is not None
        assert fit_circle(slightly_oval, tolerance=0.001) is None

    @pytest.mark.parametrize("radius", [0.6, 12.5])
    def test_the_same_proportional_deviation_gets_the_same_answer_at_any_radius(
        self, radius: float
    ) -> None:
        """The slack scales with the radius, and no absolute slack can do this.

        ``test_default_tolerance_is_one_percent`` pins the *value* of the
        tolerance and says nothing about what it multiplies: drop the ``*
        radius`` and its fixture is small enough that relative and absolute
        agree. They stop agreeing on a big hole. A 25 mm hole rounded to the two
        decimals a PDF carries can arrive measuring 25.00 x 24.92 — 0.3% out,
        well inside 1% — and an absolute 0.01 mm slack rejects it. **A rejected
        circle is not a diagnostic**; it is simply not a hole, so it vanishes
        from the drill file, the drawing and the JSON alike, at exit 0.

        So: the same *proportion* must get the same verdict on a 1.2 mm hole and
        a 25 mm one. 0.3% is accepted at both, 3% is refused at both.
        """
        assert fit_circle(circle_path(0.0, 0.0, radius, ry=radius * (24.92 / 25.00))) is not None
        assert fit_circle(circle_path(0.0, 0.0, radius, ry=radius * 0.97)) is None

    def test_default_tolerance_is_one_percent(self) -> None:
        import inspect

        assert inspect.signature(fit_circle).parameters["tolerance"].default == 0.01


# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------


class TestConstants:
    def test_kappa_constant(self) -> None:
        assert KAPPA == pytest.approx(0.5522847498)
