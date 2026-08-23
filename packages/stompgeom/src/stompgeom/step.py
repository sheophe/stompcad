"""Read a STEP assembly into named solids in assembly coordinates.

The format layer, with nothing enclosure-specific in it. XCAF applies each
component's placement and the reader normalises every representation to
millimetres, so a sub-part modelled in inches arrives at the same scale as
one modelled in millimetres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stompmodel.errors import DocumentError

from .kernel import require_kernel

__all__ = [
    "StepSolid", "StepDocument", "read_step", "label_name", "bounding_box_mm",
    "source_timestamp",
]

#: Used when the source file declares no timestamp. Never a clock reading.
_EPOCH = "1970-01-01T00:00:00+00:00"

_TIMESTAMP_PATTERN = re.compile(r"time_stamp\s*\*?/?\s*'([^']*)'")

#: OCC's own synthesised indirection, written on a component occurrence that
#: carries no name of its own -- e.g. ``=>[0:1:1:34]``. Matched with
#: ``fullmatch`` so a genuine name that merely contains brackets, digits or
#: colons is never mistaken for it; an observed kernel behaviour with no
#: documented guarantee, so both directions are tested (see test_step.py).
_OCC_INDIRECTION = re.compile(r"=>\[[0-9:]+\]")


def source_timestamp(path: Path) -> str:
    """The source file's ``/* time_stamp */`` comment marker, or the epoch when absent.

    This matches ST-Developer's comment above ``FILE_NAME``, not the
    ``FILE_NAME`` field itself, so reading back a STEP file this workspace
    wrote drops provenance to the epoch even though the file carries a real
    stamp -- this workspace's own writer does not emit that comment.
    Determinism is unaffected: every write from one source still copies the
    same value, whatever it is.
    """
    head = path.read_bytes()[:4096].decode("latin-1")
    found = _TIMESTAMP_PATTERN.search(head)
    return found.group(1) if found else _EPOCH


@dataclass(frozen=True, slots=True)
class StepSolid:
    """One product's solid, placed in assembly coordinates and scaled to mm.

    ``name`` is empty exactly when nobody named this solid -- see
    :func:`label_name`, the one rule that decides that.
    """

    name: str
    shape: Any
    unit_mm: float


@dataclass(frozen=True)
class StepDocument:
    """Every solid a STEP file contains, the XCAF document, and its timestamp.

    ``timestamp`` is copied from the source ``FILE_NAME`` so an emitted file can
    reuse it instead of reading the clock. See ADR-0007 on determinism.
    """

    solids: tuple[StepSolid, ...]
    document: Any
    timestamp: str = _EPOCH

    def named(self, keyword: str) -> tuple[StepSolid, ...]:
        """Solids whose product name contains ``keyword``, case-insensitively."""
        wanted = keyword.upper()
        return tuple(s for s in self.solids if wanted in s.name.upper())


def bounding_box_mm(shape: Any) -> tuple[float, float, float, float, float, float]:
    """``(x0, y0, z0, x1, y1, z1)`` of ``shape`` in millimetres.

    ``AddOptimal_s`` rather than plain ``Add_s``: without a precomputed mesh,
    ``Add_s`` falls back to the convex hull of each surface's control poles,
    which for a filleted casting overshoots the true extent by an order of
    magnitude. ``AddOptimal_s`` measures the underlying geometry directly.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box)
    return box.Get()


def read_step(path: Path) -> StepDocument:
    """Read ``path`` as an XCAF assembly of named, placed, millimetre solids."""
    require_kernel()

    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    if not path.is_file():
        raise DocumentError(f"no model at {path}")

    # Ask OCC to normalise every representation to millimetres. Without this a
    # sub-assembly authored in inches arrives 25.4x too small.
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise DocumentError(f"{path} is not a readable STEP file")
    if not reader.Transfer(document):
        raise DocumentError(f"{path} contains no transferable shape")

    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    labels = TDF_LabelSequence()
    tool.GetFreeShapes(labels)

    solids: list[StepSolid] = []
    for index in range(1, labels.Length() + 1):
        _collect(labels.Value(index), solids)
    if not solids:
        raise DocumentError(f"{path} contains no solids")
    return StepDocument(tuple(solids), document, source_timestamp(path))


def _collect(label: Any, out: list[StepSolid]) -> None:
    """Walk one XCAF label, recording leaf solids in document order.

    A component label refers to a shape in the product's own local
    coordinates, plus a placement relative to its parent. ``GetShape_s`` on
    the *component* label — not the referred product label — resolves the
    reference and applies that placement itself, so every instance of a
    repeated part carries its own assembly position without a manual
    ``Moved`` here.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    if XCAFDoc_ShapeTool.IsAssembly_s(label):
        children = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(label, children)
        for index in range(1, children.Length() + 1):
            _collect(children.Value(index), out)
        return

    shape = XCAFDoc_ShapeTool.GetShape_s(label)
    if shape.IsNull():
        return
    out.append(StepSolid(name=label_name(label), shape=shape, unit_mm=1.0))


def label_name(label: Any) -> str:
    """The name XCAF recorded for ``label``, or "" when nobody named it.

    OCC synthesises an indirection placeholder such as ``=>[0:1:1:34]`` on a
    component occurrence that carries no name of its own; that placeholder
    names nothing, so it reads back as "" like a label with no name attribute
    at all. ``IsAttribute`` is checked before ``FindAttribute``: this
    binding's ``FindAttribute`` segfaults on a label with no
    ``TDataStd_Name`` attribute rather than returning ``False``, so presence
    is checked first and never inferred from the lookup's return value.
    """
    from OCP.TDataStd import TDataStd_Name

    if not label.IsAttribute(TDataStd_Name.GetID_s()):
        return ""
    holder = TDataStd_Name()
    label.FindAttribute(TDataStd_Name.GetID_s(), holder)
    name = str(holder.Get().ToExtString())
    return "" if _OCC_INDIRECTION.fullmatch(name) else name
