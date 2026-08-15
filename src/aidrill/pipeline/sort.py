"""Deterministic hole ordering.

Ordering is a pipeline concern, not an emitter one: the Excellon file, the
drawing's balloon numbers and the JSON must list holes in the same sequence, or
an operator checking one against another has to work out why they differ.
"""

from __future__ import annotations

from typing import Callable, ClassVar

from ..model import DrillData, Hole, StageRun

__all__ = ["SortHoles"]


def _reading_order(hole: Hole) -> tuple[float, float]:
    """Descending Y, then ascending X — the order you would read the panel in."""
    return (-hole.y, hole.x)


class SortHoles:
    """Sort holes by ``key`` (default: descending Y, then ascending X)."""

    name: ClassVar[str] = "sort"

    def __init__(self, key: Callable[[Hole], object] | None = None) -> None:
        self.key = _reading_order if key is None else key

    def describe(self) -> StageRun:
        """Name the ordering that was applied, not the argument that chose it.

        ``SortHoles()`` and ``SortHoles(key=None)`` order holes identically, so
        both report ``"default"``; anything else reports the callable's own
        ``__name__``, which is the only handle a reader has on what it did.
        """
        if self.key is _reading_order:
            key = "default"
        else:
            key = getattr(self.key, "__name__", type(self.key).__name__)
        return StageRun(self.name, (("key", key),))

    def apply(self, data: DrillData) -> DrillData:
        return data.with_holes(sorted(data.holes, key=self.key))
