"""The one protocol that is stompdrill's alone.

Stage, Pipeline and Emitter are generic and live in stompmodel. Source does
not: RawDrillData is artwork, and stompcollider's board reader returns
something else entirely. See ADR-0009.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .quantise import RawDrillData

__all__ = ["Source"]


@runtime_checkable
class Source(Protocol):
    """Read artwork as unquantised finite millimetres in ``RawDrillData``.

    Coordinates are Y-up and centred on the reference outline when present;
    otherwise they remain page-relative and the missing frame is diagnosed.
    """

    def read(self) -> RawDrillData: ...
