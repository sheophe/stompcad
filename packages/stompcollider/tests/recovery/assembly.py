"""Read an assembly model back out of its STEP, through OCP directly.

Not through ``stompgeom``: that package's writer produced these bytes, and a
reader drawn from it could invert its own transform and prove nothing. OCP is
the independent parser here, the role ``pdfminer.six`` plays for
``stompdrill``'s drawing recovery. One thing *is* shared with the writer --
``stompmodel``'s ``nm_from_mm``, the canonical millimetre-to-nanometre rule --
so a scale wrong there would cancel across the round trip. That is sanctioned,
and named because an unstated shared constant weakens the independence claim.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from stompmodel.units import Nanometre, nm_from_mm

from . import RecoveredAssembly, RecoveredSolid

__all__ = ["read_assembly"]


def read_assembly(payload: bytes) -> RecoveredAssembly:
    """Every product ``payload`` names, and the box each occupies, in nanometres.

    The bytes are staged to a file because a STEP reader takes a path. Unit
    normalisation is asked for explicitly: a file's own declared unit must
    not decide the scale a measurement comes back at.
    """
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(document)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "assembly.stp"
        path.write_bytes(payload)
        if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise ValueError("not a readable STEP file")
        if not reader.Transfer(document):
            raise ValueError("the STEP file contains no transferable shape")
    return RecoveredAssembly(solids=tuple(_solids(document)))


def _solids(document: Any) -> list[RecoveredSolid]:
    """The document's free shapes, each named and measured.

    The emitter writes each solid as its own free shape, so these *are* the
    products it wrote and this reader never descends into one. A null shape
    is refused rather than skipped: a product the file names but holds no
    geometry for is exactly the failure a comparison over names alone would
    pass.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    free = TDF_LabelSequence()
    XCAFDoc_DocumentTool.ShapeTool_s(document.Main()).GetFreeShapes(free)

    found: list[RecoveredSolid] = []
    for index in range(1, free.Length() + 1):
        label = free.Value(index)
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        name = _name(label)
        if shape.IsNull():
            raise ValueError(f"{name!r} names a product with no shape")
        found.append(RecoveredSolid(name=name, box_nm=_box_nm(shape)))
    return found


def _name(label: Any) -> str:
    """What the file calls this product, or "" when it names it nothing.

    ``IsAttribute`` is asked before ``FindAttribute``: this binding's
    ``FindAttribute`` faults on a label carrying no name rather than
    answering ``False``.
    """
    from OCP.TDataStd import TDataStd_Name

    if not label.IsAttribute(TDataStd_Name.GetID_s()):
        return ""
    holder = TDataStd_Name()
    label.FindAttribute(TDataStd_Name.GetID_s(), holder)
    return str(holder.Get().ToExtString())


def _box_nm(
    shape: Any,
) -> tuple[Nanometre, Nanometre, Nanometre, Nanometre, Nanometre, Nanometre]:
    """``(x0, y0, z0, x1, y1, z1)`` of ``shape``, in whole nanometres.

    ``AddOptimal_s`` measures the geometry rather than the control poles of
    its surfaces, which for a curved face overshoots the true extent
    substantially -- a hull, not a box.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box)
    measured = tuple(nm_from_mm(value) for value in box.Get())
    return (
        measured[0], measured[1], measured[2], measured[3], measured[4], measured[5],
    )
