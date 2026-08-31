"""One docking, two artefacts, one set of facts.

Neither artefact is checked against the value that produced it: each is read
back by an independent reader -- ``recovery/report.py`` through the standard
library's JSON parser, ``recovery/assembly.py`` through OCP's STEP parser --
and the two are then compared. No transform is shared, because one side reads
numbers out of a document and the other measures geometry out of a file.
"""

# The end-to-end scene comes from ``test_cli.py``: the docking under test is
# then one the whole pipeline really produced, and that fixture is already
# built to defeat accidental agreement -- two boards whose parts are named
# differently and listed out of ordinal order. It stubs
# ``sources.step.read_step`` for the two STEP inputs, because a written file
# cannot carry an unnamed substrate, so the real file read is not exercised
# here; ``test_source.py`` owns that.

from __future__ import annotations

import ast
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from stompcollider.cli import main
from stompcollider.emitters.assembly import AssemblyEmitter, Solids
from stompcollider.emitters.report import ReportEmitter
from stompcollider.model import Board, Correspondence, DockData, Placement
from stompgeom.build import PlacedSolid, build_document
from stompgeom.step import read_step_document
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration
from stompmodel.units import Nanometre, mm_from_nm, nm_from_mm
from tests.recovery import (
    RecoveredAssembly,
    RecoveredBoard,
    RecoveredDock,
    RecoveredPlacement,
    RecoveredSolid,
    midpoint_nm,
)
from tests.recovery.assembly import read_assembly
from tests.recovery.report import read_report
from tests.test_cli import (
    _HOLES_A,
    _HOLES_B,
    _PINS_A,
    _PINS_B,
    _both_boards,
    _prepare,
)

__all__: list[str] = []

RECOVERY = Path(__file__).resolve().parent / "recovery"

#: The substrate every board in ``test_cli``'s scene is built on, as exported:
#: 1.6 mm thick, its top face on its own carrier plane. Stated here because a
#: board's exported extent is what a stated ``z`` displaces.
_SLAB_Z_MM = (-1.6, 0.0)

#: Which pin carries which designator, from the scene's own numbering.
_EXPORTED_AXES_MM = {
    **{f"RV{number}": axis for number, axis in enumerate(_PINS_A, start=1)},
    **{f"SW{number}": axis for number, axis in enumerate(_PINS_B, start=1)},
}


def _docked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RecoveredDock, RecoveredAssembly]:
    """Run the two-board scene end to end, and read both artefacts back.

    Exit 1 is the scene's own verdict: two boards in one file is
    ``multiple-boards``, a warning, so both artefacts are still written.
    """
    run = _prepare(
        tmp_path, monkeypatch, board=_both_boards(),
        holes=_HOLES_A + _HOLES_B, bores=_HOLES_A + _HOLES_B,
    )

    assert main(run.argv) == 1

    return (
        read_report(run.report.read_text(encoding="utf-8")),
        read_assembly(run.assembly.read_bytes()),
    )


def _part_names(report: RecoveredDock) -> set[str]:
    """What the report says the model should call each board's parts."""
    return {
        f"board:{board.ordinal}:{designator}"
        for board in report.boards
        for designator in board.designators
    }


def _chosen(board: RecoveredBoard) -> RecoveredPlacement:
    """The placement the model was written at: rank 1, read by rank."""
    return min(board.placements, key=lambda placement: placement.rank)


def _substrate(assembly: RecoveredAssembly, ordinal: int) -> RecoveredSolid:
    """The one board body of ``ordinal``: the solid nobody named."""
    prefix = f"board:{ordinal}:unnamed@"
    found = [solid for solid in assembly.solids if solid.name.startswith(prefix)]
    assert len(found) == 1, f"{prefix}: {len(found)} board bodies, not one"
    return found[0]


# ---------------------------------------------------------------------------
# what both artefacts say about one docking
# ---------------------------------------------------------------------------


def test_both_artefacts_name_the_same_boards_and_the_same_parts(
    tmp_path, monkeypatch
) -> None:
    """Every designator the report lists is a solid the model carries, and
    the model carries no board part the report never mentioned.

    Set equality both ways, so a model that dropped a board and a model
    that invented one both fail. The two boards' parts are named
    differently on purpose: a run that paired an ordinal with the other
    board's geometry writes ``board:1:SW1`` and is caught here.
    """
    report, assembly = _docked(tmp_path, monkeypatch)

    stated = _part_names(report)
    held = {
        name for name in assembly.names
        if name.startswith("board:") and "unnamed@" not in name
    }

    assert stated == held
    assert {"board:1:RV1", "board:2:SW1"} <= stated
    assert "board:1:SW1" not in held


def test_every_part_sits_over_the_hole_the_report_pairs_it_with(
    tmp_path, monkeypatch
) -> None:
    """The docking claim itself: the report says ``RV1`` goes in hole 1 at
    a stated position, and the model puts that solid's axis there.

    The axis is the measured box's own middle, which for a round part is
    exactly where its axis runs. Compared as whole nanometres with no
    epsilon: the position is a canonical length in the report and a
    measurement in the model, and they must agree to the last one.
    """
    report, assembly = _docked(tmp_path, monkeypatch)

    checked = 0
    for board in report.boards:
        for pair in _chosen(board).correspondence:
            solid = assembly.named(f"board:{board.ordinal}:{pair.designator}")
            seated = solid.centre_nm
            assert (seated[0], seated[1]) == pair.hole_xy_nm, (
                f"{solid.name} is not over hole {pair.hole_index}"
            )
            checked += 1

    assert checked == len(_EXPORTED_AXES_MM), "no correspondence was compared"


def test_the_model_moved_each_part_rather_than_writing_it_where_it_was_exported(
    tmp_path, monkeypatch
) -> None:
    """The control for the test above: agreement there is not agreement by
    doing nothing.

    Every pin in this scene is exported at a position the docking does not
    leave it at -- the carrier basis alone turns the board a quarter turn --
    so a writer that ignored the placement entirely would disagree with the
    report about every part.
    """
    _report, assembly = _docked(tmp_path, monkeypatch)

    for board_ordinal, designators in ((1, ("RV1", "RV2", "RV3")), (2, ("SW1", "SW2"))):
        for designator in designators:
            solid = assembly.named(f"board:{board_ordinal}:{designator}")
            exported = _EXPORTED_AXES_MM[designator]
            seated = solid.centre_nm

            assert (seated[0], seated[1]) != (
                nm_from_mm(exported[0]), nm_from_mm(exported[1])
            ), f"{solid.name} was written where it was exported"


def test_the_depth_the_report_states_is_the_depth_the_model_holds(
    tmp_path, monkeypatch
) -> None:
    """``z_nm`` is what displaces the board along the face normal, so the
    board body's own extent in the model is its exported extent plus that.

    The body is the solid nobody named, which is what makes a board a
    board; a model that wrote only the parts would fail to find it. Both
    boards are checked, because one board could pin the datum by a
    coincidence of its own export.
    """
    report, assembly = _docked(tmp_path, monkeypatch)

    for board in report.boards:
        assert board.panel_face == "+w", "this scene seats both boards as exported"
        stated = _chosen(board).z_nm
        body = _substrate(assembly, board.ordinal)

        assert (body.box_nm[2], body.box_nm[5]) == (
            Nanometre(nm_from_mm(_SLAB_Z_MM[0]) + stated),
            Nanometre(nm_from_mm(_SLAB_Z_MM[1]) + stated),
        )


# ---------------------------------------------------------------------------
# a placement with every term of it turned on
# ---------------------------------------------------------------------------
#
# The scene above is what this pipeline can really produce, and every
# placement it produces has ``x``, ``y`` and ``theta`` at zero: a
# correspondence exists only where a part's axis already lies within the
# recognition tolerance of its hole, so the fitted transform is always the
# small one. A placement with all four terms non-zero therefore has to be
# stated rather than computed, and the two emitters are driven from it
# directly.

_EPOCH = "1970-01-01T00:00:00+00:00"

#: ``(name, corner, extents)`` in millimetres. Nothing is a cube and nothing
#: sits on an axis, so a rotation that dropped a term is visible.
_BOARD_PARTS = (
    ("", (3.0, 5.0, 6.6), (20.0, 8.0, 1.6)),
    ("RV1", (4.0, 6.0, 8.2), (3.0, 4.0, 9.0)),
)
_CASE_PARTS = (("PANEL", (-60.0, -60.0, 0.0), (120.0, 120.0, 3.0)),)

#: Two boards at different places and through different quarter turns: a
#: writer applying one board's motion to both disagrees with the report.
#: Both carry the one face there is -- which side points at the panel is
#: derived, not searched -- so it is the placements that must differ.
_SEATED = {
    1: ("+w", (11.0, -23.0, -9.0), 90.0),
    2: ("+w", (-7.0, 31.0, -4.0), 270.0),
}


def _identity() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _box(corner: tuple[float, float, float], extents: tuple[float, float, float]) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*corner), *extents).Shape()


def _solids(parts: tuple[tuple[str, Any, Any], ...]) -> Solids:
    document = build_document(
        [PlacedSolid(_box(corner, extents), name, None, None) for name, corner, extents in parts]
    )
    read = read_step_document(document)
    return Solids(document=read.document, solids=read.solids)


def _board(ordinal: int) -> Board:
    face, _translation, _theta = _SEATED[ordinal]
    return Board(
        ordinal=ordinal,
        designators=("RV1",),
        extent_nm=(nm_from_mm(20.0), nm_from_mm(8.0), nm_from_mm(1.6)),
        carrier=_identity(),
        components=(),
        panel_face=face,
    )


def _placement(ordinal: int) -> Placement:
    _face, translation, theta = _SEATED[ordinal]
    return Placement(
        rank=1,
        x_nm=nm_from_mm(translation[0]),
        y_nm=nm_from_mm(translation[1]),
        z_nm=nm_from_mm(translation[2]),
        theta_deg=theta,
        correspondence=(
            Correspondence(
                designator="RV1",
                hole_index=ordinal,
                hole_xy_nm=(nm_from_mm(translation[0]), nm_from_mm(translation[1])),
                insertion_nm=nm_from_mm(4.0),
                offset_nm=Nanometre(0),
                seat_nm=nm_from_mm(-6.0),
            ),
        ),
        clashes=(),
    )


def _stated() -> DockData:
    """Two boards, each seated somewhere the other is not."""
    return DockData(
        case=CaseRegistration("1590B", CaseFace.BOX, "case.stp", FaceFrame(_identity())),
        boards=tuple(_board(ordinal) for ordinal in sorted(_SEATED)),
        placements={ordinal: (_placement(ordinal),) for ordinal in sorted(_SEATED)},
    )


def _emitted() -> tuple[RecoveredDock, RecoveredAssembly]:
    """One value, both emitters, both artefacts read back independently."""
    data = _stated()
    boards = {ordinal: _solids(_BOARD_PARTS) for ordinal in sorted(_SEATED)}

    report = ReportEmitter().emit(data)
    model = AssemblyEmitter(_solids(_CASE_PARTS), boards, timestamp=_EPOCH).emit(data)

    return read_report(report.decode("utf-8")), read_assembly(model)


def _corners_mm(
    corner: tuple[float, float, float], extents: tuple[float, float, float]
) -> list[tuple[float, float, float]]:
    return [
        (corner[0] + dx, corner[1] + dy, corner[2] + dz)
        for dx in (0.0, extents[0])
        for dy in (0.0, extents[1])
        for dz in (0.0, extents[2])
    ]


def _seated_box_nm(
    corner: tuple[float, float, float],
    extents: tuple[float, float, float],
    placement: RecoveredPlacement,
    panel_face: str | None,
) -> tuple[Nanometre, ...]:
    """Where a stated placement puts a box, from the spec's own composition.

    Turn the board to face the panel, rotate by theta about that normal,
    then translate -- read out of the report and applied here, never taken
    from the code that wrote the model. The case's face frame is the model
    frame in this scene, so no projection stands between the two.
    """
    radians = math.radians(float(placement.theta_deg))
    cos, sin = math.cos(radians), math.sin(radians)
    shift = tuple(mm_from_nm(value) for value in (placement.x_nm, placement.y_nm, placement.z_nm))
    turned = [
        (x, y, z) if panel_face == "+w" else (x, -y, -z)
        for x, y, z in _corners_mm(corner, extents)
    ]
    moved = [
        (shift[0] + x * cos - y * sin, shift[1] + x * sin + y * cos, shift[2] + z)
        for x, y, z in turned
    ]
    return tuple(
        nm_from_mm(value)
        for value in (
            *(min(point[axis] for point in moved) for axis in range(3)),
            *(max(point[axis] for point in moved) for axis in range(3)),
        )
    )


def test_the_model_puts_each_board_where_the_report_says_it_put_it() -> None:
    """Every term of the placement is exercised: a turn, a translation in
    the face's plane, a depth along its normal, and the face itself.

    The prediction is computed from the report's own four numbers, so a
    model that dropped the rotation, transposed the translation, or ignored
    which way the board faces disagrees with the document that describes
    it.
    """
    report, assembly = _emitted()

    for ordinal in sorted(_SEATED):
        board = report.board(ordinal)
        placement = _chosen(board)
        for name, corner, extents in _BOARD_PARTS:
            solid = (
                assembly.named(f"board:{ordinal}:{name}")
                if name
                else _substrate(assembly, ordinal)
            )

            assert solid.box_nm == _seated_box_nm(
                corner, extents, placement, board.panel_face
            ), f"{solid.name} is not where the report placed board {ordinal}"


def test_the_two_boards_are_not_written_in_the_same_place() -> None:
    """The control for the test above: a prediction that matched both boards
    because both were written identically would prove nothing."""
    _report, assembly = _emitted()

    assert assembly.named("board:1:RV1").box_nm != assembly.named("board:2:RV1").box_nm


def test_the_case_is_written_where_it_was_and_is_named_what_it_was_called() -> None:
    """The case moves for nothing: the report echoes a registration and the
    model leaves the enclosure alone, so a placement leaking onto it shows
    here."""
    report, assembly = _emitted()
    (name, corner, extents) = _CASE_PARTS[0]

    assert report.case == ("1590B", "box", "case.stp")
    assert assembly.named(name).box_nm == tuple(
        nm_from_mm(value)
        for value in (
            corner[0], corner[1], corner[2],
            corner[0] + extents[0], corner[1] + extents[1], corner[2] + extents[2],
        )
    )


# ---------------------------------------------------------------------------
# the readers' own claims
# ---------------------------------------------------------------------------


def _report_text() -> str:
    return ReportEmitter().emit(_stated()).decode("utf-8")


def test_the_report_reader_reads_the_angle_exactly_rather_than_as_a_float() -> None:
    """Six decimals is the only formatting either artefact depends on, so
    the reader parses it as a decimal and a comparison can demand equality."""
    placement = _chosen(read_report(_report_text()).board(1))

    assert placement.theta_deg == Decimal("90.000000")


def test_the_report_reader_refuses_a_document_of_another_format() -> None:
    with pytest.raises(ValueError, match="not a stompcollider-dock-report"):
        read_report(_report_text().replace("stompcollider-dock-report", "something-else"))


def test_the_report_reader_refuses_a_key_it_does_not_model() -> None:
    """A reader that skipped what it does not model would pass a change to
    the document by omission, which is how a cross-artefact test rots."""
    with pytest.raises(ValueError, match="unhandled placement"):
        read_report(_report_text().replace('"rank": 1', '"rank": 1, "seated": true'))


def test_the_report_reader_refuses_a_length_that_is_not_whole_nanometres() -> None:
    """The dangerous failure is a plausible number in the wrong unit, so a
    length written as a decimal is refused rather than rounded."""
    with pytest.raises(ValueError, match="not a whole number of nanometres"):
        read_report(_report_text().replace('"x_nm": 11000000', '"x_nm": 11000000.5'))


def test_the_report_reader_reads_a_null_location_as_a_stated_absence() -> None:
    """``location_nm`` is emitted unconditionally; a reader treating it as
    optional could not tell a panel-wide finding from a dropped field."""
    text = _report_text().replace(
        '"diagnostics": []',
        '"diagnostics": [{"severity": "warning", "code": "clash", "message": "m",'
        ' "location_nm": null, "data": {}}]',
    )

    (found,) = read_report(text).diagnostics

    assert (found.code, found.location_nm) == ("clash", None)


def test_the_midpoint_refuses_an_extent_the_canonical_model_cannot_halve() -> None:
    with pytest.raises(ValueError, match="not a whole number of nanometres"):
        midpoint_nm(Nanometre(0), Nanometre(1))


def test_the_midpoint_is_exact_on_the_boundary_that_refusal_sits_on() -> None:
    """So the refusal above is rejecting a half nanometre, not every value."""
    assert midpoint_nm(Nanometre(0), Nanometre(2)) == 1


def test_the_assembly_reader_refuses_bytes_that_are_not_a_step_file() -> None:
    with pytest.raises(ValueError, match="not a readable STEP file"):
        read_assembly(b"ISO-10303-21;\nnothing here;\n")


def test_the_assembly_reader_refuses_a_name_that_stands_for_no_one_solid() -> None:
    """A comparison that silently took the first of two solids sharing a
    name would state a position for the wrong body."""
    _report, assembly = _emitted()

    with pytest.raises(ValueError, match="names 0 solids"):
        assembly.named("board:9:RV1")


# ---------------------------------------------------------------------------
# independence
# ---------------------------------------------------------------------------

#: The two packages that wrote these artefacts: ``stompcollider`` emitted the
#: report, and ``stompgeom``'s writer produced the STEP. A reader drawn from
#: either could invert that writer's own transform and prove it
#: self-consistent, which is not what this file claims.
FORBIDDEN = frozenset({"stompcollider", "stompgeom"})


def imported_roots(source: str) -> set[str]:
    """Every absolute import root in ``source``, plus the root of any relative
    import that escapes the subpackage.

    Every module here lives in ``tests.recovery``, so level 1 (``from .foo``)
    stays inside it, but level 2 or deeper (``from ..conftest``) climbs out
    to ``tests`` -- the route by which a recovery could reach the emitters it
    exists to check independently while staying invisible to a scan that
    only reads absolute imports.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and (
            node.level == 0 or node.level >= 2
        ):
            found.add(node.module.split(".")[0])
    return found


def recovery_modules() -> list[Path]:
    """Every module in the subpackage, sorted so a failure names a stable one."""
    return sorted(p for p in RECOVERY.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_scanner_finds_an_emitter_import() -> None:
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert "stompcollider" in imported_roots(
        "from stompcollider.emitters.report import _document"
    )


def test_the_scanner_finds_the_writers_own_package_too() -> None:
    """``stompgeom`` wrote the STEP, so reading it back through that package
    would be the same self-consistency, one artefact along."""
    assert "stompgeom" in imported_roots("import stompgeom.step")


def test_the_scanner_finds_a_relative_import_that_escapes_the_subpackage() -> None:
    """A level-2 relative import leaves ``tests.recovery`` for ``tests``,
    where the emitters this file exercises are already imported."""
    assert "test_cli" in imported_roots("from ..test_cli import _prepare")


def test_no_recovery_imports_a_package_that_wrote_what_it_reads() -> None:
    """The failure this must catch is a transform wrong in both directions,
    which self-consistency cannot see."""
    offenders = {
        str(module.relative_to(RECOVERY)): sorted(
            imported_roots(module.read_text(encoding="utf-8")) & FORBIDDEN
        )
        for module in recovery_modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_scan_reaches_every_recovery_module() -> None:
    """An empty or narrowed walk would pass the gate above by finding nothing."""
    scanned = {str(module.relative_to(RECOVERY)) for module in recovery_modules()}

    assert scanned == {"__init__.py", "report.py", "assembly.py"}
