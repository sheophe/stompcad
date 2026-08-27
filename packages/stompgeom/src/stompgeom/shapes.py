"""Assembling kernel shapes into one shape.

The topological side of geometry, as distinct from the format side that
reads and writes STEP. See ADR-0008.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .kernel import require_kernel

__all__ = ["compound"]


def compound(shapes: Iterable[Any]) -> Any:
    """Bundle ``shapes`` into one ``TopoDS_Compound``, in the order given.

    An empty iterable yields an empty compound rather than raising: a level
    with no faces is a legitimate value, and refusing it here would push the
    same check into every caller.
    """
    require_kernel()
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    built = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(built)
    for shape in shapes:
        builder.Add(built, shape)
    return built
