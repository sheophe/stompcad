"""Cut the accepted holes into a supplied enclosure model and write STEP.

Presentation only in the sense that matters: every hole, its position and its
diameter were decided before this module ran. The kernel is imported inside
the methods, so importing the emitter registry stays free of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..cad.base import KernelUnavailable
from ..errors import EmitterError
from ..model import DrillData
from ..units import mm_from_nm
from .base import register_emitter

__all__ = ["StepOptions", "StepEmitter", "cut_shape"]

#: Recorded in the header so a reader can tell which release cut the holes.
_VERSION = "0.1.0"


def require_kernel() -> None:
    """Indirection so a test can simulate an absent kernel."""
    from ..cad.step import require_kernel as check

    check()


@dataclass(frozen=True, slots=True)
class StepOptions:
    """The supplied case model to cut, and the title recorded in the header."""

    model: Any | None = None
    title: str = ""


@register_emitter
class StepEmitter:
    """Emit the supplied enclosure with this panel's holes drilled through it."""

    name: ClassVar[str] = "step"
    media_type: ClassVar[str] = "model/step"
    extension: ClassVar[str] = ".stp"

    def __init__(self, options: StepOptions | None = None) -> None:
        self.options = options if options is not None else StepOptions()
        if self.options.model is None:
            raise EmitterError("the step emitter needs a case model; pass --case-model PATH")
        try:
            require_kernel()
        except KernelUnavailable as failure:
            raise EmitterError(str(failure)) from failure

    def emit(self, data: DrillData) -> bytes:
        """Cut every numbered hole and serialise the whole assembly."""
        import tempfile
        from pathlib import Path

        model = self.options.model
        assert model is not None, "__init__ already refused a missing model"
        document = cut_shape(model, data)
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "out.stp"
            _write(document, target, self.options.title, model.document_timestamp)
            return target.read_bytes()


def cut_shape(model: Any, data: DrillData) -> Any:
    """Replace the drilled solid in the model's document with a cut copy.

    The solid is located by product-name keyword, walking the assembly tree
    the way ``select_solid`` does — not by ``IsSame`` against
    ``target_shape``, whose location may differ from the one carried by the
    document's own label.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    document = model.document
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    tools = _drill_compound(model, data)
    if tools is None:
        return document

    keyword = "BOX" if model.face == "box" else "LID"
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    cut_any = any(
        _cut_component(tool, free.Value(index), keyword, tools)
        for index in range(1, free.Length() + 1)
    )
    if not cut_any:
        raise EmitterError(f"no component named {keyword!r} was found to cut")

    # Each assembly's own compound is cached at read time; a component's new
    # shape does not retroactively rebuild it, so the writer would otherwise
    # serialise the stale, uncut aggregate.
    tool.UpdateAssemblies()
    return document


def _cut_component(tool: Any, label: Any, keyword: str, tools: Any) -> bool:
    """Recurse into an assembly; cut the first ``keyword``-matching leaf."""
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    if XCAFDoc_ShapeTool.IsAssembly_s(label):
        children = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(label, children)
        return any(
            _cut_component(tool, children.Value(index), keyword, tools)
            for index in range(1, children.Length() + 1)
        )
    if keyword not in _label_name(label).upper():
        return False
    return _cut_leaf(tool, label, tools)


def _cut_leaf(tool: Any, label: Any, tools: Any) -> bool:
    """Cut one placed leaf shape and write the result back through its label.

    A component label is a reference: its own ``GetShape_s`` bakes in the
    assembly placement, but ``SetShape`` only accepts the *referred* label's
    own, unplaced geometry. The cut runs in the placed (world) frame, where
    ``tools`` was built, then the component's own location is undone before
    the result is written back — otherwise the placement would apply twice.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.TDF import TDF_Label
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    placed = XCAFDoc_ShapeTool.GetShape_s(label)
    if placed.IsNull():
        return False
    cut = BRepAlgoAPI_Cut(placed, tools)
    cut.Build()
    if not cut.IsDone():
        raise EmitterError("the boolean cut failed on the supplied model")
    result = cut.Shape()

    referred = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
        location = XCAFDoc_ShapeTool.GetLocation_s(label)
        tool.SetShape(referred, result.Located(location.Inverted()))
    else:
        tool.SetShape(label, result)
    return True


def _label_name(label: Any) -> str:
    """The product name recorded on ``label``, or empty when unnamed."""
    from OCP.TDataStd import TDataStd_Name

    holder = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), holder):
        return str(holder.Get().ToExtString())
    return ""


def _drill_compound(model: Any, data: DrillData) -> Any | None:
    """One compound of bounded cylinders, in canonical hole order."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    holes = data.numbered()
    if not holes:
        return None

    # Bounded by the two levels the clearance check already found, plus a
    # little either side. An unbounded cylinder would punch the far wall too.
    overshoot = 1.0
    depth = abs(model.inner_position_mm - model.drilled_position_mm) + 2 * overshoot
    direction = tuple(-component for component in model.frame.w)

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for _, hole in holes:
        start = _face_point(model, hole, overshoot)
        axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*direction))
        radius = float(mm_from_nm(hole.diameter_nm)) / 2
        builder.Add(compound, BRepPrimAPI_MakeCylinder(axis, radius, depth).Shape())
    return compound


def _face_point(model: Any, hole: Any, overshoot: float) -> tuple[float, float, float]:
    """The cylinder's start, ``overshoot`` mm outside the drilled face."""
    frame = model.frame
    x, y = float(mm_from_nm(hole.x_nm)), float(mm_from_nm(hole.y_nm))
    origin = tuple(float(mm_from_nm(value)) for value in frame.origin_nm)
    return tuple(
        origin[i] + x * frame.u[i] + y * frame.v[i] + overshoot * frame.w[i]
        for i in range(3)
    )


def _write(document: Any, path: Any, title: str, timestamp: str) -> None:
    """Write the XCAF document with a header that carries no clock reading."""
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.TCollection import TCollection_HAsciiString
    from OCP.XSControl import XSControl_WorkSession

    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    session = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(session, False)
    writer.Transfer(document)

    header = APIHeaderSection_MakeHeader(session.Model())
    header.SetName(TCollection_HAsciiString(title or "aidrill"))
    header.SetTimeStamp(TCollection_HAsciiString(timestamp))
    header.SetAuthorValue(1, TCollection_HAsciiString(""))
    header.SetOriginatingSystem(TCollection_HAsciiString(f"aidrill {_VERSION}"))
    writer.Write(str(path))
