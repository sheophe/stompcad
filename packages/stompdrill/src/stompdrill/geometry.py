"""Floating-point plane geometry for matrices, paths, and circle recovery.

Geometry remains in its source units; quantisation belongs to the phase that
selects a domain answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

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

#: PDF ``cm`` operands ``a b c d e f``: [[a, b], [c, d]], translated by (e, f).
Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: Quarter-circle cubic control offset: 4/3 * (sqrt(2) - 1) times the radius.
KAPPA: float = 0.5522847498


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------


def multiply(m: Matrix, n: Matrix) -> Matrix:
    """Compose two matrices: apply ``m`` first, then ``n``.

    For PDF ``cm`` concatenation use ``multiply(cm_operands, ctm)``.
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

    Sources expand shorthand ``v`` and ``y`` operators into this form.
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
    """A path in device space, with its CTM already applied."""

    segments: tuple[Segment, ...]

    @property
    def anchors(self) -> tuple[Point, ...]:
        """The on-curve points, in order, control points excluded.

        Closed paths retain any repeated start point from the stream.
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

        Control points are excluded. Raises ``ValueError`` when no anchor exists.
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
    """A recovered circle in its subpath's units, expressed by diameter."""

    cx: float
    cy: float
    diameter: float


def _cubics(path: SubPath) -> list[tuple[Point, CurveTo]] | None:
    """Pair each cubic with its start point, or ``None`` if the path isn't all curves.

    A second subpath, missing start, or any straight segment rejects the path.
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

    Relative ``tolerance`` checks closure, equidistant centroid radii, quarter
    turns, and kappa-consistent controls. The centroid test is rotation invariant.
    Every band here and below is closed: each guard rejects on ``> slack``, so a
    deviation exactly one slack out is still a circle.
    """
    pairs = _cubics(path)
    if pairs is None or len(pairs) != 4:
        return None

    anchors = [start for start, _ in pairs]

    # The cubics themselves must return to the start; ClosePath is insufficient.
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

    return Circle(cx=cx, cy=cy, diameter=2.0 * radius)


def _quarter_turns(
    anchors: list[Point],
    centre: Point,
    radius: float,
    slack: float,
) -> bool:
    """Return whether consecutive radius vectors are perpendicular.

    ``KAPPA`` applies only to quarter arcs: ``4/3 * tan(theta/4) * r`` at
    ``theta = pi/2``. Dividing the dot product by ``radius`` compares lengths.
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
    """Check control length, radial component, and tangential direction.

    Each quarter's controls are tangent offsets of length ``KAPPA * radius``.
    Travel direction comes from the anchors, preserving mirrored circles.
    """
    expected = KAPPA * radius
    cx, cy = centre
    anchors = [start for start, _ in pairs]
    ax, ay = anchors[0][0] - cx, anchors[0][1] - cy
    bx, by = anchors[1][0] - cx, anchors[1][1] - cy
    travel = 1.0 if (ax * by - ay * bx) >= 0.0 else -1.0

    # The first control follows travel; the second points back from the end.
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
