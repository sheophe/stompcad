"""A document colouring sub-shapes, not only whole solids.

Built rather than committed: a binary fixture would fix one OpenCASCADE
version's encoding into the repository, which is the coupling the writer's
own guard exists to detect.
"""

from __future__ import annotations

from typing import Any

__all__ = ["per_face_coloured_document"]


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

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
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
