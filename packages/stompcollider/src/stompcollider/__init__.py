"""Seats PCB models inside a drilled case and reports where they clash.

Deliberately empty of exports for now: ``Source``, ``canonicalise``,
``Match``, ``Seat`` and the emitters land here as later tasks add them,
mirroring ``stompdrill``'s own root -- see
``docs/specs/stompcollider-technical.md``'s module layout. The values this
task adds live in ``stompcollider.model``, one name, one home.
"""

from __future__ import annotations

__all__: list[str] = []
