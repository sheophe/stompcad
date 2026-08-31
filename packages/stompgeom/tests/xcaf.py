"""An XCAF assembly built in memory, so this package can drive its own writer.

No fixture file and no download: the kernel is unconditional here, so a
document with the three features the writer normalises -- an assembly, so
there are usage occurrences; a nameless leaf, so the translator generates its
volatile wrapper product; and two coloured leaves, so the colour chains are
reordered -- can be constructed outright. See ADR-0008 on each member
proving itself alone.
"""

from __future__ import annotations

from typing import Any

__all__ = ["BODY_COLOUR", "BODY_SIZE_MM", "LID_COLOUR", "build_document"]

#: The named leaf's own extent, asserted after a round trip through the file.
#: Deliberately unequal in all three axes, so a transposed bounding box fails.
BODY_SIZE_MM = (11.0, 23.0, 3.0)

#: Neither is one of STEP's pre-defined colours. A pure red or green is
#: written as ``DRAUGHTING_PRE_DEFINED_COLOUR`` instead of ``COLOUR_RGB``,
#: which is not the chain ``_reslot_colours`` reorders.
BODY_COLOUR = (0.21, 0.43, 0.65)
LID_COLOUR = (0.75, 0.31, 0.12)


def build_document() -> Any:
    """A three-leaf XCAF assembly: a named coloured body, a named coloured
    lid, and a nameless uncoloured bracket."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colours = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    def leaf(name: str, size: tuple[float, float, float], colour: Any) -> Any:
        box = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), *size).Shape()
        label = shapes.AddShape(box, False)
        if name:
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
        else:
            # ``AddShape`` names a label "SOLID" of its own accord, and a
            # named product is exactly what suppresses the wrapper.
            label.ForgetAttribute(TDataStd_Name.GetID_s())
        if colour is not None:
            colours.SetColor(
                label,
                Quantity_Color(*colour, Quantity_TOC_RGB),
                XCAFDoc_ColorType.XCAFDoc_ColorSurf,
            )
        return label

    body = leaf("body", BODY_SIZE_MM, BODY_COLOUR)
    lid = leaf("lid", (11.0, 23.0, 1.0), LID_COLOUR)
    bracket = leaf("", (2.0, 2.0, 2.0), None)

    lifted = gp_Trsf()
    lifted.SetTranslation(gp_Vec(0.0, 0.0, 5.0))

    assembly = shapes.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("enclosure"))
    # A component label carries its own name, distinct from the product it
    # refers to. It is the one the reader hands back, so a real assembly's
    # components are named here too rather than left to the kernel.
    for name, label, placement in (
        ("body", body, TopLoc_Location()),
        ("lid", lid, TopLoc_Location(lifted)),
        ("bracket", bracket, TopLoc_Location()),
    ):
        component = shapes.AddComponent(assembly, label, placement)
        TDataStd_Name.Set_s(component, TCollection_ExtendedString(name))
    shapes.UpdateAssemblies()
    return document
