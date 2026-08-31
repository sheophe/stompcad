"""A document whose distinct shapes share one colour, built through OCP.

Built rather than committed, for the same reason as ``per_face_colours``:
a binary fixture would fix one OpenCASCADE version's encoding into the
repository. Distinct shapes sharing one RGB value is the shape that makes
``STEPCAFControl_Writer`` choose, itself, which one's colour chain carries
the inline definition -- a choice this module's reslot cannot see or
control, unlike which physical slot a chain lands in.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SHARED_COLOUR", "repeated_colour_document"]

#: Not one of STEP's pre-defined colours (a pure red or green is written as
#: DRAUGHTING_PRE_DEFINED_COLOUR instead of COLOUR_RGB, a different chain
#: shape entirely) -- see ``xcaf.py``'s own note on the same choice.
SHARED_COLOUR = (0.21, 0.43, 0.65)


def repeated_colour_document() -> Any:
    """Five differently-sized solids, each coloured with ``SHARED_COLOUR``."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colours = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    sizes = (
        (5.0, 6.0, 7.0),
        (8.0, 9.0, 10.0),
        (11.0, 12.0, 13.0),
        (14.0, 15.0, 16.0),
        (17.0, 18.0, 19.0),
    )
    for index, size in enumerate(sizes):
        box = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), *size).Shape()
        label = shapes.AddShape(box, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(f"part-{index}"))
        colours.SetColor(
            label,
            Quantity_Color(*SHARED_COLOUR, Quantity_TOC_RGB),
            XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        )
    return document
