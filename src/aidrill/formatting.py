"""Shared numeric formatting.

Two emitters and the CLI report all print millimetre values. Only one of them
handled negative zero, so a hole at x = -0.0004 printed as ``X0.000`` in the
drill file and ``-0.00`` in the drawing's schedule -- two artifacts describing
the same hole, disagreeing in print.
"""

from __future__ import annotations

__all__ = ["format_mm"]


def format_mm(value: float, decimals: int = 3, signed: bool = False) -> str:
    """Format a millimetre value, normalising negative zero away.

    ``signed`` forces a leading ``+`` on positives, for coordinate tables where
    column alignment matters more than brevity.
    """
    text = f"{value:.{decimals}f}"
    if float(text) == 0.0:
        text = f"{0.0:.{decimals}f}"
    if signed and not text.startswith("-"):
        text = "+" + text
    return text
