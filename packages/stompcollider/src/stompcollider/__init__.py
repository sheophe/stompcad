"""Seats PCB models inside a drilled case and reports where they clash.

The package root exposes the canonicalisation entry point and what it
reads, so a caller never has to guess a submodule -- see
``docs/specs/stompcollider-technical.md``'s module layout. ``Match``, ``Seat``,
``Clashes``, ``BoardSource`` and both emitters land here, mirroring
``stompdrill``'s own root. The command line does not: a console script is
how a command line is reached, and ``stompdrill``'s root exports no
``main`` either. The domain values live in
``stompcollider.model``; the float-millimetre reader types live in
``stompcollider.raw`` -- one name, one home, each.
"""

from __future__ import annotations

from .canonicalise import canonicalise
from .clash import Clashes
from .emitters import AssemblyEmitter, ReportEmitter
from .match import Match
from .raw import RawBoard, RawBoards, RawComponent, RawCylinder
from .seat import Seat
from .sources import BoardSource

__all__ = [
    "BoardSource",
    "canonicalise",
    "Match",
    "Seat",
    "Clashes",
    "ReportEmitter",
    "AssemblyEmitter",
    "RawCylinder",
    "RawComponent",
    "RawBoard",
    "RawBoards",
]
