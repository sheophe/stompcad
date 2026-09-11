"""Cancellation: a sink that raises, and the code a stopped run exits with.

Spec decision 9. `Cancelled` derives from `BaseException`, not `Exception`,
for the reason `KeyboardInterrupt` does: a handler written for a fault must
not absorb it. ADR-0001's staged writes discard their temporaries as the
stack unwinds, which is what makes a cancelled run leave nothing behind.
The progress protocol itself does not change; `CancellingSink` is
`stompcad`'s own wrapper around whatever sink a run was already using.
"""

from __future__ import annotations

from collections.abc import Callable

from stompmodel.progress import Sink

__all__ = ["Cancelled", "CancellingSink", "EXIT_CANCELLED"]

#: Reserved for a stop the user asked for; no other path may produce it.
#: The shell's own convention for a process ended by SIGINT: 128 + 2.
EXIT_CANCELLED: int = 130


class Cancelled(BaseException):
    """A stop the user asked for.

    Not an ``Exception``: a handler written for a fault must not absorb it,
    which is why ``KeyboardInterrupt`` is shaped alike.
    """


class CancellingSink:
    """Delegates to ``inner`` until ``stop()`` is true, then raises instead.

    ``stop`` is polled once per reported leaf, so cancellation is noticed
    at the same granularity progress already reports at -- no finer.
    """

    __slots__ = ("_inner", "_stop")

    def __init__(self, inner: Sink, stop: Callable[[], bool]) -> None:
        self._inner = inner
        self._stop = stop

    def update(self, position: float, path: tuple[str, ...]) -> None:
        if self._stop():
            raise Cancelled(f"cancelled at {position:.0%}")
        self._inner.update(position, path)
