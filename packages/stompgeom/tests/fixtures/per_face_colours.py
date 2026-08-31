"""Documents colouring sub-shapes, not only whole solids.

Two colour a box face by face; the third colours the solids inside one
part, a level above its faces and below the shape a reader hands back.
Built rather than committed: a binary fixture would fix one OpenCASCADE
version's encoding into the repository, which is the coupling the writer's
own guard exists to detect.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BROAD_COLOUR",
    "BROAD_FACE_AREA_MM2",
    "LARGER_SIDES_MM",
    "NARROW_COLOUR",
    "PART_NAME",
    "SIDES_MM",
    "SMALLER_SIDES_MM",
    "area_weighted_document",
    "per_face_coloured_document",
    "solid_by_solid_document",
]

#: The one box the two face-colouring builders cut their faces from.
#: Unequal in all three axes, so each pair of opposite faces has its own area.
SIDES_MM = (10.0, 20.0, 30.0)

#: One of the two widest faces, 20 x 30. Two of them carry ``BROAD_COLOUR``
#: and the remaining four carry ``NARROW_COLOUR``, so the broad colour holds
#: the larger area (1200 mm2 against 1000) while covering the smaller number
#: of faces. A rule counting faces answers the other colour.
BROAD_FACE_AREA_MM2 = 600.0

#: Neither is one of STEP's pre-defined colours; see ``tests/xcaf.py``.
BROAD_COLOUR = (0.21, 0.43, 0.65)
NARROW_COLOUR = (0.75, 0.31, 0.12)

#: The two boxes ``solid_by_solid_document`` bundles into one compound. The
#: larger carries ``BROAD_COLOUR`` and holds the greater surface, so it
#: decides the compound's colour; the smaller carries ``NARROW_COLOUR``.
LARGER_SIDES_MM = (20.0, 20.0, 20.0)
SMALLER_SIDES_MM = (2.0, 2.0, 2.0)

#: What that compound's one component is called, so a test can find it.
PART_NAME = "substrate"


def per_face_coloured_document() -> Any:
    """One box whose six faces carry six different surface colours."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    box = BRepPrimAPI_MakeBox(*SIDES_MM).Shape()
    shape_tool.AddShape(box, True)

    explorer = TopExp_Explorer(box, TopAbs_ShapeEnum.TopAbs_FACE)
    index = 0
    while explorer.More():
        shade = (index + 1) / 8.0
        color_tool.SetColor(
            explorer.Current(),
            Quantity_Color(shade, 1.0 - shade, 0.5, Quantity_TypeOfColor.Quantity_TOC_RGB),
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )
        index += 1
        explorer.Next()
    return document


def area_weighted_document() -> Any:
    """One box whose two widest faces disagree with its other four.

    Built so the colour holding the most surface is not the colour on the
    most faces, which is what separates a rule weighing area from one
    counting faces. See ``BROAD_FACE_AREA_MM2``.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.GProp import GProp_GProps
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    box = BRepPrimAPI_MakeBox(*SIDES_MM).Shape()
    shape_tool.AddShape(box, True)

    explorer = TopExp_Explorer(box, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(explorer.Current(), properties)
        broad = round(properties.Mass() - BROAD_FACE_AREA_MM2, 6) == 0
        colour = BROAD_COLOUR if broad else NARROW_COLOUR
        color_tool.SetColor(
            explorer.Current(),
            Quantity_Color(*colour, Quantity_TypeOfColor.Quantity_TOC_RGB),
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )
        explorer.Next()
    return document


def solid_by_solid_document() -> Any:
    """An assembly whose one part is a compound of two coloured solids.

    A board substrate arrives this way -- the colour sits on the solid, a
    level below the shape the reader hands back and a level above the faces,
    and the part is a located component besides. Neither the compound nor
    any face carries a colour, so a rule reading only those two answers
    nothing for a part a file plainly colours.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt, gp_Trsf, gp_Vec
    from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    from stompgeom.shapes import compound

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    larger = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), *LARGER_SIDES_MM).Shape()
    smaller = BRepPrimAPI_MakeBox(gp_Pnt(40.0, 0.0, 0.0), *SMALLER_SIDES_MM).Shape()
    product = shape_tool.AddShape(compound([larger, smaller]), False)
    TDataStd_Name.Set_s(product, TCollection_ExtendedString(PART_NAME))

    for solid, colour in ((larger, BROAD_COLOUR), (smaller, NARROW_COLOUR)):
        color_tool.SetColor(
            solid,
            Quantity_Color(*colour, Quantity_TypeOfColor.Quantity_TOC_RGB),
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )

    moved = gp_Trsf()
    moved.SetTranslation(gp_Vec(0.0, 0.0, 60.0))
    assembly = shape_tool.NewShape()
    TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("board"))
    component = shape_tool.AddComponent(assembly, product, TopLoc_Location(moved))
    TDataStd_Name.Set_s(component, TCollection_ExtendedString(PART_NAME))
    shape_tool.UpdateAssemblies()
    return document
