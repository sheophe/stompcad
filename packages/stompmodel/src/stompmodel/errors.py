"""The error base every stomp package raises through, and the shared members.

Each tool's own base descends from ``StompError``. ADR-0009 holds the
argument for one base and for what is admitted beside it.
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
