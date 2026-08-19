"""Cut the accepted holes into a supplied enclosure model and write STEP.

Presentation only in the sense that matters: every hole, its position and its
diameter were decided before this module ran. The kernel is imported inside
the methods, so importing the emitter registry stays free of it. Three OCC
process-global effects — a translator product-name suffix, the assembly
usage occurrence ids, and which numeric slot each colour is written into —
are not controllable through any exposed API, so ``_write`` normalises the
written bytes afterwards instead.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import re
from collections.abc import Callable, Iterator
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

#: The translator's auto-generated wrapper product. Set at write time, and the
#: volatile counter it appends is erased afterwards. All three uses -- the
#: setter, the pattern, the replacement -- read it here rather than spelling it.
_PRODUCT_NAME = "stompcad"

#: One physical-file entity, wrapped or not, that may carry a volatile
#: counter (see the module docstring). ``DOTALL`` so a line-wrapped entity
#: matches as a whole; entity bodies here never contain a literal ``);``.
_VOLATILE_ENTITY = re.compile(
    rb"(#\d+ = (?:NEXT_ASSEMBLY_USAGE_OCCURRENCE|PRODUCT)\(.*?\);)", re.DOTALL
)
#: The writer's own "<write.step.product.name> <counter>.1" wrapper product;
#: never a real part name, which always keeps the name it was read with.
#: Matches by *content*, not by entity id, because the wrapper's own id is
#: itself one of the unstable counters this module exists to erase: a real
#: source part literally named "stompcad 1.2" would be silently rewritten by
#: this pattern too. No fixture exercises that collision and there is no
#: id-based alternative available through this kernel's bindings.
#: Built from ``_PRODUCT_NAME``, never spelled out: written twice, a rename
#: would silence this pattern and leave a volatile id in a plausible artefact.
_VOLATILE_VERSION = re.compile(rb"'" + _PRODUCT_NAME.encode() + rb" \d+\.\d+'")
_VOLATILE_NAUO_ID = re.compile(rb"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\(')(\d+)(')")

#: One colour presentation, the fixed nine-entity chain STEPCAFControl_Writer
#: emits per coloured shape: a styled-item wrapper down to the RGB literal.
#: Each entity but the first refers only to the next; group 1 is the chain's
#: own starting id, group 2 the ``STYLED_ITEM``'s id, group 3 the id of the
#: *shape* it colours (an external, stable reference — never renumbered
#: here), group 4 the closing ``COLOUR_RGB``'s own id, group 5 its literal.
_COLOUR_CHAIN = re.compile(
    rb"#(\d+) = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION\(.*?\);\s*"
    rb"#(\d+) = STYLED_ITEM\('color',\(#\d+\),#(\d+)\);\s*"
    rb"#\d+ = PRESENTATION_STYLE_ASSIGNMENT\(.*?\);\s*"
    rb"#\d+ = SURFACE_STYLE_USAGE\(.*?\);\s*"
    rb"#\d+ = SURFACE_SIDE_STYLE\(.*?\);\s*"
    rb"#\d+ = SURFACE_STYLE_FILL_AREA\(.*?\);\s*"
    rb"#\d+ = FILL_AREA_STYLE\(.*?\);\s*"
    rb"#\d+ = FILL_AREA_STYLE_COLOUR\(.*?\);\s*"
    rb"#(\d+) = COLOUR_RGB\('',([^)]*)\);",
    re.DOTALL,
)


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
        """Cut every numbered hole, write STEP, then undo the cut in place.

        The supplied model is restored before returning, so a second
        ``emit`` on the same instance sees the pristine geometry again: this
        emitter only translates and serialises, it does not own state.
        """
        import tempfile
        from pathlib import Path

        model = self.options.model
        assert model is not None, "__init__ already refused a missing model"
        document, undo, touched = cut_shape(model, data)
        try:
            with tempfile.TemporaryDirectory() as scratch:
                target = Path(scratch) / "out.stp"
                _write(document, target, self.options.title, model.document_timestamp, touched)
                return target.read_bytes()
        finally:
            undo()


def cut_shape(model: Any, data: DrillData) -> tuple[Any, Callable[[], None], frozenset[str]]:
    """Replace the drilled solid in the model's document with a cut copy.

    The solid is located by product-name keyword, walking the assembly tree
    the way ``select_solid`` does — not by ``IsSame`` against
    ``target_shape``, whose location may differ from the one carried by the
    document's own label. Returns the mutated document, an ``undo`` closure
    that restores every changed label to its pre-cut shape, and the entry
    strings of the labels it changed (``_write`` needs these: a label whose
    shape is replaced here does not keep its colour in the written STEP).
    """
    from OCP.TDF import TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    document = model.document
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    tools = _drill_compound(model, data)
    if tools is None:
        return document, lambda: None, frozenset()

    keyword = "BOX" if model.face == "box" else "LID"
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

    touched = frozenset(_label_entry(referred) for referred, _ in originals)
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
    if keyword not in _label_name(label).upper():
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


def _label_name(label: Any) -> str:
    """The product name recorded on ``label``, or empty when unnamed."""
    from OCP.TDataStd import TDataStd_Name

    holder = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), holder):
        return str(holder.Get().ToExtString())
    return ""  # pragma: no cover - every label this kernel returns to us is named;
    # a hand-built label with no attributes at all crashes this OCP binding's own
    # FindAttribute before reaching this line, so no test can safely construct one


def _label_entry(label: Any) -> str:
    """A label's document-unique tag path, stable across shape mutation.

    Unlike a shape's own identity, a label's entry string survives
    ``SetShape``: it is what lets ``_count_colour_assignments`` recognise
    "the same label" before and after ``cut_shape`` replaces its geometry.
    """
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool

    text = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, text)
    return text.ToCString()


# Re-establishing the cut solid's own colour was tried and abandoned: neither
# re-linking the referred label to its original XCAFDoc_ColorTool colour
# label nor re-setting the RGB value directly, at solid, component, or
# per-face granularity, before or after UpdateAssemblies, changes the
# written STYLED_ITEM count. A SetShape to an unchanged shape (no real cut)
# keeps its colour, so the mechanism is sound; STEPCAFControl_Writer simply
# does not serialise colour for a shape it had to replace. No further
# in-kernel route is exposed through this binding to force it.
def _count_colour_assignments(document: Any, touched: frozenset[str]) -> int:
    """Distinct shapes coloured in ``document``, excluding cut solids.

    A cut solid keeps its ``XCAFDoc_ColorTool`` assignment (``SetShape``
    does not clear it) but not its written colour, so counting ``touched``
    labels in would overcount against what the writer actually produces.
    Excluding them is what makes this agree with the real output rather
    than approximate it. A component referring to one label twice (four
    screw instances, one product) counts once, matching one written chain.
    """
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    def leaves(label: Any, out: list[Any]) -> None:
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            children = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, children)
            for index in range(1, children.Length() + 1):
                leaves(children.Value(index), out)
        else:
            out.append(label)

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    components: list[Any] = []
    for index in range(1, free.Length() + 1):
        leaves(free.Value(index), components)

    coloured: set[str] = set()
    for component in components:
        referred = TDF_Label()
        target = referred if XCAFDoc_ShapeTool.GetReferredShape_s(component, referred) \
            else component
        entry = _label_entry(target)
        if entry in touched:
            continue
        if color_tool.IsSet(target, XCAFDoc_ColorType.XCAFDoc_ColorSurf):
            coloured.add(entry)
    return len(coloured)


def _drill_compound(model: Any, data: DrillData) -> Any | None:
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


@contextlib.contextmanager
def _silence_stdout() -> Iterator[None]:
    """Suppress OCC's C++ progress banners, invisible to Python-level redirects.

    OCC writes its transfer statistics through the C runtime, bypassing
    ``sys.stdout`` entirely, so only redirecting the OS file descriptor
    itself keeps a clean report from an ``stompdrill`` invocation.
    """
    saved = os.dup(1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        yield
    finally:
        os.dup2(saved, 1)
        os.close(devnull)
        os.close(saved)


# Kernel-side resets were tried first and abandoned (Task 12 investigation):
# ``STEPControl_Controller.Init_s()`` and a fresh ``XSControl_WorkSession``
# per call both leave the counters below unaffected, and no
# ``Interface_Static`` key touches either one — ``write.step.product.name``
# only substitutes the wrapper product's *prefix*, never the "<counter>.1"
# suffix appended after it, and the NAUO counter has no exposed key at all.
# Post-processing the written bytes is not a workaround pending a better
# fix; it is the only route this kernel's bindings leave open.
def _normalise(payload: bytes) -> bytes:
    """Erase the two process-global OCC counters from one written file.

    Neither the translator's per-write product-name suffix nor the assembly
    usage occurrence ids are resettable through any API this kernel exposes.
    Rewriting bytes after the fact is honest and fully deterministic; each
    affected entity is first rejoined onto one line, since the writer's own
    line-wrap column depends on how many digits the volatile counter had
    that call, which would otherwise leak process history back in.
    """
    payload = _VOLATILE_ENTITY.sub(lambda m: re.sub(rb"\n[ \t]*", b"", m.group(1)), payload)
    payload = _VOLATILE_VERSION.sub(b"'" + _PRODUCT_NAME.encode() + b"'", payload)
    counter = itertools.count(1)

    def renumber(match: re.Match[bytes]) -> bytes:
        return match.group(1) + str(next(counter)).encode("ascii") + match.group(3)

    return _VOLATILE_NAUO_ID.sub(renumber, payload)


def _reslot_colours(payload: bytes, expected: int) -> bytes:
    """Re-seat each colour chain into the numeric slot content order picks.

    ``STEPCAFControl_Writer::WriteColors`` hashes on the ``TShape`` pointer
    to decide *which* chain goes in *which* fixed nine-id slot at the file's
    tail — the pointer, not the file, so two writes of the same document
    permute the slots. The chains themselves, and the ids they occupy, are
    unaffected: this sorts the chains by the shape id they colour (already
    a stable, external reference) and writes each into the slot the file's
    own encounter order assigned, renumbering only that chain's own nine ids.
    """
    chains = list(_COLOUR_CHAIN.finditer(payload))
    # Checked unconditionally, before the "nothing to reorder" shortcut
    # below: a silent count mismatch — not just zero matches — is exactly
    # what a future OpenCASCADE upgrade reshaping this chain would produce,
    # and reordering nothing looks identical to reordering correctly unless
    # the count is verified against ``expected``, the source document's own.
    if len(chains) != expected:
        raise EmitterError(
            f"the source document assigns {expected} colour(s), but "
            f"{len(chains)} STYLED_ITEM chain(s) were found in the written "
            "STEP; _COLOUR_CHAIN in stompdrill.emitters.step likely needs "
            "updating for this OpenCASCADE version's colour-chain shape"
        )
    if len(chains) < 2:
        return payload

    # ``chains`` is already in slot order (ascending file position == ascending
    # id); pairing it against the content-sorted list below re-seats chain i's
    # *content* into slot i's *ids*, whatever order the writer produced them in.
    ordered = sorted(chains, key=lambda match: (int(match.group(3)), match.group(5)))

    pieces: list[bytes] = []
    cursor = 0
    for slot, content in zip(chains, ordered):
        pieces.append(payload[cursor:slot.start()])
        cursor = slot.end()
        own_start = int(content.group(1))
        delta = int(slot.group(1)) - own_start
        local = set(range(own_start, own_start + 9))

        def shift(match: re.Match[bytes], delta: int = delta, local: set[int] = local) -> bytes:
            old = int(match.group(1))
            return b"#" + str(old + delta if old in local else old).encode("ascii")

        pieces.append(re.sub(rb"#(\d+)", shift, content.group(0)))
    pieces.append(payload[cursor:])
    return b"".join(pieces)


def _write(
    document: Any, path: Any, title: str, timestamp: str, touched: frozenset[str]
) -> None:
    """Write the XCAF document with a header that carries no clock reading."""
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.TCollection import TCollection_HAsciiString
    from OCP.XSControl import XSControl_WorkSession

    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    # Load-bearing for determinism, not just cosmetic: fixes the prefix the
    # translator's auto-generated wrapper product uses, which ``_normalise``
    # then strips the volatile "<counter>.1" suffix from.
    Interface_Static.SetCVal_s("write.step.product.name", _PRODUCT_NAME)
    session = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(session, False)
    expected = _count_colour_assignments(document, touched)
    with _silence_stdout():
        writer.Transfer(document)

        header = APIHeaderSection_MakeHeader(session.Model())
        header.SetName(TCollection_HAsciiString(title or "stompdrill"))
        header.SetTimeStamp(TCollection_HAsciiString(timestamp))
        header.SetAuthorValue(1, TCollection_HAsciiString(""))
        header.SetOriginatingSystem(TCollection_HAsciiString(f"stompdrill {_VERSION}"))
        writer.Write(str(path))
    payload = _normalise(path.read_bytes())
    path.write_bytes(_reslot_colours(payload, expected))
