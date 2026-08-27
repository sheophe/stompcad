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
from typing import TYPE_CHECKING

from stompmodel.errors import DocumentError

from .kernel import require_kernel

if TYPE_CHECKING:
    # Real OCP names, for readability only: cadquery-ocp ships no py.typed
    # marker and this workspace's mypy configurations set
    # ignore_missing_imports for OCP.*, so these resolve to Any either way
    # and check nothing beyond what a bare Any already did. See ADR-0008.
    from OCP.TDF import TDF_Label
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopoDS import TopoDS_Shape

__all__ = [
    "StepSolid", "StepDocument", "StepLabel", "read_step", "leaf_labels",
    "bounding_box_mm", "assembly_spans", "source_timestamp",
]

#: Used when the source file declares no timestamp. Never a clock reading.
_EPOCH = "1970-01-01T00:00:00+00:00"

#: A STEP string literal: an unescaped closing quote ends it, and a doubled
#: quote (``''``) inside represents one literal quote character (ISO 10303-21
#: §6). The two alternatives cover disjoint cases at every position -- the
#: next character is a quote or it is not -- so this cannot backtrack: a run
#: of quotes with no closing call still matches in linear time.
_STEP_STRING = r"'(?:[^']|'')*'"

#: Zero or more ``/* field_name */`` comment annotations, the way a
#: conforming ST-Developer file labels a field immediately before its own
#: value -- never a second copy of the value carried without the field.
_COMMENT = r"(?:/\*.*?\*/\s*)*"

#: ``FILE_NAME``'s own second positional argument (ISO 10303-21 §6.4.3): the
#: field the writer actually sets. The name field's comment and value are
#: matched but not captured; only the time-stamp field's value is.
_FILE_NAME_PATTERN = re.compile(
    r"FILE_NAME\s*\(\s*" + _COMMENT + _STEP_STRING + r"\s*,\s*" + _COMMENT
    + r"(" + _STEP_STRING + r")",
    re.DOTALL,
)

#: OCC's own synthesised indirection, written on a component occurrence that
#: carries no name of its own -- e.g. ``=>[0:1:1:34]``. Matched with
#: ``fullmatch`` so a genuine name that merely contains brackets, digits or
#: colons is never mistaken for it; an observed kernel behaviour with no
#: documented guarantee, so both directions are tested (see test_step.py).
_OCC_INDIRECTION = re.compile(r"=>\[[0-9:]+\]")


def source_timestamp(path: Path) -> str:
    """``FILE_NAME``'s own time-stamp field, or the epoch when absent or empty.

    This is the field the writer actually sets (see :mod:`stompgeom.writer`),
    read positionally rather than through ST-Developer's ``/* time_stamp */``
    comment convention -- a second producer's labelling for the same field,
    which this workspace's own writer never emits. A declared but empty field
    degrades to the epoch too, rather than reporting an empty string.
    Determinism is unaffected: every write from one source still copies the
    same value, whatever it is.
    """
    head = path.read_bytes()[:4096].decode("latin-1")
    found = _FILE_NAME_PATTERN.search(head)
    if not found:
        return _EPOCH
    value = found.group(1)[1:-1].replace("''", "'")
    return value if value else _EPOCH


@dataclass(frozen=True, slots=True)
class StepLabel:
    """A label together with the ``TDocStd_Document`` it was drawn from.

    ``document`` keeps ``label`` valid -- that object specifically, since
    neither the document's ``ShapeTool`` nor its root label does (ADR-0008).
    ``label`` routinely holds a *referred* label, not a leaf. ``name`` and
    ``entry`` are computed on access, never stored: they compare unequal by
    ``==`` (kernel identity), why ``replaced_labels`` is entries. ``label``
    stays public and raw: the cutting path needs four XCAF verbs this
    package does not wrap.
    """

    document: TDocStd_Document
    label: TDF_Label

    @property
    def name(self) -> str:
        """See :func:`_label_name`."""
        return _label_name(self.label)

    @property
    def entry(self) -> str:
        """See :func:`_label_entry`."""
        return _label_entry(self.label)


@dataclass(frozen=True, slots=True)
class StepSolid:
    """One product's solid, placed in assembly coordinates and scaled to mm.

    ``name`` is empty exactly when nobody named this solid -- see
    :func:`_label_name`, the one rule that decides that, reached through the
    :class:`StepLabel` :func:`leaf_labels` hands back.
    """

    name: str
    shape: TopoDS_Shape


@dataclass(frozen=True)
class StepDocument:
    """Every solid a STEP file contains, the XCAF document, and its timestamp.

    ``timestamp`` is copied from the source ``FILE_NAME`` so an emitted file can
    reuse it instead of reading the clock. See ADR-0007 on determinism.
    """

    solids: tuple[StepSolid, ...]
    document: TDocStd_Document
    timestamp: str = _EPOCH

    def named(self, keyword: str) -> tuple[StepSolid, ...]:
        """Solids whose product name contains ``keyword``, case-insensitively."""
        wanted = keyword.upper()
        return tuple(s for s in self.solids if wanted in s.name.upper())


def bounding_box_mm(shape: TopoDS_Shape) -> tuple[float, float, float, float, float, float]:
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


def assembly_spans(document: StepDocument) -> tuple[float, float, float]:
    """The bounding-box span of every solid together, per axis, in millimetres."""
    boxes = [bounding_box_mm(solid.shape) for solid in document.solids]
    lows = [min(b[axis] for b in boxes) for axis in range(3)]
    highs = [max(b[axis + 3] for b in boxes) for axis in range(3)]
    return (highs[0] - lows[0], highs[1] - lows[1], highs[2] - lows[2])


def read_step(path: Path) -> StepDocument:
    """Read ``path`` as an XCAF assembly of named, placed, millimetre solids."""
    require_kernel()

    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

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

    solids: list[StepSolid] = []
    for entry in leaf_labels(document):
        shape = XCAFDoc_ShapeTool.GetShape_s(entry.label)
        if shape.IsNull():
            continue
        solids.append(StepSolid(name=entry.name, shape=shape))
    if not solids:
        raise DocumentError(f"{path} contains no solids")
    return StepDocument(tuple(solids), document, source_timestamp(path))


def leaf_labels(document: TDocStd_Document) -> tuple[StepLabel, ...]:
    """Every leaf (non-assembly) label under ``document``'s free shapes.

    The one XCAF descent this workspace performs, ``GetFreeShapes`` prologue
    included, in document order. Each leaf comes back wrapped in a
    :class:`StepLabel` holding ``document`` itself, with no filtering -- a
    null-shaped leaf comes back too, since what a leaf is *for* is a
    call-site decision. Eager, not lazy: a suspended descent holding a
    kernel handle over a tree a caller then mutates is a hazard this package
    has already paid for once. Raises nothing; an empty document is ``()``.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)

    leaves: list[TDF_Label] = []
    for index in range(1, free.Length() + 1):
        _walk_leaves(free.Value(index), leaves)
    return tuple(StepLabel(document, label) for label in leaves)


def _walk_leaves(label: TDF_Label, out: list[TDF_Label]) -> None:
    """Append ``label`` if it is a leaf, else recurse into its components.

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
            _walk_leaves(children.Value(index), out)
        return
    out.append(label)


def _label_name(label: TDF_Label) -> str:
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


def _label_entry(label: TDF_Label) -> str:
    """A label's document-unique tag path, stable across shape mutation.

    Unlike a shape's own identity, a label's entry string survives
    ``SetShape``, and unlike the label itself survives being compared with
    one drawn from a separate kernel call for the same node -- label
    equality is kernel object identity, not this. A general fact about the
    label tree, not the writer's alone, which is why it lives here rather
    than in :mod:`stompgeom.writer`, its original, one-time home.
    """
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool

    text = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, text)
    return text.ToCString()
