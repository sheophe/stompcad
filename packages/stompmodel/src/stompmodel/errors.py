"""The error base every stomp package raises through.

One base, so a caller composing two tools catches one type rather than one
per tool. ``EmitterError`` lives here because ``DrillData.numbered()``
raises it and every package that emits an artefact can fail the same way.
See ADR-0009.
"""

from __future__ import annotations

__all__ = ["StompError", "EmitterError"]


class StompError(Exception):
    """Base for every error raised by a stomp package."""


class EmitterError(StompError):
    """An emitter could not produce output from the data it was given."""
