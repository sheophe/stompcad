"""Deterministic pipeline-level hole ordering shared by every emitter."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

from ..model import DrillData, Hole, StageRun

if TYPE_CHECKING:
    # ``sorted`` needs a key whose result can be compared with ``<``. Spelling
    # that as ``object`` types the parameter by what a key *is* rather than by
    # what this stage does with it, and ``SortHoles(key=lambda h: h)`` then
    # type-checks cleanly and raises TypeError on a real panel. _typeshed is
    # not importable at runtime, which is why the import is guarded.
    from _typeshed import SupportsRichComparison

__all__ = ["SortHoles"]


def _reading_order(hole: Hole) -> tuple[int, int]:
    """Descending Y, then ascending X — the order you would read the panel in."""
    return (-hole.y_nm, hole.x_nm)


class SortHoles:
    """Sort holes by ``key`` (default: descending Y, then ascending X)."""

    name: ClassVar[str] = "sort"

    def __init__(self, key: Callable[[Hole], SupportsRichComparison] | None = None) -> None:
        self.key = _reading_order if key is None else key

    def describe(self) -> StageRun:
        """Record ``default`` or the effective key callable's name."""
        if self.key is _reading_order:
            key = "default"
        else:
            key = getattr(self.key, "__name__", type(self.key).__name__)
        return StageRun(self.name, (("key", key),))

    def apply(self, data: DrillData) -> DrillData:
        return data.with_holes(sorted(data.holes, key=self.key))
