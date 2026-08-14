"""Deterministic hole ordering.

Ordering is a pipeline concern, not an emitter one: the Excellon file, the
drawing's balloon numbers and the JSON must list holes in the same sequence, or
an operator checking one against another has to work out why they differ.
"""

from __future__ import annotations

from typing import Callable, ClassVar

from ..model import DrillData, Hole

__all__ = ["SortHoles"]


def _reading_order(hole: Hole) -> tuple[float, float]:
    """Descending Y, then ascending X — the order you would read the panel in."""
    return (-hole.y, hole.x)


class SortHoles:
    """Sort holes by ``key`` (default: descending Y, then ascending X)."""

    name: ClassVar[str] = "sort"

    def __init__(self, key: Callable[[Hole], object] | None = None) -> None:
        self.key = _reading_order if key is None else key

    def apply(self, data: DrillData) -> DrillData:
        return data.with_holes(sorted(data.holes, key=self.key))
