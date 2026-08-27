"""The compound builder: one idiom, one home."""

from __future__ import annotations

from typing import Any

import pytest

from stompgeom.shapes import compound


def _box(dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def _members(shape: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_compound_holds_every_shape_given() -> None:
    """The whole set arrives, not the first or the last."""
    assert len(_members(compound([_box(1, 1, 1), _box(2, 2, 2), _box(3, 3, 3)]))) == 3


def test_compound_of_nothing_is_an_empty_compound() -> None:
    """A level with no faces is a value, not an error; see this task's Interfaces."""
    from OCP.TopAbs import TopAbs_ShapeEnum

    empty = compound([])
    assert empty.ShapeType() == TopAbs_ShapeEnum.TopAbs_COMPOUND
    assert _members(empty) == []


def test_compound_accepts_a_generator() -> None:
    """Callers pass generator expressions; a one-pass consumer must not break."""
    assert len(_members(compound(_box(n, n, n) for n in (1, 2)))) == 2


def test_compound_preserves_the_order_shapes_were_given() -> None:
    """The member sequence must match the input sequence, not just its set.

    Three distinct-sized boxes give three distinguishable members; each
    box's own volume is a stable fingerprint that survives the trip through
    the kernel, whereas a raw ``TopoDS`` handle is not reliably comparable
    by identity across a build. Comparing volumes in traversal order proves
    ``compound`` neither reverses nor sorts what it was given -- the promise
    ``stompgeom.shapes.compound``'s docstring makes.
    """
    boxes = [_box(1, 1, 1), _box(2, 2, 2), _box(3, 3, 3)]
    recovered = [_volume(member) for member in _members(compound(boxes))]
    assert recovered == pytest.approx([1.0, 8.0, 27.0])
