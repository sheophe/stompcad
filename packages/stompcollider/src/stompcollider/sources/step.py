"""Read board models, the case model and the drill document into ``RawBoards``.

Measurements only: every length that leaves here is a millimetre float,
upstream of ``canonicalise`` (ADR-0003). The kernel is reached through
``stompgeom``, never OCP, and the drill document through ``stompmodel``'s
codec, never ``stompdrill``. See "Reading boards" in
``docs/specs/stompcollider-technical.md``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from stompgeom.levels import Direction
from stompgeom.step import (
    StepDocument,
    StepSolid,
    assembly_spans,
    bounding_box_mm,
    read_step,
)
from stompmodel.codec import from_document
from stompmodel.diagnostics import Diagnostic
from stompmodel.errors import DocumentError
from stompmodel.model import EnclosureMatch
from stompmodel.units import Nanometre, format_nm, mm_from_nm, nm_from_mm

from ..boards import basis_about, carrier_frame, dot, group, negated, substrates
from ..errors import StompcolliderError
from ..protrude import admissible, protrusion_of, reach_along
from ..raw import RawBoard, RawBoards, RawComponent

__all__ = ["BoardSource"]


@dataclass(frozen=True, slots=True)
class BoardSource:
    """Every file one run reads, and the one measured result they make.

    ``boards`` is a list of models rather than one because a design may
    stack several; which board is which is settled downstream by ordinal,
    never by the order they are listed here.
    """

    drill: Path
    boards: Sequence[Path]
    case_model: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "boards", tuple(self.boards))
        if not self.boards:
            raise StompcolliderError("a docking run needs at least one board model to read")

    def read(self) -> RawBoards:
        """Measure every board, having first checked the case model is the right one.

        Board files are read in sorted order, not the order the operator
        listed them: two spellings of one command line must reach the same
        artefact, which ADR-0006 requires of element order generally.
        """
        drill = from_document(json.loads(self.drill.read_text(encoding="utf-8")))
        case = read_step(self.case_model)

        diagnostics: list[Diagnostic] = []
        mismatch = _cross_check(drill.enclosure, assembly_spans(case), self.case_model)
        if mismatch is not None:
            diagnostics.append(mismatch)

        measured: list[RawBoard] = []
        for path in sorted(self.boards):
            try:
                document = read_step(path)
            except DocumentError as failure:
                diagnostics.append(_unreadable(path, failure))
                continue
            measured.extend(_measure(document))

        if len(measured) > 1:
            diagnostics.append(
                Diagnostic.warning(
                    "multiple-boards",
                    f"the input holds {len(measured)} boards, not one",
                    data=(("boards", len(measured)),),
                )
            )
        return RawBoards(boards=tuple(measured), diagnostics=tuple(diagnostics))


def _unreadable(path: Path, failure: DocumentError) -> Diagnostic:
    """``path`` could not be read as a board, said without naming a directory.

    The file's name, never its path, exactly as ``wrong-case-model`` names
    the case model and ``CaseRegistration`` names its own: a diagnostic
    carrying where a file happened to sit would make one board read from two
    directories produce two artefacts, which is the byte-identity ADR-0006
    requires. The reader states the reason against the path it was given, so
    that spelling is reduced too rather than the reason being discarded.
    """
    return Diagnostic.error(
        "unreadable-board",
        str(failure).replace(str(path), path.name),
        data=(("model", path.name),),
    )


def _cross_check(
    enclosure: EnclosureMatch | None,
    spans_mm: tuple[float, float, float],
    path: Path,
) -> Diagnostic | None:
    """Compare the model's own footprint with the enclosure the panel identified.

    The same comparison ``stompdrill``'s ``CheckCaseClearance._cross_check``
    makes, and deliberately so: both pairs reduced to descending order --
    neither source states which of its two numbers is the length -- then
    exact nanometre equality. Product names never enter it. A panel that
    identified no enclosure has no footprint to compare, so there is nothing
    to check rather than something to guess at.
    """
    if enclosure is None:
        return None
    measured = _footprint_nm(spans_mm)
    identified = _descending((enclosure.length_nm, enclosure.width_nm))
    if measured == identified:
        return None
    return Diagnostic.error(
        "wrong-case-model",
        f"the drill document identifies a "
        f"{format_nm(identified[0])} x {format_nm(identified[1])} mm enclosure but "
        f"{path.name} measures {format_nm(measured[0])} x {format_nm(measured[1])} mm",
        data=(
            ("model", path.name),
            ("enclosure_nm", identified),
            ("model_nm", measured),
        ),
    )


def _footprint_nm(spans_mm: tuple[float, float, float]) -> tuple[Nanometre, Nanometre]:
    """The model's footprint: its two greatest spans, largest first.

    Which two is settled by dropping the shallowest axis, the depth --
    ``stompdrill``'s ``loader._footprint_and_axis`` reads the same three
    spans the same way, and a footprint measured differently in the two
    tools would make one ``wrong-case-model`` mean two things.
    """
    return _descending(tuple(nm_from_mm(span) for span in sorted(spans_mm)[1:]))


def _descending(pair: tuple[Nanometre, ...]) -> tuple[Nanometre, Nanometre]:
    """A footprint's two lengths, largest first."""
    larger, smaller = sorted(pair, reverse=True)
    return (larger, smaller)


def _measure(document: StepDocument) -> list[RawBoard]:
    """Every board ``document`` holds, each with the components grouped onto it."""
    found = substrates(document)
    return [_board(substrate, parts) for substrate, parts in group(document, found)]


def _board(substrate: StepSolid, parts: Sequence[StepSolid]) -> RawBoard:
    """One substrate and its parts, measured about the way those parts protrude."""
    frame = carrier_frame(substrate)
    if frame is None:  # pragma: no cover - substrates() admits only slabs
        raise StompcolliderError("no-substrate: a grouped solid measures no slab")
    outward = _outward(frame.w, substrate, parts)
    u, v = basis_about(outward)
    box = bounding_box_mm(substrate.shape)
    return RawBoard(
        corner_a_mm=(box[0], box[1], box[2]),
        corner_b_mm=(box[3], box[4], box[5]),
        carrier_origin_mm=tuple(mm_from_nm(value) for value in frame.origin_nm),  # type: ignore[arg-type]
        carrier_u=u,
        carrier_v=v,
        carrier_w=outward,
        components=tuple(_component(part, outward) for part in parts),
    )


def _component(part: StepSolid, outward: Direction) -> RawComponent:
    """``part``'s protrusion, or the same part stated as having no axis."""
    found = protrusion_of(part, outward)
    return found if found is not None else RawComponent(designator=part.name, axis_xy_mm=None)


def _outward(normal: Direction, substrate: StepSolid, parts: Sequence[StepSolid]) -> Direction:
    """Which way along the carrier normal the board's parts protrude.

    Derived, never assumed: ``carrier_frame`` publishes whichever carrier
    level sorts first, a choice it says carries no meaning, and reading a
    board from the wrong side measures its solder pins, not its controls.
    The vote is over the cylinders lying along the normal -- ``admissible``
    is sign-agnostic exactly so this may ask before the sign is known -- and
    the side one reaches furthest beyond the substrate wins. With no such
    cylinder either way nothing protrudes, so the frame's normal stands.
    """
    low, high = _extremes(bounding_box_mm(substrate.shape), normal)
    reaches = [
        reach_along(cylinder, normal)
        for part in parts
        for cylinder in admissible(part, normal)
    ]
    if not reaches:
        return normal
    forward = max(reach[1] for reach in reaches) - high
    backward = low - min(reach[0] for reach in reaches)
    return normal if forward >= backward else negated(normal)


def _extremes(
    box: tuple[float, float, float, float, float, float], axis: Direction
) -> tuple[float, float]:
    """How far ``box`` reaches along ``axis``, least first.

    Every one of the eight corners, not the two measured extremes: the
    carrier normal need not be a model axis, so the extreme corner there is
    not necessarily the extreme corner here. Named assumption: this is the
    substrate's *box*, which for a carrier normal oblique to the model axes
    holds slack the substrate itself does not, and unequal slack at the two
    ends could take :func:`_outward`'s tie the other way. Exact for every
    axis-aligned board, the committed fixture among them.
    """
    reach = [
        dot((x, y, z), axis)
        for x in (box[0], box[3])
        for y in (box[1], box[4])
        for z in (box[2], box[5])
    ]
    return (min(reach), max(reach))
