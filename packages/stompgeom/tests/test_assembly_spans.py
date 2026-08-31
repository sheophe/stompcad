"""The assembly's own extent, per axis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stompgeom.step import assembly_spans


@dataclass(frozen=True)
class _Solid:
    name: str
    shape: Any


def _box(dx: float, dy: float, dz: float, at: tuple[float, float, float]) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


@dataclass(frozen=True)
class _Document:
    solids: tuple[_Solid, ...]


def test_spans_cover_every_solid_not_the_first() -> None:
    """Two disjoint solids span their union, so neither alone can satisfy it."""
    document = _Document((
        _Solid("a", _box(10.0, 1.0, 1.0, (0.0, 0.0, 0.0))),
        _Solid("b", _box(1.0, 20.0, 1.0, (0.0, 0.0, 0.0))),
    ))
    x, y, z = assembly_spans(document)  # type: ignore[arg-type]
    assert round(x, 6) == 10.0
    assert round(y, 6) == 20.0


def test_spans_measure_extent_not_distance_from_the_origin() -> None:
    """A solid placed away from the origin spans its own size, not its reach."""
    document = _Document((_Solid("a", _box(3.0, 4.0, 5.0, (100.0, 0.0, 0.0))),))
    x, _y, _z = assembly_spans(document)  # type: ignore[arg-type]
    assert round(x, 6) == 3.0
