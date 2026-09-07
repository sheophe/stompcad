"""Progress as a weighted tree, folded to one position.

A run is a tree: the root spans the whole invocation, each node divides its
span among its children, and each leaf is one countable piece of work.
Accumulating completed spans left to right gives a single number between 0
and 1, which is what a bar draws. Nothing here measures time, and no value
depends on a previous run -- see ``docs/specs/stompcad-technical.md``.

Both tools report into one tree because ``stompcad`` renders one bar over
both, which is the ADR-0009 rule 2 behaviour admitting this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Protocol, runtime_checkable

__all__ = ["Sink", "Scope", "NullScope", "NO_PROGRESS", "track"]


class Sink(Protocol):
    """Receives the folded position and the labels of the active branch."""

    def update(self, position: float, path: tuple[str, ...]) -> None: ...


@runtime_checkable
class Scope(Protocol):
    """One span of the run. Divide it, name it, or let it complete."""

    def steps(self, count: int) -> Iterator[Scope]:
        """Divide this span into ``count`` equal slots, one scope each."""
        ...

    def parts(self, *weights: float) -> Iterator[Scope]:
        """Divide this span in proportion to ``weights``, one scope each."""
        ...

    def label(self, name: str) -> None:
        """Name the work happening in this span."""
        ...


class NullScope:
    """A scope that reports nothing, and the default wherever one is optional.

    Divides like a real scope so that a caller written against ``Scope``
    runs unchanged with no observer: the loops still execute the same
    number of times, and only the reporting is absent.
    """

    __slots__ = ()

    def steps(self, count: int) -> Iterator[Scope]:
        if count < 0:
            raise ValueError(f"a division needs a count of 0 or more, not {count}")
        return iter([self] * count)

    def parts(self, *weights: float) -> Iterator[Scope]:
        return iter([self] * len(weights))

    def label(self, name: str) -> None:
        return None


#: The null scope. One instance, because it holds nothing.
NO_PROGRESS: Scope = NullScope()


class _Run:
    """One invocation's position and the sink watching it.

    The position is a maximum rather than an assignment, which is what
    makes monotonicity a property of the type: a child that under-reported
    cannot pull the bar backwards when its parent moves on.
    """

    __slots__ = ("_sink", "_position")

    def __init__(self, sink: Sink) -> None:
        self._sink = sink
        self._position = 0.0

    def advance(self, position: float, path: tuple[str, ...]) -> None:
        if position > self._position:
            self._position = position
        self._sink.update(self._position, path)


class _Node:
    """A half-open span of the run, and the node it was divided from."""

    __slots__ = ("_run", "_lo", "_hi", "_parent", "_name")

    def __init__(
        self, run: _Run, lo: float, hi: float, parent: _Node | None
    ) -> None:
        self._run = run
        self._lo = lo
        self._hi = hi
        self._parent = parent
        self._name: str | None = None

    def _path(self) -> tuple[str, ...]:
        names: list[str] = []
        node: _Node | None = self
        while node is not None:
            if node._name is not None:
                names.append(node._name)
            node = node._parent
        return tuple(reversed(names))

    def label(self, name: str) -> None:
        self._name = name
        self._run.advance(self._lo, self._path())

    def steps(self, count: int) -> Iterator[Scope]:
        if count < 0:
            raise ValueError(f"a division needs a count of 0 or more, not {count}")
        return self._divide([1.0] * count)

    def parts(self, *weights: float) -> Iterator[Scope]:
        return self._divide(weights)

    def _divide(self, weights: Sequence[float]) -> Iterator[Scope]:
        """Yield one child per weight, then close this node at its own end.

        Positions are computed from a running total rather than from the
        previous child's end, so a long division does not accumulate float
        error along the way. ``sum(weights)`` and the running ``done`` add
        the same values in different orders, so they can disagree by a
        rounding step; each bound is clamped to this node's own span so
        that disagreement can never let a child claim territory past its
        parent's end.
        """
        total = float(sum(weights))
        span = self._hi - self._lo
        try:
            if total <= 0.0:
                return
            done = 0.0
            for weight in weights:
                if weight < 0.0:
                    raise ValueError(f"a weight cannot be negative: {weight}")
                lo = min(self._hi, self._lo + span * (done / total))
                done += weight
                hi = min(self._hi, self._lo + span * (done / total))
                yield _Node(self._run, lo, hi, self)
                self._run.advance(hi, self._path())
        finally:
            self._run.advance(self._hi, self._path())


@contextmanager
def track(sink: Sink) -> Iterator[Scope]:
    """Open a run reporting into ``sink``, and complete it on the way out.

    The exit advances to 1.0 whatever the body did, so a run that raised
    or returned early still leaves the sink at a finished position rather
    than at whatever fraction it had reached.
    """
    run = _Run(sink)
    root = _Node(run, 0.0, 1.0, None)
    try:
        yield root
    finally:
        run.advance(1.0, ())
