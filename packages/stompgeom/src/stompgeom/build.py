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

    for solid in solids:
        shape = solid.shape if solid.placement is None else placed(solid.shape, solid.placement)
        label = shape_tool.AddShape(_addable(shape, solid.colour), False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(solid.name))
        if solid.colour is not None:
            colour_tool.SetColor(
                label,
                Quantity_Color(*solid.colour, Quantity_TOC_RGB),
                XCAFDoc_ColorType.XCAFDoc_ColorSurf,
            )
    return document


def _addable(shape: Any, colour: tuple[float, float, float] | None) -> Any:
    """``shape`` as something ``AddShape`` will give a label of its own.

    ``AddShape`` makes a *located* shape a reference to the unlocated
    original, and a colour on a reference becomes a
    ``PRESENTATION_STYLE_BY_CONTEXT`` chain -- one ``solid_colour`` cannot
    resolve, the census does not count and the colour region cannot
    canonicalise. A one-solid compound is identity-located, so the label
    owns its shape and no geometry is rebuilt. Only a coloured solid needs
    it: an uncoloured reference writes correctly and shares its base.
    """
    if colour is None or shape.Location().IsIdentity():
        return shape
    return compound([shape])


def solid_colour(document: TDocStd_Document, solid: Any) -> tuple[float, float, float] | None:
    """``solid``'s own surface colour in ``document``, or ``None`` if it has none.

    The published reading half of ``build_document``'s colouring, named
    explicitly rather than left implicit -- see
    ``stompcollider-technical.md:598-602``. Reads by shape, not by label:
    ``XCAFDoc_ColorTool`` resolves a shape straight back to the label it was
    assigned under. ``solid`` is anything with a ``.shape`` -- a
    :class:`stompgeom.step.StepSolid`, never a raw ``TDF_Label`` -- despite
    the brief's paraphrase naming this parameter "label".
    """
    require_kernel()
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    found = Quantity_Color()
    if not colour_tool.GetColor(solid.shape, XCAFDoc_ColorType.XCAFDoc_ColorSurf, found):
        return None
    return (found.Red(), found.Green(), found.Blue())
