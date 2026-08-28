"""This package's error base, beneath the workspace's own, and its usage reason.

``UsageError`` is separate from the base because the CLI's own contract
distinguishes exit 3 (a bad flag, resolved before any file opens) from exit 2
(a finding raised while processing real data) -- see ADR-0009.
"""

from __future__ import annotations

from stompmodel.errors import StompError

__all__ = ["StompcolliderError", "UsageError", "NoSubstrateError"]


class StompcolliderError(StompError):
    """Base for every error raised by stompcollider alone."""


class UsageError(StompcolliderError):
    """A malformed flag or invocation, resolved before any file is opened."""


class NoSubstrateError(StompcolliderError):
    """A model holds no board body to group components onto.

    Its own type because a caller reading several files reports this one as
    the ``no-substrate`` diagnostic the spec's table lists and carries on to
    the next file -- a decision that must not rest on reading a message.
    """
