"""Seats PCB models inside a drilled case and reports where they clash.

The package root exposes the canonicalisation entry point and what it
reads, so a caller never guesses a submodule -- see the module layout in
``docs/specs/stompcollider-technical.md``. ``Match``, ``Seat``,
``Clashes``, ``BoardSource`` and both emitters land here; the command
line does not, because a console script is how one is reached and
``stompdrill``'s root exports no ``main`` either. Domain values live in
``stompcollider.model``, the reader's float millimetres in ``raw``.
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
