"""The assembly model: the case, plus every board seated where it was placed.

Synthetic and kernel-backed, like ``test_clash.py``: the solids are built
through OCP directly because that is what a fixture is. Every scene breaks
the task's four named vacuity hazards on purpose -- a placement whose
rotation permutes all three axes rather than an identity, a seated depth
that is not zero, two boards rather than one, and colours neither uniform
nor all distinct, so a builder painting everything one colour and one that
cannot repeat a colour both have somewhere to fail.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from stompcollider.emitters.assembly import AssemblyEmitter, Solids
from stompcollider.model import Board, DockData, Placement
from stompgeom.build import PlacedSolid, build_document, solid_colour
from stompgeom.step import StepSolid, bounding_box_mm, read_step
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration
from stompmodel.protocols import Emitter
from stompmodel.units import Nanometre

_SOURCE = (
    Path(__file__).resolve().parent.parent
    / "src" / "stompcollider" / "emitters" / "assembly.py"
)

_PCB = Path(__file__).resolve().parent / "fixtures" / "tar-pcb.stp"

#: Not one of STEP's pre-defined colours. A pure red, green or blue is
#: written as ``DRAUGHTING_PRE_DEFINED_COLOUR`` rather than ``COLOUR_RGB``,
#: a chain shape ``stompgeom.writer`` refuses outright -- avoided by choice
#: of colour, never silenced. See ``stompgeom/tests/test_build.py``.
_SLATE = (0.21, 0.43, 0.65)
_RUST = (0.75, 0.31, 0.12)
_MOSS = (0.10, 0.55, 0.90)
_CLAY = (0.60, 0.60, 0.05)


# --------------------------------------------------------------------------
# Kernel fixtures. Nothing is a cube and nothing sits on the origin: an
# axis-permuting placement is only visible on a solid whose three extents
# differ, and a placement's translation is only visible on a solid that was
# not already there.
# --------------------------------------------------------------------------


def _box(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


#: ``(name, colour, corner, extents)`` for each source solid. An empty name
#: is a solid nobody named -- legitimate input (ADR-0007) -- and a ``None``
#: colour is the control that colour is read per solid, not painted on.
_CASE_PARTS = (
    ("BOX", _SLATE, (-5.0, -5.0, -2.0), (60.0, 40.0, 3.0)),
    ("LID", _CLAY, (-5.0, -5.0, 30.0), (60.0, 40.0, 3.0)),
    ("", None, (50.0, 20.0, 0.0), (4.0, 4.0, 10.0)),
)

_BOARD_ONE_PARTS = (
    ("", _MOSS, (2.0, 3.0, 5.0), (20.0, 8.0, 1.6)),
    ("RV1", _RUST, (4.0, 5.0, 6.6), (3.0, 3.0, 9.0)),
    ("SW1", _CLAY, (14.0, 4.0, 6.6), (5.0, 4.0, 7.0)),
)

_BOARD_TWO_PARTS = (
    ("", _MOSS, (30.0, 3.0, 5.0), (12.0, 6.0, 1.6)),
    ("J1", _RUST, (32.0, 4.0, 6.6), (4.0, 3.0, 6.0)),
    ("D1", None, (38.0, 4.0, 6.6), (2.0, 2.0, 4.0)),
)


def _group(parts: tuple[tuple[str, Any, Any, Any], ...], reverse: bool = False) -> Solids:
    """One source document's solids, built the way a read file arrives.

    ``build_document`` is the published builder and ``read_step_document``
    the published read-back, so this fixture stands in for a file without
    inventing a second way to carry a name and a colour.
    """
    from stompgeom.step import read_step_document

    ordered = tuple(reversed(parts)) if reverse else parts
    document = build_document([
        PlacedSolid(_box(corner, *extents), name, colour, None)
        for name, colour, corner, extents in ordered
    ])
    return Solids(document=document, solids=read_step_document(document).solids)


# --------------------------------------------------------------------------
# Pure values.
# --------------------------------------------------------------------------


def _nm(value: float) -> Nanometre:
    return Nanometre(round(value * 1_000_000))


def _face_basis() -> CoordinateFrame:
    """A drilled face that is neither the model frame nor on its origin.

    ``w`` is the model's ``-y``, so an emitter that quietly measured a
    placement against the model frame, or forgot the face origin, lands
    somewhere else in all three axes. See ``FaceFrame``: the origin sits on
    the inner surface and ``w`` is the outward normal.
    """
    return CoordinateFrame(
        origin_nm=(_nm(7.0), _nm(11.0), _nm(13.0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 0.0, 1.0),
        w=(0.0, -1.0, 0.0),
    )


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _case() -> CaseRegistration:
    return CaseRegistration("1590BB", CaseFace("box"), "1590BB.stp", FaceFrame(_face_basis()))


def _board(ordinal: int, designators: tuple[str, ...]) -> Board:
    return Board(
        ordinal=ordinal,
        designators=designators,
        extent_nm=(_nm(20.0), _nm(8.0), _nm(1.6)),
        carrier=_identity_frame(),
        components=(),
        panel_face="+w",
    )


def _placement(
    rank: int, x_mm: float, y_mm: float, z_mm: float, theta_deg: float
) -> Placement:
    return Placement(
        rank=rank,
        x_nm=_nm(x_mm),
        y_nm=_nm(y_mm),
        z_nm=_nm(z_mm),
        theta_deg=theta_deg,
        correspondence=(),
        clashes=(),
    )


#: Board 1's chosen seating: a quarter turn about the face normal on top of
#: a face frame that is itself a quarter turn, so the composed rotation
#: permutes all three model axes -- and a seated depth of -28.085 mm, which
#: is not zero, so "exported w plus z" and "z alone" differ.
_ONE_CHOSEN = (21.0, 33.0, -28.085, 90.0)
#: The runner-up, listed *first* in the fixture so an emitter reading tuple
#: position rather than rank writes the board somewhere else entirely.
_ONE_RUNNER_UP = (1.0, 2.0, -3.0, 0.0)
_TWO_CHOSEN = (-9.0, 4.5, -12.25, 180.0)


def _seated(reverse: bool = False) -> DockData:
    """Two boards, each with its own chosen placement, on one drilled case."""
    boards: tuple[Board, ...] = (_board(1, ("RV1", "SW1")), _board(2, ("J1", "D1")))
    placements = {
        1: (_placement(2, *_ONE_RUNNER_UP), _placement(1, *_ONE_CHOSEN)),
        2: (_placement(1, *_TWO_CHOSEN),),
    }
    if reverse:
        boards = tuple(reversed(boards))
        placements = {2: placements[2], 1: placements[1]}
    return DockData(case=_case(), boards=boards, placements=placements)


def _emitter(reverse: bool = False) -> AssemblyEmitter:
    boards = {
        1: _group(_BOARD_ONE_PARTS, reverse),
        2: _group(_BOARD_TWO_PARTS, reverse),
    }
    return AssemblyEmitter(
        case=_group(_CASE_PARTS, reverse),
        boards=dict(reversed(list(boards.items()))) if reverse else boards,
        title="dock",
        timestamp="1970-01-01T00:00:00+00:00",
    )


def payload(reverse: bool = False) -> bytes:
    """One assembly's bytes. Public: the cross-process probe imports it."""
    return _emitter(reverse).emit(_seated(reverse))


# --------------------------------------------------------------------------
# Hand-worked expectations. Derived from ``CoordinateFrame``'s own published
# composition and written out here as arithmetic, never by calling the code
# under test: a test that asks the implementation what it did asserts
# nothing about what it should have done.
# --------------------------------------------------------------------------


def _seated_one(point: tuple[float, float, float]) -> tuple[float, float, float]:
    """Board 1 under its chosen placement: ``(28 - y, 39.085 - z, 46 + x)``.

    Face basis ``u=(1,0,0)``, ``v=(0,0,1)``, ``w=(0,-1,0)`` at
    ``(7, 11, 13)``; turned 90 degrees about ``w`` the target axes become
    ``u'=(0,0,1)``, ``v'=(-1,0,0)``, ``w'=w``, and the target origin
    ``(7+21, 11+28.085, 13+33)``.
    """
    x, y, z = point
    return (28.0 - y, 39.085 - z, 46.0 + x)


def _seated_two(point: tuple[float, float, float]) -> tuple[float, float, float]:
    """Board 2, turned 180 degrees: ``(-2 - x, 23.25 - z, 17.5 - y)``."""
    x, y, z = point
    return (-2.0 - x, 23.25 - z, 17.5 - y)


def _corners(
    corner: tuple[float, float, float], extents: tuple[float, float, float]
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        (corner[0] + dx, corner[1] + dy, corner[2] + dz)
        for dx in (0.0, extents[0])
        for dy in (0.0, extents[1])
        for dz in (0.0, extents[2])
    )


def _expected_box(
    corner: tuple[float, float, float],
    extents: tuple[float, float, float],
    seat: Any,
) -> tuple[float, ...]:
    moved = [seat(point) for point in _corners(corner, extents)]
    return tuple(
        round(value, 6)
        for value in (
            *(min(point[axis] for point in moved) for axis in range(3)),
            *(max(point[axis] for point in moved) for axis in range(3)),
        )
    )


def _read_back(payload_bytes: bytes) -> tuple[StepSolid, ...]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "assembly.stp"
        path.write_bytes(payload_bytes)
        return read_step(path).solids


def _named(solids: tuple[StepSolid, ...], name: str) -> StepSolid:
    found = [solid for solid in solids if solid.name == name]
    assert len(found) == 1, f"{name} appears {len(found)} times"
    return found[0]


def _box_of(solids: tuple[StepSolid, ...], name: str) -> tuple[float, ...]:
    return tuple(round(value, 6) for value in bounding_box_mm(_named(solids, name).shape))


# --------------------------------------------------------------------------
# What the assembly holds.
# --------------------------------------------------------------------------


def test_the_emitter_is_an_emitter_over_dock_data() -> None:
    emitter: Emitter[DockData] = _emitter()
    assert (emitter.name, emitter.media_type, emitter.extension) == (
        "assembly", "model/step", ".stp",
    )


def test_the_assembly_holds_the_case_solids_and_every_board_s_solids() -> None:
    solids = _read_back(payload())
    assert len(solids) == len(_CASE_PARTS) + len(_BOARD_ONE_PARTS) + len(_BOARD_TWO_PARTS)


def test_every_named_solid_keeps_the_name_it_arrived_with() -> None:
    names = {solid.name for solid in _read_back(payload())}
    assert {"BOX", "LID", "RV1", "SW1", "J1", "D1"} <= names


def test_a_solid_nobody_named_is_named_by_its_own_geometry() -> None:
    """The rule ``clash.solid_name`` states, so the report and the model
    name one unnamed case solid identically rather than twice over."""
    names = {solid.name for solid in _read_back(payload())}
    assert "case:unnamed@50000000,20000000,0" in names
    assert "board:1:unnamed@2000000,3000000,5000000" in names


# --------------------------------------------------------------------------
# Where each board lands. The whole point of the artefact.
# --------------------------------------------------------------------------


def test_a_board_is_written_at_its_placement_not_at_its_export_position() -> None:
    """A builder ignoring ``placement`` passes every count test above and
    fails this one: the composed rotation permutes all three axes, so a
    3 x 3 x 9 shaft comes back 3 x 9 x 3."""
    solids = _read_back(payload())
    assert _box_of(solids, "RV1") == _expected_box((4.0, 5.0, 6.6), (3.0, 3.0, 9.0), _seated_one)
    assert _box_of(solids, "RV1") != (4.0, 5.0, 6.6, 7.0, 8.0, 15.6)


def test_every_board_is_written_at_its_own_placement() -> None:
    """One board cannot tell "every board is placed" from "the first board
    is placed", so board 2 is seated by a different transform entirely."""
    solids = _read_back(payload())
    assert _box_of(solids, "J1") == _expected_box((32.0, 4.0, 6.6), (4.0, 3.0, 6.0), _seated_two)
    assert _box_of(solids, "J1") != _expected_box((32.0, 4.0, 6.6), (4.0, 3.0, 6.0), _seated_one)


def test_the_case_solids_are_written_where_they_already_were() -> None:
    """The case is not placed: only boards move. ``PlacedSolid.placement``
    is ``None`` for "leave where it was", never identity applied."""
    assert _box_of(_read_back(payload()), "LID") == (-5.0, -5.0, 30.0, 55.0, 35.0, 33.0)


def test_the_written_placement_is_the_rank_one_one_not_the_first_listed() -> None:
    """Board 1's placements are stored runner-up first, so an emitter
    reading tuple position writes the board 40 mm away from here."""
    solids = _read_back(payload())
    runner_up = _expected_box(
        (4.0, 5.0, 6.6), (3.0, 3.0, 9.0),
        lambda point: (point[0] + 8.0, 14.0 - point[2], 15.0 + point[1]),
    )
    assert _box_of(solids, "RV1") != runner_up
    assert _box_of(solids, "RV1") == _expected_box(
        (4.0, 5.0, 6.6), (3.0, 3.0, 9.0), _seated_one
    )


# --------------------------------------------------------------------------
# The seating datum: a board's seated depth is its exported ``w`` plus
# ``z_nm``. Nothing else in the workspace pairs a board with a drilled case,
# so nothing else can catch this composition wrong.
# --------------------------------------------------------------------------


def _face_w(box: tuple[float, ...]) -> tuple[float, float]:
    """``box``'s extent along the face normal, least first.

    The face frame's ``w`` is the model's ``-y`` and its origin sits at
    ``y = 11``, so a model point's depth on the face is ``11 - y`` exactly:
    no projection error, and the box maps corner for corner.
    """
    return (round(11.0 - box[4], 6), round(11.0 - box[1], 6))


def test_a_seated_board_s_depth_is_its_exported_w_plus_the_placement_z() -> None:
    """The datum this fixture exists to pin. ``RV1`` is exported reaching
    ``w`` 6.6 to 15.6 mm along its carrier normal and is seated at
    ``z = -28.085 mm``; it must end up at -21.485 to -12.485 mm on the
    face. A composition dropping the exported term reads -28.085 mm with
    no extent at all; one dropping ``z`` reads 6.6 to 15.6 mm.
    """
    exported = (6.6, 15.6)
    z_mm = -28.085

    seated = _face_w(_box_of(_read_back(payload()), "RV1"))

    assert seated == (round(exported[0] + z_mm, 6), round(exported[1] + z_mm, 6))
    assert seated != (z_mm, z_mm)
    assert seated != exported


def test_the_seating_datum_holds_for_the_second_board_too() -> None:
    """A one-board fixture could pin the datum by coincidence of that
    board's own export; ``J1`` is exported over a different span and
    seated to a different depth."""
    exported = (6.6, 12.6)
    z_mm = -12.25

    seated = _face_w(_box_of(_read_back(payload()), "J1"))

    assert seated == (round(exported[0] + z_mm, 6), round(exported[1] + z_mm, 6))
    assert seated != (z_mm, z_mm)
    assert seated != exported


# --------------------------------------------------------------------------
# Collisions.
# --------------------------------------------------------------------------


def _clashing() -> DockData:
    """Board 1 driven straight through the case floor."""
    return DockData(
        case=_case(),
        boards=(_board(1, ("RV1", "SW1")),),
        placements={1: (_placement(1, -9.0, -20.0, 0.0, 0.0),)},
    )


def _overlap(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    return all(
        first[axis] < second[axis + 3] and second[axis] < first[axis + 3]
        for axis in range(3)
    )


def test_a_clashing_placement_is_still_written_with_the_interference_intact() -> None:
    """Collisions are left in place: resolving one away, or dropping the
    offending solid, would hide the fault the tool exists to show."""
    emitter = AssemblyEmitter(
        case=_group(_CASE_PARTS),
        boards={1: _group(_BOARD_ONE_PARTS)},
        title="dock",
        timestamp="1970-01-01T00:00:00+00:00",
    )

    solids = _read_back(emitter.emit(_clashing()))

    substrate = _box_of(solids, "board:1:unnamed@2000000,3000000,5000000")
    assert _overlap(substrate, _box_of(solids, "BOX"))


# --------------------------------------------------------------------------
# Colour.
# --------------------------------------------------------------------------


def _colour_of(document: Any, solids: tuple[StepSolid, ...], name: str) -> Any:
    got = solid_colour(document, _named(solids, name))
    return None if got is None else tuple(round(channel, 4) for channel in got)


def _rounded(colour: tuple[float, float, float]) -> tuple[float, ...]:
    return tuple(round(channel, 4) for channel in colour)


def test_distinct_colours_survive_the_placement() -> None:
    """A builder painting every solid one colour passes a uniform fixture."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "assembly.stp"
        path.write_bytes(payload())
        written = read_step(path)

    assert _colour_of(written.document, written.solids, "BOX") == _rounded(_SLATE)
    assert _colour_of(written.document, written.solids, "LID") == _rounded(_CLAY)
    assert _colour_of(written.document, written.solids, "RV1") == _rounded(_RUST)


def test_a_colour_shared_by_solids_of_two_boards_survives_on_both() -> None:
    """The repeated-colour case ``stompgeom``'s writer now supports."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "assembly.stp"
        path.write_bytes(payload())
        written = read_step(path)

    assert _colour_of(written.document, written.solids, "RV1") == _rounded(_RUST)
    assert _colour_of(written.document, written.solids, "J1") == _rounded(_RUST)


def test_a_solid_nobody_coloured_stays_uncoloured() -> None:
    """The control on the two tests above: colour is read per solid, not
    painted across the assembly."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "assembly.stp"
        path.write_bytes(payload())
        written = read_step(path)

    assert _colour_of(written.document, written.solids, "D1") is None


# --------------------------------------------------------------------------
# Determinism.
# --------------------------------------------------------------------------


def test_two_writes_of_one_assembly_are_byte_identical() -> None:
    assert payload() == payload()


def test_two_orderings_of_the_same_geometry_are_byte_identical() -> None:
    """ADR-0006: no rule may consult input order. The solids of every
    group, the boards, and the mapping of ordinals to solids all arrive
    reversed."""
    assert payload() == payload(reverse=True)


def test_one_assembly_is_byte_identical_across_processes() -> None:
    """Hash randomisation differs only *between* processes, so a
    same-process comparison proves nothing about a set leaking its
    iteration order into the geometry's build sequence."""
    tests_dir = Path(__file__).resolve().parent
    script = (
        f"import sys; sys.path.insert(0, {str(tests_dir)!r}); "
        "from test_assembly import payload; "
        "import hashlib, sys as s; "
        "s.stdout.write(hashlib.sha256(payload()).hexdigest())"
    )

    def run(seed: str) -> str:
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.decode()

    assert run("1") == run("2") != ""


# --------------------------------------------------------------------------
# The rule this task carries: the emitter builds no kernel document itself.
# --------------------------------------------------------------------------

#: Names that only appear where a module assembles an XCAF document itself.
_DOCUMENT_NAMES = ("TDocStd_Document", "XCAFApp", "XCAFDoc_DocumentTool", "TDataStd_Name")


def _document_names(source: str) -> set[str]:
    return {name for name in _DOCUMENT_NAMES if name in source}


def _calls(source: str) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_the_document_scanner_finds_a_hand_built_document() -> None:
    """The guilty probe: a gate that can pass by finding nothing is not
    evidence until a deliberate breach makes it fail."""
    guilty = (
        "from OCP.TDocStd import TDocStd_Document\n"
        "document = TDocStd_Document('MDTV-XCAF')\n"
    )

    assert _document_names(guilty) == {"TDocStd_Document"}


def test_the_call_scanner_tells_an_import_from_a_call() -> None:
    """Its companion probe: importing the builder is not calling it."""
    assert "build_document" not in _calls(
        "from stompgeom.build import build_document\nx = 1\n"
    )
    assert "build_document" in _calls("document = build_document([])\n")


def test_the_emitter_builds_no_kernel_document_itself() -> None:
    """ADR-0008 and ``stompcollider-technical.md``:598-602: it calls the
    builder ``stompgeom`` promoted, and assembles nothing of its own."""
    source = _SOURCE.read_text(encoding="utf-8")

    assert _document_names(source) == set()
    assert {"build_document", "render_step"} <= _calls(source)


# --------------------------------------------------------------------------
# Refusals, and one real board.
# --------------------------------------------------------------------------


def test_a_board_with_placements_but_no_solids_is_refused() -> None:
    """Silently omitting it would look exactly like a board that is not
    there -- the same reason ``Clashes`` refuses rather than skips."""
    from stompmodel.errors import EmitterError

    emitter = AssemblyEmitter(
        case=_group(_CASE_PARTS),
        boards={1: _group(_BOARD_ONE_PARTS)},
        title="dock",
        timestamp="1970-01-01T00:00:00+00:00",
    )

    with pytest.raises(EmitterError, match="board 2"):
        emitter.emit(_seated())


def test_a_board_with_no_placement_is_left_out_rather_than_written_unplaced() -> None:
    """There is no seating to write it at, and writing it where it was
    exported would state a position nothing decided. Not a refusal: a board
    with no candidate at all is the error upstream withholds every artefact
    for, so this path belongs to a library caller, not to a run."""
    data = DockData(
        case=_case(),
        boards=(_board(1, ("RV1", "SW1")), _board(2, ("J1", "D1"))),
        placements={1: (_placement(1, *_ONE_CHOSEN),)},
    )

    names = {solid.name for solid in _read_back(_emitter().emit(data))}

    assert "RV1" in names
    assert "J1" not in names


def test_a_group_needs_a_solid() -> None:
    with pytest.raises(ValueError, match="at least one solid"):
        Solids(document=object(), solids=())


@pytest.mark.boards
def test_a_real_board_s_names_survive_the_placement() -> None:
    """Which is why ``stompgeom.shapes.placed`` locates rather than
    rebuilds, and why the census had to widen before this task existed."""
    read = read_step(_PCB)
    emitter = AssemblyEmitter(
        case=_group(_CASE_PARTS),
        boards={1: Solids(document=read.document, solids=read.solids)},
        title="dock",
        timestamp=read.timestamp,
    )

    names = {solid.name for solid in _read_back(emitter.emit(_seated_one_board()))}

    assert "RV1" in names and "BOX" in names


def _seated_one_board() -> DockData:
    return DockData(
        case=_case(),
        boards=(_board(1, ("RV1",)),),
        placements={1: (_placement(1, *_ONE_CHOSEN),)},
    )
