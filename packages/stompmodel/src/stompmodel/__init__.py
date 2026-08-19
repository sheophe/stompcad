"""The values every stomp package exchanges.

Pure Python by construction: no kernel, no parser, no I/O beyond
serialisation. What lives here either crosses a package boundary with no
owner, or is a contract both tools implement identically. See ADR-0009.
"""

from __future__ import annotations

from .units import (
    NM_PER_MM,
    Millimetre,
    Nanometre,
    format_nm,
    mm_from_nm,
    nm_from_mm,
    scaled_nm,
)

__all__ = [
    "Nanometre",
    "Millimetre",
    "NM_PER_MM",
    "nm_from_mm",
    "scaled_nm",
    "mm_from_nm",
    "format_nm",
]
