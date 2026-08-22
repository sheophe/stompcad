"""This package's error base, beneath the workspace's own."""

from __future__ import annotations

from stompmodel.errors import StompError

__all__ = ["StompgeomError"]


class StompgeomError(StompError):
    """Base for every error raised by stompgeom alone."""
