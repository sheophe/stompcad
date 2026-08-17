"""Deterministic pipeline-level hole ordering shared by every emitter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, ClassVar

from ..model import DrillData, Hole, StageRun

if TYPE_CHECKING:
    # ``sorted`` needs a key whose result can be compared with ``<``. Spelling
    # that as ``object`` types the parameter by what a key *is* rather than by
    # what this stage does with it, and ``RouteHoles(key=lambda h: h)`` then
    # type-checks cleanly and raises TypeError on a real panel. _typeshed is
    # not importable at runtime, which is why the import is guarded.
    from _typeshed import SupportsRichComparison

__all__ = ["RouteHoles"]


def _total_order(hole: Hole) -> tuple[int, int, float, float, float]:
    """Reading order, then the measurement, so no two holes can tie.

    Nominal position ties for two holes at one point, and ``min``
    would then keep whichever arrived first — input order deciding an answer
    that must be geometric. The measurement that produced each hole breaks it.
    Two holes equal in both are interchangeable, so no output distinguishes them.
    """
    return (-hole.y_nm, hole.x_nm, hole.raw.x, hole.raw.y, hole.raw.diameter)


def _distance_sq(a: Hole, b: Hole) -> int:
    """Squared distance in whole nanometres — exact, and monotone in distance."""
    return (a.x_nm - b.x_nm) ** 2 + (a.y_nm - b.y_nm) ** 2


def _nearest_neighbour(block: list[Hole]) -> list[Hole]:
    """Visit the topmost-then-leftmost hole, then always the nearest unvisited."""
    remaining, route = list(block), []
    cursor: Hole | None = None
    while remaining:
        if cursor is None:
            nxt = min(remaining, key=_total_order)
        else:
            # Bound before the lambda so the closure is over a Hole, not an
            # Optional — mypy narrows the local, never the enclosing name.
            here = cursor
            nxt = min(remaining, key=lambda h: (_distance_sq(here, h), *_total_order(h)))
        remaining.remove(nxt)
        route.append(nxt)
        cursor = nxt
    return route


def _path_length(route: list[Hole]) -> float:
    """Sum of leg lengths. Real distance, because a reversal changes legs
    unequally and squared lengths would not compare correctly."""
    return sum(_distance_sq(a, b) ** 0.5 for a, b in pairwise(route))


def _two_opt(route: list[Hole]) -> list[Hole]:
    """Reverse the first segment that shortens the path, keeping the start fixed."""
    improved = True
    while improved:
        improved = False
        for i in range(1, len(route)):
            for j in range(i + 1, len(route)):
                candidate = route[:i] + route[i : j + 1][::-1] + route[j + 1 :]
                if _path_length(candidate) < _path_length(route) - 1e-9:
                    route, improved = candidate, True
    return route


def _routed(holes: Sequence[Hole]) -> list[Hole]:
    """Tool-major blocks, ascending by size, each routed on its own."""
    ordered: list[Hole] = []
    for diameter in sorted({hole.diameter_nm for hole in holes}):
        block = [hole for hole in holes if hole.diameter_nm == diameter]
        ordered += _two_opt(_nearest_neighbour(block))
    return ordered


class RouteHoles:
    """Plan the drilling sequence and number the holes along it.

    By default: one contiguous block per diameter, blocks ascending by size,
    each routed by nearest-neighbour then 2-opt on its own. A supplied ``key``
    replaces all of that with a flat ordering, so it can break tool contiguity.
    """

    name: ClassVar[str] = "route"

    def __init__(self, key: Callable[[Hole], SupportsRichComparison] | None = None) -> None:
        self.key = key

    def describe(self) -> StageRun:
        """Record ``default`` or the effective key callable's name."""
        if self.key is None:
            key = "default"
        else:
            key = getattr(self.key, "__name__", type(self.key).__name__)
        return StageRun(self.name, (("key", key),))

    def apply(self, data: DrillData) -> DrillData:
        ordered = (
            _routed(data.holes) if self.key is None else sorted(data.holes, key=self.key)
        )
        return data.with_holes(
            hole.with_number(number) for number, hole in enumerate(ordered, start=1)
        )
