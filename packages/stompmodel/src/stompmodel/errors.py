"""The error base every stomp package raises through.

One base, so a caller composing two tools catches one type rather than one
per tool. ``EmitterError`` lives here because ``DrillData.numbered()``
raises it and every package that emits an artefact can fail the same way.
``DocumentError`` for the same reason in the other direction: the shared
document has one codec, so refusing a foreign one is one failure, not one
per reader. See ADR-0009.
"""

from __future__ import annotations

__all__ = ["StompError", "EmitterError", "DocumentError"]


class StompError(Exception):
    """Base for every error raised by a stomp package."""


class EmitterError(StompError):
    """An emitter could not produce output from the data it was given."""


class DocumentError(StompError):
    """A serialised document is not the one this reader knows how to read.

    Distinct from ``EmitterError``: nothing was being produced, and the fault
    is the file's rather than the data's. A reader that guessed at an
    unfamiliar shape instead of raising this is how two packages come to
    disagree about one file.
    """
