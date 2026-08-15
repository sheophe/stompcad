"""Plane geometry: matrices, paths, and circle recovery.

Pure maths. No I/O, no PDF library, no knowledge of holes or panels — sources
depend on this module, never the other way round.

It exists because every vector format states a circle the same awkward way:
PostScript, PDF and SVG all lack an arc primitive, so a circle arrives as four
cubic Beziers. Recovering "this is a 7 mm hole at (-40, 18)" from twelve
coordinate pairs is a single, sharp problem, and per SPEC 2.2 it is solved
exactly once, here, for every source to reuse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Union

__all__ = [
    "IDENTITY",
    "KAPPA",
    "PT_PER_MM",
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
    "pt_to_mm",
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

#: PDF user space is 1/72 inch. Everything downstream of a source is millimetres.
PT_PER_MM: float = 72.0 / 25.4


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


Segment = Union[MoveTo, LineTo, CurveTo, ClosePath]


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
    """A recovered circle in whatever space its subpath was in.

    Diameter, not radius, because that is what a drill chart, a tool table and
    a designer all speak in; halving it once here avoids everyone downstream
    doubling it back.
    """

    cx: float
    cy: float
    diameter: float


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

    Three things must hold, and each rules out a shape that a panel drawing
    genuinely contains:

    * **four cubics, closing back on themselves** — rejects rounded rectangles
      (four cubics *and* four lines), arcs, and anything miscounted;
    * **all four anchors equidistant from their centroid** — rejects ellipses,
      including circles squashed by a non-uniform CTM;
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

    if not _kappa_consistent(pairs, (cx, cy), radius, slack):
        return None

    return Circle(cx=cx, cy=cy, diameter=2.0 * radius)


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


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------


def pt_to_mm(v: float) -> float:
    """Convert PDF points to millimetres, the canonical unit of everything above a source."""
    return v / PT_PER_MM
