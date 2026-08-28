"""Assemble placed, named, coloured solids into one XCAF document.

The one construction ``render_step`` needs and the writer's colour census
already walks: :func:`stompgeom.shapes.placed` locates a solid before it is
added, so no separate placement step runs afterwards for the census to miss.
See ADR-0008 on this joining the kernel layer only once a real second
consumer -- the assembly emitter -- needed it.
"""

from __future__ import annotations

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
    explicitly rather than left implicit -- see ``Order of work`` in
    ``docs/specs/stompcollider-technical.md``. Reads by shape, not by label:
    ``XCAFDoc_ColorTool`` resolves a shape straight back to the label it was
    assigned under, so ``solid`` is anything with a ``.shape`` -- a
    :class:`stompgeom.step.StepSolid`, never a raw ``TDF_Label``.
    """
    require_kernel()
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    found = Quantity_Color()
    if not colour_tool.GetColor(solid.shape, XCAFDoc_ColorType.XCAFDoc_ColorSurf, found):
        return None
    return (found.Red(), found.Green(), found.Blue())
