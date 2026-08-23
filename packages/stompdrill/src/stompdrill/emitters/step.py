"""Cut the accepted holes into a supplied enclosure model and hand off to STEP.

Presentation only in the sense that matters: every hole, its position and its
diameter were decided before this module ran. Deciding where a hole goes is
drilling; turning a document into deterministic bytes is not -- that half now
lives in ``stompgeom.writer``, imported here rather than duplicated. The
kernel is imported inside the methods, so importing the emitter registry
stays free of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from stompgeom import kernel
from stompgeom.step import label_name
from stompgeom.writer import label_entry, render_step
from stompmodel.errors import EmitterError
from stompmodel.model import DrillData
from stompmodel.units import mm_from_nm

from ..cad import OcpCaseModel, step_keyword
from .base import register_emitter

__all__ = ["StepOptions", "StepEmitter", "cut_shape"]

#: Recorded in the header so a reader can tell which release cut the holes.
_VERSION = "0.1.0"

#: Named at the call site, never defaulted inside the shared writer.
_ORIGINATING_SYSTEM = f"stompdrill {_VERSION}"


@dataclass(frozen=True, slots=True)
class StepOptions:
    """The supplied case model to cut, and the title recorded in the header."""

    model: OcpCaseModel | None = None
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
            kernel.require_kernel()
        except kernel.KernelUnavailable as failure:
            raise EmitterError(str(failure)) from failure
        if not isinstance(self.options.model, OcpCaseModel):
            raise EmitterError(
                "the step emitter needs a kernel-backed case model from --case-model; "
                "a clearance-only model cannot be cut"
            )

    def emit(self, data: DrillData) -> bytes:
        """Cut every numbered hole, write STEP, then undo the cut in place.

        The supplied model is restored before returning, so a second
        ``emit`` on the same instance sees the pristine geometry again: this
        emitter only translates and serialises, it does not own state.
        """
        model = self.options.model
        assert model is not None, "__init__ already refused a missing model"
        document, undo, touched = cut_shape(model, data)
        try:
            return render_step(
                document,
                title=self.options.title or "stompdrill",
                timestamp=model.document_timestamp,
                originating_system=_ORIGINATING_SYSTEM,
                replaced_labels=touched,
            )
        finally:
            undo()


def cut_shape(
    model: OcpCaseModel, data: DrillData
) -> tuple[Any, Callable[[], None], frozenset[str]]:
    """Replace the drilled solid in the model's document with a cut copy.

    The solid is located by product-name keyword, walking the assembly tree
    the way ``select_solid`` does — not by ``IsSame`` against
    ``target_shape``, whose location may differ from the one carried by the
    document's own label. Returns the mutated document, an ``undo`` closure
    that restores every changed label to its pre-cut shape, and the entry
    strings of the labels it changed: ``render_step`` needs these, since a
    replaced label does not keep its colour in the written STEP.
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    document = model.document
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    tools = _drill_compound(model, data)
    if tools is None:
        return document, lambda: None, frozenset()

    keyword = step_keyword(model.face)
    originals: list[tuple[Any, Any]] = []
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    cut_any = any(
        _cut_component(tool, free.Value(index), keyword, tools, originals)
        for index in range(1, free.Length() + 1)
    )
    if not cut_any:
        raise EmitterError(f"no component named {keyword!r} was found to cut")

    # Each assembly's own compound is cached at read time; a component's new
    # shape does not retroactively rebuild it, so the writer would otherwise
    # serialise the stale, uncut aggregate.
    tool.UpdateAssemblies()

    def undo() -> None:
        for referred, original in originals:
            tool.SetShape(referred, original)
        tool.UpdateAssemblies()

    touched = frozenset(label_entry(referred) for referred, _ in originals)
    return document, undo, touched


def _cut_component(
    tool: Any, label: Any, keyword: str, tools: Any, originals: list[tuple[Any, Any]]
) -> bool:
    """Recurse into an assembly; cut the first ``keyword``-matching leaf."""
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    if XCAFDoc_ShapeTool.IsAssembly_s(label):
        children = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetComponents_s(label, children)
        return any(
            _cut_component(tool, children.Value(index), keyword, tools, originals)
            for index in range(1, children.Length() + 1)
        )
    if keyword not in label_name(label).upper():
        return False
    return _cut_leaf(tool, label, tools, originals)


def _cut_leaf(
    tool: Any, label: Any, tools: Any, originals: list[tuple[Any, Any]]
) -> bool:
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
    if placed.IsNull():  # pragma: no cover - a label matched by name always carries a shape
        return False
    cut = BRepAlgoAPI_Cut(placed, tools)
    cut.Build()
    if not cut.IsDone():
        raise EmitterError("the boolean cut failed on the supplied model")
    result = cut.Shape()

    referred = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
        original = XCAFDoc_ShapeTool.GetShape_s(referred)
        location = XCAFDoc_ShapeTool.GetLocation_s(label)
        tool.SetShape(referred, result.Located(location.Inverted()))
        originals.append((referred, original))
    else:
        # A bare top-level shape, not an assembly component: no placement to
        # undo before writing it back. Every Hammond fixture is an assembly,
        # so this is a fallback for a single-solid STEP file this codebase
        # has no fixture for, not a path these tests can reach.
        original = XCAFDoc_ShapeTool.GetShape_s(label)  # pragma: no cover
        tool.SetShape(label, result)  # pragma: no cover
        originals.append((label, original))  # pragma: no cover
    return True


def _drill_compound(model: OcpCaseModel, data: DrillData) -> Any | None:
    """One compound of bounded cylinders, sorted into drill-number order.

    ``data.numbered()`` pairs each hole with its ``Hole.index`` but yields
    them in tuple order, not index order, so the sort below is explicit:
    the compound's build order must be a function of the numbering alone,
    never of the tuple order a caller happened to hand in (ADR-0006).
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    holes = sorted(data.numbered(), key=lambda pair: pair[0])
    if not holes:
        return None

    # Bounded by the two levels the clearance check already found, plus a
    # little either side. An unbounded cylinder would punch the far wall too.
    overshoot = 1.0
    depth = abs(model.inner_position_mm - model.drilled_position_mm) + 2 * overshoot
    direction = tuple(-component for component in model.frame.basis.w)

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for _, hole in holes:
        start = _face_point(model, hole, overshoot)
        axis = gp_Ax2(gp_Pnt(*start), gp_Dir(*direction))
        radius = float(mm_from_nm(hole.diameter_nm)) / 2
        builder.Add(compound, BRepPrimAPI_MakeCylinder(axis, radius, depth).Shape())
    return compound


def _face_point(model: OcpCaseModel, hole: Any, overshoot: float) -> tuple[float, float, float]:
    """The cylinder's start, ``overshoot`` mm outside the drilled face."""
    frame = model.frame.basis
    x, y, z = frame.to_model(hole.x_nm, hole.y_nm)
    wx, wy, wz = frame.w
    return (
        float(x) + overshoot * wx,
        float(y) + overshoot * wy,
        float(z) + overshoot * wz,
    )
