"""Exact inclusive tolerance comparisons for whole-nanometre lengths."""

from __future__ import annotations

__all__ = ["within"]


def within(a: int, b: int, tolerance: int) -> bool:
    """Return ``abs(a - b) <= tolerance`` for whole-nanometre lengths."""
    return abs(a - b) <= tolerance
