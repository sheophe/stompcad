"""The first thing the run's process runs, and the only thing it imports.

``spawn`` needs a target it can import by name, and importing the server
means importing ``drive`` and everything under it. Naming this instead
keeps that import inside the process that does the work: the interface
loads a module with no dependencies at all, and the weight arrives where
it is used.
"""

from __future__ import annotations

from typing import Any

__all__ = ["child"]


def child(commands: Any, events: Any, stopping: Any, entry: str, busy: Any) -> None:
    """Hand straight over to the server, importing it here rather than above."""
    from .serve import serve

    serve(commands, events, stopping, entry, busy)
