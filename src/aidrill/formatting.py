"""Shared formatting for millimetre values."""

from __future__ import annotations

__all__ = ["format_mm"]


def format_mm(value: float, decimals: int = 3, signed: bool = False) -> str:
    """Format a millimetre value, normalising negative zero away.

    ``signed`` gives non-negative values a leading ``+``.
    """
    text = f"{value:.{decimals}f}"
    if float(text) == 0.0:
        text = f"{0.0:.{decimals}f}"
    if signed and not text.startswith("-"):
        text = "+" + text
    return text
