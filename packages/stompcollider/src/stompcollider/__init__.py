"""Seats PCB models inside a drilled case and reports where they clash.

The package root exposes the canonicalisation entry point and what it
reads, so a caller never has to guess a submodule -- see
``docs/specs/stompcollider-technical.md``'s module layout. ``Match`` and
``Seat`` land here now; ``Source`` and the emitters join it as later tasks
add them, mirroring ``stompdrill``'s own root. The domain values live in
``stompcollider.model``; the float-millimetre reader types live in
``stompcollider.raw`` -- one name, one home, each.
"""

from __future__ import annotations

from .canonicalise import canonicalise
from .match import Match
from .raw import RawBoard, RawBoards, RawComponent, RawCylinder
from .seat import Seat

__all__ = [
    "canonicalise",
    "Match",
    "Seat",
    "RawCylinder",
    "RawComponent",
    "RawBoard",
    "RawBoards",
]
