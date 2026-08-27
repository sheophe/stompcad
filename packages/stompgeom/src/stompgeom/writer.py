"""Three OCC process-global effects — a translator product-name suffix, the
assembly usage occurrence ids, and which numeric slot each colour is written
into — are not controllable through any exposed API, so ``render_step``
normalises the written bytes afterwards instead.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from stompmodel.errors import EmitterError

from .kernel import require_kernel
from .step import StepLabel

if TYPE_CHECKING:
    # See stompgeom.step's own TYPE_CHECKING block: real OCP names for
    # readability only, resolved to Any either way by this workspace's
    # mypy configuration. See ADR-0008.
    from OCP.TDocStd import TDocStd_Document

__all__ = ["render_step"]

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

#: One colour presentation, the chain STEPCAFControl_Writer emits per
#: coloured shape: an item down to its colour. A whole-solid colour (a
#: Hammond enclosure's box or lid) gets its own
#: ``MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION`` wrapper and
#: its own inline ``COLOUR_RGB``, one item per wrapper -- group 1 is that
#: wrapper's own id. A sub-shape colour (a board's per-face copper or
#: silkscreen) shares one wrapper across many items, so the wrapper is only
#: ever present on the *first* item a given wrapper's list names; every
#: later sibling item matches with group 1 absent. ``OVER_RIDING_STYLED_ITEM``
#: additionally names the item it overrides (the trailing ``,#\d+``, dropped
#: rather than captured -- it is never one of this chain's own ids). Group 2
#: is the item's own id, group 3 the id of the *shape* it colours (an
#: external, stable reference — never renumbered here), group 4 the id
#: ``FILL_AREA_STYLE_COLOUR`` names -- always present, but only *defined*
#: within this chain, with the literal captured as group 5, when the colour
#: is this chain's own rather than one written earlier and reused. The
#: trailing clause backreferences group 4 (``\4``) rather than capturing a
#: fresh id, which is what proves a following ``COLOUR_RGB`` defines *this*
#: reference rather than being an unrelated entity that happens to follow a
#: reused-colour chain with no terminal entity of its own. Every entity body
#: here is bounded with ``[^;]*?`` rather than ``.*?``: an entity never
#: contains a literal ``;`` (see ``_VOLATILE_ENTITY``), so the optional
#: wrapper cannot expand past an unrelated intervening entity to reach a
#: styled item that is not really its own.
_COLOUR_CHAIN = re.compile(
    rb"(?:#(\d+) = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION\([^;]*?\);\s*)?"
    rb"#(\d+) = (?:STYLED_ITEM|OVER_RIDING_STYLED_ITEM)\('[^']*',\(#\d+\),#(\d+)(?:,\s*#\d+)?\);\s*"
    rb"#\d+ = PRESENTATION_STYLE_ASSIGNMENT\([^;]*?\);\s*"
    rb"#\d+ = SURFACE_STYLE_USAGE\([^;]*?\);\s*"
    rb"#\d+ = SURFACE_SIDE_STYLE\([^;]*?\);\s*"
    rb"#\d+ = SURFACE_STYLE_FILL_AREA\([^;]*?\);\s*"
    rb"#\d+ = FILL_AREA_STYLE\([^;]*?\);\s*"
    rb"#\d+ = FILL_AREA_STYLE_COLOUR\('',#(\d+)\);"
    rb"(?:\s*#\4 = COLOUR_RGB\('',([^)]*)\);)?",
    re.DOTALL,
)


# Re-establishing the cut solid's own colour was tried and abandoned: neither
# re-linking the referred label to its original XCAFDoc_ColorTool colour
# label nor re-setting the RGB value directly, at solid, component, or
# per-face granularity, before or after UpdateAssemblies, changes the
# written STYLED_ITEM count. A SetShape to an unchanged shape (no real cut)
# keeps its colour, so the mechanism is sound; STEPCAFControl_Writer simply
# does not serialise colour for a shape it had to replace. No further
# in-kernel route is exposed through this binding to force it.
def _count_colour_assignments(document: TDocStd_Document, replaced_labels: frozenset[str]) -> int:
    """Distinct shapes coloured in ``document``, excluding a replaced solid.

    A board colours individual faces on *sub-shape* labels a leaf-only
    census misses, so this walks components and sub-shapes together (no
    ``ColorTool.GetShapesOfColor`` here, and a face colour is observed
    beneath an intermediate label, not only a leaf). A replaced solid is
    excluded, not counted (``SetShape`` keeps the assignment but not the
    written colour); a label reached twice counts once, resolved to its
    referred label when one exists.
    """
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    kinds = (
        XCAFDoc_ColorType.XCAFDoc_ColorSurf,
        XCAFDoc_ColorType.XCAFDoc_ColorGen,
        XCAFDoc_ColorType.XCAFDoc_ColorCurv,
    )

    coloured: set[str] = set()
    seen: set[str] = set()

    def visit(label: TDF_Label) -> None:
        referred = TDF_Label()
        target = referred if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred) else label
        entry = StepLabel(document, target).entry
        if entry in seen:
            return
        seen.add(entry)
        if entry in replaced_labels:
            return
        if any(color_tool.IsSet(target, kind) for kind in kinds):
            coloured.add(entry)
        children = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(target, children)
        for index in range(1, children.Length() + 1):
            visit(children.Value(index))
        if XCAFDoc_ShapeTool.IsAssembly_s(target):
            components = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(target, components)
            for index in range(1, components.Length() + 1):
                visit(components.Value(index))

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    for index in range(1, free.Length() + 1):
        visit(free.Value(index))
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
# fix; it is the only route this kernel's bindings leave open. (``render_step``
# does call ``Init_s()`` below, but for an unrelated reason — it defines the
# ``Interface_Static`` keys so those settings take effect at all — and it
# still does nothing for the counters below.)
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


def _defined_ids(text: bytes) -> list[int]:
    """Every id ``text`` itself *defines* (``#N = ...``), in file order.

    A chain also *references* external ids -- the shape it colours, a reused
    colour, an overridden item -- which must never move; those never match
    ``#N = `` and so are excluded automatically, generalising what a fixed
    nine-id range used to assume about a chain's own shape.
    """
    return [int(found) for found in re.findall(rb"#(\d+) = ", text)]


def _colour_sort_key(match: re.Match[bytes]) -> tuple[int, bytes, int]:
    """The shape a chain colours, its literal if own, and its colour id.

    The literal (absent, ``b""``, for a reused colour) and the referenced
    colour id are both stable, external facts about the chain's content,
    unaffected by which ids get reassigned -- unlike an id, neither is a
    float, so this stays a legal dict/set-free sort key across processes.
    """
    return (int(match.group(3)), match.group(5) or b"", int(match.group(4)))


def _check_reslot_integrity(
    result: bytes, chain_text: bytes, id_map: dict[int, int]
) -> None:
    """Refuse a reslot that lost, duplicated, or dangled an id.

    The count guard in ``_reslot_colours`` cannot see a structurally broken
    *output*. ``chain_text`` is the renumbered chains alone, gaps excluded:
    a gap is untouched payload that may define ids of its own (an
    unrelated product's entities), neither this pass's to own nor missing
    from it. Every id this pass assigned must be defined exactly once, and
    every reference a chain makes must resolve somewhere in the file.
    """
    defined = sorted(int(found) for found in re.findall(rb"#(\d+) = ", chain_text))
    if defined != sorted(id_map.values()):
        raise EmitterError(
            "_reslot_colours produced a duplicated or missing entity id; "
            "refusing to write a structurally invalid STEP file"
        )
    referenced = {int(found) for found in re.findall(rb"#(\d+)", chain_text)}
    resolvable = {int(found) for found in re.findall(rb"#(\d+) = ", result)}
    dangling = referenced - resolvable
    if dangling:
        raise EmitterError(
            f"_reslot_colours left {len(dangling)} dangling reference(s); "
            "refusing to write a structurally invalid STEP file"
        )


def _foreign_entity_in_gaps(payload: bytes, chains: list[re.Match[bytes]]) -> bool:
    """Whether a gap between two colour chains holds an entity of its own.

    Observed in practice as curve/edge styling (``CURVE_STYLE``,
    ``DRAUGHTING_PRE_DEFINED_CURVE_FONT``) physically interspersed in the
    tail by ``STEPCAFControl_Writer``'s own hash-based ordering -- a
    presentation subsystem this module does not parse. Such an entity's id
    is exactly as allocator-dependent as a colour chain's, but this pass
    has no chain of its own to re-seat it through, so it cannot be made
    canonical; only whitespace between two chains is safe to leave as is.
    """
    return any(
        re.search(rb"#\d+\s*=", payload[chains[i].end():chains[i + 1].start()])
        for i in range(len(chains) - 1)
    )


def _reslot_colours(payload: bytes, expected: int) -> bytes:
    """Re-seat every colour chain's content into the id slots content-order picks.

    ``STEPCAFControl_Writer::WriteColors`` hashes on the ``TShape`` pointer
    to decide *which* chain goes in *which* slot at the file's tail -- the
    pointer, not the file, so two writes of the same document permute the
    slots. See the comment below for why this renumbers through one global
    id map rather than a per-chain delta, and why the renumbered chains are
    also physically reassembled rather than merely renumbered in place.
    """
    # A per-chain delta (this function's own history) assumed every chain
    # owned the same count of contiguous ids and referenced no id another
    # chain defines -- both true only while every chain colours a whole
    # solid. A sub-shape colour breaks both: chains run 7, 8 or 9 ids
    # depending on whether they carry a shared wrapper or their own
    # COLOUR_RGB, and a wrapper's reference list names *sibling* chains'
    # own ids. This instead builds one id map across every chain -- the
    # pool of every id any chain defines, in slot (file) order, handed out
    # to chains in *content*-sorted order -- and renumbers the whole
    # region through that single table, so a reference to any chain's id
    # resolves correctly wherever that chain ends up. Renumbering alone
    # would not make two writes byte-identical (the surrounding text would
    # still sit at its original, allocator-dependent offset), so the
    # renumbered chains are also physically reassembled in content order;
    # the gap between two chains (in practice just the writer's own line
    # break) travels by position, since a gap carries no id of its own to
    # place it by content instead.
    chains = list(_COLOUR_CHAIN.finditer(payload))
    # Checked unconditionally, before the "nothing to reorder" shortcut
    # below: a silent count mismatch — not just zero matches — is exactly
    # what a future OpenCASCADE upgrade reshaping this chain would produce,
    # and reordering nothing looks identical to reordering correctly unless
    # the count is verified against ``expected``, the source document's own.
    if len(chains) != expected:
        raise EmitterError(
            f"the source document assigns {expected} colour(s), but "
            f"{len(chains)} colour chain(s) were found in the written STEP. "
            "Either this document colours through a route the census does not "
            "walk, or _COLOUR_CHAIN needs updating for this OpenCASCADE "
            "version's chain shape"
        )
    if len(chains) < 2:
        return payload

    # The renumbering below assumes every entity in the region belongs to
    # some chain it can re-seat; a foreign entity's own id is exactly as
    # allocator-dependent, but this pass has no way to make it canonical.
    # Before this task such a document was refused outright (the census
    # under-counted it); this restores that safe refusal for precisely the
    # documents this widened census still cannot make deterministic,
    # rather than silently emitting non-canonical bytes.
    if _foreign_entity_in_gaps(payload, chains):
        raise EmitterError(
            "the colour region contains foreign entities between chains "
            "-- presentation data (e.g. curve or edge styling) this module "
            "does not parse -- so the output could not be made canonical; "
            "refusing to write a STEP file whose bytes would not be "
            "deterministic across processes"
        )

    ordered = sorted(chains, key=_colour_sort_key)

    # The pool is every id any chain defines, concatenated in slot (file)
    # order -- already ascending, since chains are non-overlapping matches
    # found in file order and ids only increase through the file. Handing
    # its entries out to chains in content order, one chain's own count at
    # a time, is a bijection: the pool's total length is exactly the sum of
    # what every chain consumes.
    pool = [id_ for chain in chains for id_ in _defined_ids(chain.group(0))]
    id_map: dict[int, int] = {}
    cursor = 0
    for chain in ordered:
        own = _defined_ids(chain.group(0))
        id_map.update(zip(own, pool[cursor:cursor + len(own)]))
        cursor += len(own)

    def remap(match: re.Match[bytes]) -> bytes:
        old = int(match.group(1))
        return b"#" + str(id_map.get(old, old)).encode("ascii")

    renumbered = [re.sub(rb"#(\d+)", remap, chain.group(0)) for chain in ordered]
    gaps = [payload[chains[i].end():chains[i + 1].start()] for i in range(len(chains) - 1)]

    region_pieces: list[bytes] = []
    for index, content in enumerate(renumbered):
        region_pieces.append(content)
        if index < len(gaps):
            region_pieces.append(gaps[index])
    region = b"".join(region_pieces)

    result = payload[:chains[0].start()] + region + payload[chains[-1].end():]
    _check_reslot_integrity(result, b"".join(renumbered), id_map)
    return result


def render_step(
    document: TDocStd_Document,
    *,
    title: str,
    timestamp: str,
    originating_system: str,
    replaced_labels: frozenset[str] = frozenset(),
) -> bytes:
    """Render the XCAF document to STEP bytes, with a header carrying no clock reading.

    OCC's writer exposes no in-memory target, only a path, so this aims it at
    a scratch file the caller never sees and returns the finished bytes
    instead of a location -- the scratch file is an implementation detail of
    a path-only kernel API, not part of this function's contract.
    """
    require_kernel()

    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_Controller
    from OCP.TCollection import TCollection_HAsciiString
    from OCP.XSControl import XSControl_WorkSession

    # ``Interface_Static`` silently drops a value written to a key no
    # controller has defined yet, and constructing the writer below defines
    # both keys with OCC's own defaults -- discarding anything set before it.
    # Initialising here is what makes the two settings below take effect for a
    # caller who has not already read a STEP file in this process; a second
    # call leaves an already-set value alone, so writes stay independent.
    STEPControl_Controller.Init_s()
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    # Load-bearing for determinism, not just cosmetic: fixes the prefix the
    # translator's auto-generated wrapper product uses, which ``_normalise``
    # then strips the volatile "<counter>.1" suffix from.
    Interface_Static.SetCVal_s("write.step.product.name", _PRODUCT_NAME)
    session = XSControl_WorkSession()
    writer = STEPCAFControl_Writer(session, False)
    expected = _count_colour_assignments(document, replaced_labels)
    descriptor, scratch = tempfile.mkstemp(suffix=".stp")
    os.close(descriptor)
    scratch_path = Path(scratch)
    try:
        with _silence_stdout():
            writer.Transfer(document)

            header = APIHeaderSection_MakeHeader(session.Model())
            header.SetName(TCollection_HAsciiString(title))
            header.SetTimeStamp(TCollection_HAsciiString(timestamp))
            header.SetAuthorValue(1, TCollection_HAsciiString(""))
            header.SetOriginatingSystem(TCollection_HAsciiString(originating_system))
            writer.Write(str(scratch_path))
        payload = _normalise(scratch_path.read_bytes())
        return _reslot_colours(payload, expected)
    finally:
        scratch_path.unlink(missing_ok=True)
