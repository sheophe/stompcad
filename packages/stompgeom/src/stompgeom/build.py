"""Assemble placed, named, coloured solids into one XCAF document.

The one construction ``render_step`` needs and the writer's colour census
already walks: :func:`stompgeom.shapes.placed` locates a solid before it is
added, so no separate placement step runs afterwards for the census to miss.
See ADR-0008 on this joining the kernel layer only once a real second
consumer -- the assembly emitter -- needed it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stompmodel.frames import RigidTransform

from .kernel import require_kernel
from .shapes import compound, placed

if TYPE_CHECKING:
    # Real OCP name for readability only; resolved to Any either way by
    # this workspace's mypy configuration. See ADR-0008.
    from OCP.TDocStd import TDocStd_Document

__all__ = ["PlacedSolid", "build_document", "solid_colour"]

#: Components in an RGB colour.
_COLOUR_COMPONENTS = 3


@dataclass(frozen=True, slots=True)
class PlacedSolid:
    """One solid on its way into a document: named, optionally coloured and moved.

    ``placement`` is ``None`` for "leave where it was", not identity applied
    -- the two must stay distinguishable, since an identity rotation and
    translation could otherwise silence a placement bug entirely.
    """

    shape: Any
    name: str
    colour: tuple[float, float, float] | None
    placement: RigidTransform | None

    def __post_init__(self) -> None:
        """Refuse a shape or a colour the document could not take.

        ``Quantity_Color`` accepts three components in ``0.0..1.0`` and
        raises from inside OCC otherwise, about a colour, with nothing to
        say which solid carried it. A null shape -- ``None``, or an OCC
        shape whose own ``IsNull()`` is true -- is refused for the same
        reason. ``placement`` needs no check here: ``RigidTransform``
        validates itself, and ``None`` is the stated "leave where it was".
        """
        if self.shape is None or self.shape.IsNull():
            raise ValueError(f"PlacedSolid.shape must be a kernel shape, not {self.shape!r}")
        if self.colour is None:
            return
        if len(self.colour) != _COLOUR_COMPONENTS:
            raise ValueError(
                f"PlacedSolid.colour must have exactly three components, "
                f"not {len(self.colour)}"
            )
        for component in self.colour:
            if not isinstance(component, (int, float)) or not math.isfinite(component):
                raise ValueError(f"PlacedSolid.colour must be finite, not {self.colour!r}")
            if not 0.0 <= component <= 1.0:
                raise ValueError(
                    f"PlacedSolid.colour components run 0.0 to 1.0, not {self.colour!r}"
                )


def build_document(solids: Sequence[PlacedSolid]) -> Any:
    """A ``TDocStd_Document`` ready for :func:`stompgeom.writer.render_step`.

    Each solid becomes its own free (non-assembly) shape: this package does
    not yet own placing one document's solids into a shared parent, only
    placing a single solid before it is added. Colour is set through
    ``XCAFDoc_ColorTool.SetColor`` on the very label the shape tool handed
    back, which is the route the writer's colour census walks; ``_addable``
    is what keeps that label the owner of the shape. See ADR-0008 and
    ``stompgeom.writer._count_colour_assignments``.
    """
    require_kernel()
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    shapes = [
        solid.shape if solid.placement is None else placed(solid.shape, solid.placement)
        for solid in solids
    ]
    for solid, shape, collides in zip(solids, shapes, _collisions(shapes)):
        label = shape_tool.AddShape(_addable(shape, solid.colour, collides), False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(solid.name))
        if solid.colour is not None:
            colour_tool.SetColor(
                label,
                Quantity_Color(*solid.colour, Quantity_TOC_RGB),
                XCAFDoc_ColorType.XCAFDoc_ColorSurf,
            )
    return document


def _collisions(shapes: Sequence[Any]) -> tuple[bool, ...]:
    """Which of ``shapes`` would otherwise lose their label to another.

    ``AddShape`` refers a *located* shape to a label holding its unlocated
    base -- reusing a free one when the batch already added it -- so an
    unlocated shape is the only one a sibling can take over; two located ones
    never collide, which is measured. ``IsSame`` is the kernel's own identity
    and never a Python ``id()``: an address varies between processes, and
    structure decided from one is the non-determinism the writer erases.
    Pairwise, because a batch is one assembly's solids -- tens, not thousands.
    """
    from OCP.TopLoc import TopLoc_Location

    bases = [shape.Located(TopLoc_Location()) for shape in shapes]
    return tuple(
        shape.Location().IsIdentity()
        and any(
            bases[other].IsSame(bases[position])
            for other in range(len(bases))
            if other != position
        )
        for position, shape in enumerate(shapes)
    )


def _addable(
    shape: Any, colour: tuple[float, float, float] | None, collides: bool
) -> Any:
    """``shape`` as something ``AddShape`` will give a label of its own.

    Two reasons a solid needs one. A colour on a located shape lands on a
    reference, written as a ``PRESENTATION_STYLE_BY_CONTEXT`` chain
    ``solid_colour`` cannot resolve; and a shape ``_collisions`` reports would
    be taken over by a sibling and lost outright. A one-solid compound is a
    shape of its own, so the label owns it and no geometry is rebuilt. Needing
    one is a fact about the batch, not the solid: the same input always builds
    the same document, which is all ADR-0006 asks.
    """
    if collides or (colour is not None and not shape.Location().IsIdentity()):
        return compound([shape])
    return shape


def solid_colour(document: TDocStd_Document, solid: Any) -> tuple[float, float, float] | None:
    """``solid``'s own surface colour in ``document``, or ``None`` if it has none.

    The published reading half of ``build_document``'s colouring, named
    explicitly rather than left implicit. Reads by shape, not by label, so
    ``solid`` is anything with a ``.shape`` -- a
    :class:`stompgeom.step.StepSolid`, never a raw ``TDF_Label``. Three
    routes, because a file records a colour in three shapes; see
    :func:`_recorded_colour` and :func:`_broadest_colour`.
    """
    require_kernel()
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    own = _recorded_colour(colour_tool, solid.shape)
    if own is not None:
        return own
    return _broadest_colour(colour_tool, solid.shape)


def _recorded_colour(colour_tool: Any, shape: Any) -> tuple[float, float, float] | None:
    """The surface colour recorded against ``shape`` itself, or ``None``.

    Two lookups, not one. ``XCAFDoc_ColorTool`` resolves a shape back to the
    label it was assigned under, and an assembly component's shape is its
    product's shape carried under a location, while the colour was assigned
    to the product. So the located shape is asked first -- an instance colour
    belongs to that instance and must win -- and the unlocated base second.
    """
    from OCP.Quantity import Quantity_Color
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_ColorType

    for candidate in (shape, shape.Located(TopLoc_Location())):
        found = Quantity_Color()
        if colour_tool.GetColor(candidate, XCAFDoc_ColorType.XCAFDoc_ColorSurf, found):
            return (found.Red(), found.Green(), found.Blue())
    return None


def _broadest_colour(colour_tool: Any, shape: Any) -> tuple[float, float, float] | None:
    """The colour covering most of ``shape``'s surface, or ``None`` for none.

    What a component modelled face by face records: no colour on the solid,
    one on each face. Weighed by area rather than by face count, because a
    part is the colour of its body and not of its many small leads. Ties
    fall to the lowest RGB triple, so the answer never depends on the order
    the kernel walks the faces in. ``None`` stays ``None``: a solid nothing
    coloured has no broadest colour to report.
    """
    from OCP.TopAbs import TopAbs_ShapeEnum

    areas: dict[tuple[float, float, float], float] = {}
    for part, inherited in _colour_bearing_parts(colour_tool, shape):
        for face in _sub_shapes(part, TopAbs_ShapeEnum.TopAbs_FACE):
            colour = _recorded_colour(colour_tool, face) or inherited
            if colour is None:
                continue
            areas[colour] = areas.get(colour, 0.0) + _surface_area(face)
    if not areas:
        return None
    return min(areas, key=lambda colour: (-areas[colour], colour))


def _colour_bearing_parts(
    colour_tool: Any, shape: Any
) -> list[tuple[Any, tuple[float, float, float] | None]]:
    """``shape``'s solids, each with the colour its own faces fall back to.

    A leaf shape is routinely a compound of solids, and a file may colour
    the solid rather than its faces -- a bare board substrate does exactly
    that. A shape holding no solid at all is walked as one part with nothing
    to inherit, so a loose shell is not silently dropped.
    """
    from OCP.TopAbs import TopAbs_ShapeEnum

    solids = _sub_shapes(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    if not solids:
        return [(shape, None)]
    return [(solid, _recorded_colour(colour_tool, solid)) for solid in solids]


def _sub_shapes(shape: Any, kind: Any) -> list[Any]:
    """Every sub-shape of ``shape`` of the given ``TopAbs_ShapeEnum`` kind.

    Materialised rather than yielded: the explorer holds kernel state over
    the shape it is walking, and the callers here walk one kind while
    resolving colour against another.
    """
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, kind)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _surface_area(face: Any) -> float:
    """``face``'s area in square millimetres, as the kernel measures it."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, properties)
    return float(properties.Mass())
