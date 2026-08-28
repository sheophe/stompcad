"""The head of the pipeline: whatever a run reads, turned into ``RawBoards``.

One of the three places this package touches the kernel, and it touches it
through ``stompgeom`` alone -- ``tests/test_package_boundary.py`` is what
keeps that true. See ADR-0001 for the flow and ADR-0008 for the layering.
"""

from __future__ import annotations

from .step import BoardGeometry, BoardScan, BoardSource

__all__ = ["BoardSource", "BoardScan", "BoardGeometry"]
