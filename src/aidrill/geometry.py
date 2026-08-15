"""Plane geometry: matrices, paths, and circle recovery.

Pure maths. No I/O, no PDF library, no knowledge of holes or panels — sources
depend on this module, never the other way round.

It exists because every vector format states a circle the same awkward way:
PostScript, PDF and SVG all lack an arc primitive, so a circle arrives as four
cubic Beziers. Recovering "this is a 7 mm hole at (-40, 18)" from twelve
coordinate pairs is a single, sharp problem, and per SPEC 2.2 it is solved
exactly once, here, for every source to reuse.

**This is one of the three modules where a length is a float, and the reason is
the fitting itself.** A quarter arc's control offset is ``KAPPA * r`` and
``KAPPA`` is irrational; a centroid is a mean of four coordinates; a radius is a
mean of four distances. None of that is expressible in whole nanometres without
losing the fit it is measuring. So the maths stays in floating-point PDF points
and the result crosses into the model's unit at one named place: the ``Circle``
that ``fit_circle`` returns, whose fields are whole nanometres.

**The conversion is at construction and nowhere earlier.** Rounding the anchors
as they are collected would quantise four coordinates and then average them, so
the centre and the radius would each carry up to four roundings instead of one —
and the diameter, being twice a radius, would carry that error doubled. A circle
of radius 3 pt shows the doubling: the diameter is 2 116 666.67 nm and rounds to
2 116 667, while the radius rounds to 1 058 333 and doubles to 2 116 666. It is
not the only radius that does, nor even the smallest — 2 pt disagrees the other
way round, a 4 pt diameter rounding to 1 411 111 against twice 705 556 — but it
is the one ``test_the_conversion_happens_once_and_on_the_diameter`` is built on.

**The centre needs a different kind of fixture, and the difference has already
fooled one reading of this module.** On a symmetric circle the four anchors of
an axis fall into antipodal pairs, and each pair sums — before any rounding — to
exactly twice the centre. Converting the two anchors separately can only carry
that sum to an integer beside it, which pins the mean of all four within half a
nanometre of the answer: the symmetric fixtures in ``tests/test_geometry.py``
land on it exactly (0.0, for a circle on the origin), a quarter off it
(-3 527 777.75, mirrored) or on the tie itself (3 878 943.5 at 37 degrees,
2 116 666.5 at 45). Half a nanometre is where the two orders stop disagreeing
about arithmetic and start disagreeing about a tie-break, and a tie only ever
refutes the rules that pick the far side — so those two tied fixtures pull in
opposite directions and *still* leave round-half-to-odd standing between them.
A whole suite once stayed green with the centroid replaced by a converted-anchor
mean.

What breaks the pairing, and with it the bound, is a *slightly asymmetric* path,
which is legal input here because ``fit_circle``'s tolerance is relative and
exists to admit measurement noise: a circle a nanometre out of true on a
millimetre radius is four orders of magnitude inside the 1% budget. Its
converted mean comes out three quarters of a nanometre low — 0.25 where the
answer is 1, 2.25 where it is 3 — far enough that half-up, half-even,
half-to-odd, truncation and a floor each give one wrong answer. A ceiling is the
one spelling that survives it, by landing on the right integer from the wrong
side, and the tied fixtures refute the ceiling instead.
``test_the_centre_converts_after_the_centroid_and_not_before`` is built on the
asymmetric path and keeps the whole table.

Both fixtures are chosen rather than found. The panel in
``tests/fixtures/tar.ai`` drifts by well under a nanometre and rounds to the
same integer either way, so *that* fixture cannot say this and must not be
trusted to. Real artwork may land on the boundary; it simply cannot be relied on
to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aidrill.units import nm_from_pt

__all__ = [
    "IDENTITY",
    "KAPPA",
    "Circle",
    "ClosePath",
    "CurveTo",
    "LineTo",
    "Matrix",
    "MoveTo",
    "Point",
    "Segment",
    "SubPath",
    "fit_circle",
    "multiply",
    "transform",
]

Point = tuple[float, float]

#: PDF ``cm`` operand order: ``a b c d e f``, meaning [[a, b], [c, d]] with the
#: translation (e, f). Stored as a plain tuple so it is hashable, comparable and
#: cheap — there is no behaviour here worth a class.
Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: Control-point offset, as a fraction of the radius, that makes a cubic Bezier
#: approximate a quarter circle: 4/3 * (sqrt(2) - 1). Every drawing tool uses
#: it, which is what makes circle recovery possible at all.
KAPPA: float = 0.5522847498


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------


def multiply(m: Matrix, n: Matrix) -> Matrix:
    """Compose two matrices: apply ``m`` first, then ``n``.

    The argument order is the one PDF's ``cm`` operator needs. ``cm``
    *concatenates* — the new matrix takes effect inside the existing one — so a
    content-stream walker updates its state with::

        ctm = multiply(cm_operands, ctm)

    Getting this backwards is silent and survives most test files, because the
    usual page CTM is a pure translation that commutes with itself. It only
    shows up when a nested ``cm`` scales, and then every coordinate inside a
    Form XObject is wrong.
    """
    a, b, c, d, e, f = m
    na, nb, nc, nd, ne, nf = n
    return (
        a * na + b * nc,
        a * nb + b * nd,
        c * na + d * nc,
        c * nb + d * nd,
        e * na + f * nc + ne,
        e * nb + f * nd + nf,
    )


def transform(m: Matrix, x: float, y: float) -> Point:
    """Map a point through ``m``: ``(a*x + c*y + e, b*x + d*y + f)``."""
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MoveTo:
    """PDF ``m``: start a new subpath at ``point``."""

    point: Point


@dataclass(frozen=True, slots=True)
class LineTo:
    """PDF ``l``: straight segment to ``point``."""

    point: Point


@dataclass(frozen=True, slots=True)
class CurveTo:
    """PDF ``c``: cubic Bezier with controls ``c1``/``c2``, ending at ``end``.

    The shorthand forms ``v`` and ``y`` are the caller's problem: a source
    expands them into this full form, so nothing downstream has to remember
    which operand each one omits.
    """

    c1: Point
    c2: Point
    end: Point


@dataclass(frozen=True, slots=True)
class ClosePath:
    """PDF ``h``: straight segment back to the subpath's start."""


Segment = MoveTo | LineTo | CurveTo | ClosePath


@dataclass(frozen=True, slots=True)
class SubPath:
    """A closed or open path in device space.

    "Device space" means the CTM has already been applied: a subpath carries
    absolute coordinates and no transform of its own. Sources resolve the
    graphics state; this module never has to.
    """

    segments: tuple[Segment, ...]

    @property
    def anchors(self) -> tuple[Point, ...]:
        """The on-curve points, in order, control points excluded.

        A closed path repeats its start point as the last anchor, exactly as
        the stream states it. Nothing is deduplicated here — a consumer that
        cares (``fit_circle`` does) can tell, and one that doesn't is unharmed.
        """
        points: list[Point] = []
        for segment in self.segments:
            if isinstance(segment, (MoveTo, LineTo)):
                points.append(segment.point)
            elif isinstance(segment, CurveTo):
                points.append(segment.end)
        return tuple(points)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Axis-aligned bounds ``(x0, y0, x1, y1)`` over the anchors.

        Control points are excluded deliberately. They lie outside the curve,
        so including them would inflate the box; and for every shape this
        library reads — rectangles, and circles/ellipses whose four anchors sit
        on the extremes — the anchor box is the exact box. For an arbitrary
        curve it is a slight under-estimate, which is the honest trade for
        never over-reporting a panel outline's size.

        Raises ``ValueError`` on a subpath with no on-curve points: there is no
        defensible answer, and returning zeros would quietly poison whatever
        picked the "largest" bbox.
        """
        points = self.anchors
        if not points:
            raise ValueError("cannot take the bounding box of a subpath with no anchors")
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------
# circle fitting
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Circle:
    """A recovered circle, in whole nanometres of the space its subpath was in.

    The subpath arrives in PDF points, so this is where a length stops being a
    float: the ``_nm`` suffix on every field is the unit stated at the call site
    rather than three stages downstream, which is the whole point of the
    convention (`aidrill.units`).

    Diameter, not radius, because that is what a drill chart, a tool table and
    a designer all speak in; halving it once here avoids everyone downstream
    doubling it back. It is also converted *as a diameter* — ``nm_from_pt`` of
    twice the radius, never twice ``nm_from_pt`` of the radius, which rounds the
    half-length and then doubles the error with it.
    """

    cx_nm: int
    cy_nm: int
    diameter_nm: int


def _cubics(path: SubPath) -> list[tuple[Point, CurveTo]] | None:
    """Pair each cubic with its start point, or ``None`` if the path isn't all curves.

    A circle is *only* curves. One stray ``LineTo`` means a rounded rectangle,
    a pie slice or a stroke cap — never a hole — so bail rather than fit a
    circle to the curved part of something else.
    """
    pairs: list[tuple[Point, CurveTo]] = []
    current: Point | None = None
    for segment in path.segments:
        if isinstance(segment, MoveTo):
            if current is not None:
                return None  # a second subpath; the caller should have split it
            current = segment.point
        elif isinstance(segment, CurveTo):
            if current is None:
                return None
            pairs.append((current, segment))
            current = segment.end
        elif isinstance(segment, ClosePath):
            pass
        else:  # LineTo
            return None
    return pairs


def fit_circle(path: SubPath, tolerance: float = 0.01) -> Circle | None:
    """Recover the circle a four-cubic path draws, or ``None`` if it isn't one.

    ``tolerance`` is *relative* to the radius (0.01 = 1%), because the absolute
    error scales with size: a 20 mm outline rounded to the PDF's two decimals
    deviates far more in absolute terms than a 3 mm hole, and one absolute
    tolerance cannot serve both.

    Four things must hold, and each rules out a shape that a panel drawing
    genuinely contains:

    * **four cubics, closing back on themselves** — rejects rounded rectangles
      (four cubics *and* four lines), arcs, and anything miscounted;
    * **all four anchors equidistant from their centroid** — rejects ellipses,
      including circles squashed by a non-uniform CTM;
    * **consecutive anchors a quarter turn apart** — rejects the shape that
      satisfies both of the above and the one below by taking a circle's
      controls onto anchors a circle would never have, because ``KAPPA`` is the
      offset for a quarter arc and only a quarter arc;
    * **kappa-consistent controls** — rejects the four-cubic rounded square,
      which is the case that matters. It has square bounds and four anchors on
      a common circle, so it passes every other test; only the control offsets
      betray it. A superellipse pushes them out towards the corners, a slack
      rounded shape pulls them in, and either way the offset stops being
      ``KAPPA * r`` perpendicular to the radius — and pointing the way the path
      travels, which is what separates an arc from an inward cusp drawn on the
      very same anchors.

    The centroid/radius test is used in preference to the bounding-box test of
    SPEC 6.4 because it is rotation invariant. They agree on axis-aligned input;
    on a circle rotated 45 degrees by a CTM the bounding box of the anchors is
    ``sqrt(2) * r`` across and would report the wrong diameter, or reject a
    perfectly good hole.
    """
    pairs = _cubics(path)
    if pairs is None or len(pairs) != 4:
        return None

    anchors = [start for start, _ in pairs]

    # Must come back to where it started: four cubics that wander off are a
    # curve, not a circle, whether or not a ClosePath papers over the gap.
    start = anchors[0]
    end = pairs[-1][1].end
    cx = sum(p[0] for p in anchors) / 4.0
    cy = sum(p[1] for p in anchors) / 4.0
    radius = sum(math.dist((cx, cy), p) for p in anchors) / 4.0

    if radius <= 0.0 or not math.isfinite(radius):
        return None  # degenerate: a zero-size path is a point, not a hole

    slack = tolerance * radius
    if math.dist(start, end) > slack:
        return None

    if any(abs(math.dist((cx, cy), p) - radius) > slack for p in anchors):
        return None

    if not _quarter_turns(anchors, (cx, cy), radius, slack):
        return None

    if not _kappa_consistent(pairs, (cx, cy), radius, slack):
        return None

    # The one conversion. Everything above is floating-point points because the
    # fitting genuinely is; everything below this line, and every consumer, has
    # whole nanometres.
    return Circle(
        cx_nm=nm_from_pt(cx),
        cy_nm=nm_from_pt(cy),
        diameter_nm=nm_from_pt(2.0 * radius),
    )


def _quarter_turns(
    anchors: list[Point],
    centre: Point,
    radius: float,
    slack: float,
) -> bool:
    """Does each cubic span a quarter turn about the centre?

    This is the precondition the kappa check never stated. ``KAPPA`` is the
    control offset for a *ninety degree* arc and nothing else — the offset for
    an arc of theta is ``4/3 * tan(theta/4) * r`` — so measuring controls
    against ``KAPPA * r`` only means something once the quarters are known to be
    quarters. Anchors at 0, 45, 180 and 225 degrees are equidistant from their
    centroid, close on themselves, and take a circle's controls without
    complaint; the fitter called that lumpy blob a 20.0 mm hole, which is a real
    bit, so the drill table passed it on without a diagnostic.

    Perpendicularity is the whole condition, and deliberately so. The caller has
    already established that the four anchors are the same distance from their
    own centroid, and equal radii about the centroid rule out the shape that
    turns a quarter one way and a quarter back: its centroid cannot land where
    such a shape would need it. A separate check on the *sense* of each turn
    would be a guard that can never fire, and one of those is worse than none.

    The dot product is divided by the radius so that what meets ``slack`` is a
    length and not an area — the same currency, as in the radial test below.
    """
    cx, cy = centre
    spokes = [(x - cx, y - cy) for x, y in anchors]
    for (px, py), (qx, qy) in zip(spokes, spokes[1:] + spokes[:1]):
        if abs(px * qx + py * qy) / radius > slack:
            return False
    return True


def _kappa_consistent(
    pairs: list[tuple[Point, CurveTo]],
    centre: Point,
    radius: float,
    slack: float,
) -> bool:
    """Are the control points where a real circle would put them?

    For each quarter, the first control sits ``KAPPA * r`` beyond the start
    anchor along the tangent, and the second sits ``KAPPA * r`` before the end
    anchor along its tangent. Three things are checked, and dropping any one of
    them lets a shape through that a drill would then cut:

    * **length** — rejects the four-cubic rounded square, whose controls are
      pushed out towards the corners or pulled slackly in;
    * **radial component** — rejects controls rotated onto the radius, which
      draw a cusp instead of an arc while keeping the length exactly right;
    * **tangential sense** — rejects controls that are the right length, exactly
      perpendicular, and pointing the wrong way along the tangent. Negate both
      offsets of a real circle and every other test still sees a circle; what it
      draws is a four-petal star with an inward cusp at every anchor.

    The direction of travel is taken from the anchors, never from an offset: an
    offset that lies about its direction is precisely what this is here to
    catch. Two consecutive anchors turn a quarter turn about the centre, and the
    sign of their cross product is the sense of the whole path — which also
    keeps this right for a circle mirrored by a negative-determinant CTM, where
    every control legitimately points the other way.
    """
    expected = KAPPA * radius
    cx, cy = centre
    anchors = [start for start, _ in pairs]
    ax, ay = anchors[0][0] - cx, anchors[0][1] - cy
    bx, by = anchors[1][0] - cx, anchors[1][1] - cy
    travel = 1.0 if (ax * by - ay * bx) >= 0.0 else -1.0

    # The first control runs with the direction of travel; the second runs back
    # against it, since it is measured from the anchor the quarter arrives at.
    for start, curve in pairs:
        for anchor, control, sense in ((start, curve.c1, 1.0), (curve.end, curve.c2, -1.0)):
            ox, oy = control[0] - anchor[0], control[1] - anchor[1]
            if abs(math.hypot(ox, oy) - expected) > slack:
                return False
            # radial component of the offset; zero for a true tangent
            rx, ry = anchor[0] - cx, anchor[1] - cy
            if abs((ox * rx + oy * ry) / radius) > slack:
                return False
            # tangent at this anchor, turned the way the path travels
            tx, ty = -ry * travel * sense, rx * travel * sense
            if ox * tx + oy * ty <= 0.0:
                return False
    return True
