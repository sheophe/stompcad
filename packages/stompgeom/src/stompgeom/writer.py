"""Three OCC process-global effects — a translator product-name suffix, the
assembly usage occurrence ids, and which numeric slot each colour is written
into — are not controllable through any exposed API, so ``write_step``
normalises the written bytes afterwards instead.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import re
from collections.abc import Iterator
from typing import Any

from stompmodel.errors import EmitterError

from .kernel import require_kernel

__all__ = ["write_step", "label_entry", "label_name"]

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


def label_name(label: Any) -> str:
    """The product name recorded on ``label``, or empty when unnamed."""
    from OCP.TDataStd import TDataStd_Name

    holder = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), holder):
        return str(holder.Get().ToExtString())
    return ""  # pragma: no cover - every label this kernel returns to us is named;
    # a hand-built label with no attributes at all crashes this OCP binding's own
    # FindAttribute before reaching this line, so no test can safely construct one


def label_entry(label: Any) -> str:
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
def _count_colour_assignments(document: Any, replaced_labels: frozenset[str]) -> int:
    """Distinct shapes coloured in ``document``, excluding a replaced solid.

    A replaced solid keeps its ``XCAFDoc_ColorTool`` assignment (``SetShape``
    does not clear it) but not its written colour, so counting
    ``replaced_labels`` labels in would overcount against what the writer
    actually produces. Excluding them is what makes this agree with the real
    output rather than approximate it. A component referring to one label
    twice (four screw instances, one product) counts once, matching one
    written chain.
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
        entry = label_entry(target)
        if entry in replaced_labels:
            continue
        if color_tool.IsSet(target, XCAFDoc_ColorType.XCAFDoc_ColorSurf):
            coloured.add(entry)
    return len(coloured)


@contextlib.contextmanager
def _silence_stdout() -> Iterator[None]:
    """Suppress OCC's C++ progress banners, invisible to Python-level redirects.

    OCC writes its transfer statistics through the C runtime, bypassing
    ``sys.stdout`` entirely, so only redirecting the OS file descriptor
    itself keeps a clean report from a caller's report.
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
            "STEP; _COLOUR_CHAIN in stompgeom.writer likely needs "
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


def write_step(
    document: Any,
    path: Any,
    *,
    title: str,
    timestamp: str,
    originating_system: str,
    replaced_labels: frozenset[str] = frozenset(),
) -> None:
    """Write the XCAF document with a header that carries no clock reading."""
    require_kernel()

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
    expected = _count_colour_assignments(document, replaced_labels)
    with _silence_stdout():
        writer.Transfer(document)

        header = APIHeaderSection_MakeHeader(session.Model())
        header.SetName(TCollection_HAsciiString(title))
        header.SetTimeStamp(TCollection_HAsciiString(timestamp))
        header.SetAuthorValue(1, TCollection_HAsciiString(""))
        header.SetOriginatingSystem(TCollection_HAsciiString(originating_system))
        writer.Write(str(path))
    payload = _normalise(path.read_bytes())
    path.write_bytes(_reslot_colours(payload, expected))
