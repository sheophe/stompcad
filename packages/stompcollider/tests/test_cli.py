"""The command line: which exit code a run earns, and which artefacts it writes.

Kernel-backed but synthetic, like ``test_clash.py``. Only the *file* reader is
stubbed, and only for the two STEP inputs: ``stompgeom``'s writer names every
product, so an unnamed substrate -- what makes a solid a board body -- survives
no round trip through a file. The drill document is a real file and both
artefacts are written to real paths. Every scenario is **one baseline with
exactly one thing changed**, so a suite that reached each exit code through an
unrelated fixture has nowhere to hide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from stompcollider.cli import main, parse_pin, parse_place
from stompcollider.errors import UsageError
from stompcollider.sources import step as source_step
from stompgeom.build import PlacedSolid, build_document
from stompgeom.step import StepDocument, read_step, read_step_document
from stompmodel.codec import to_document
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, DrillData, Hole
from stompmodel.units import Nanometre, nm_from_mm

# --------------------------------------------------------------------------
# Kernel solids. A pin is one solid with two coaxial cylinders, so its
# profile has a step in it: a plain peg would seat at zero depth and make a
# wrong seating indistinguishable from a right one.
# --------------------------------------------------------------------------


def _box(at: tuple[float, float, float], dx: float, dy: float, dz: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _cylinder(at: tuple[float, float, float], radius: float, height: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(*at), gp_Dir(0.0, 0.0, 1.0)), radius, height
    ).Shape()


def _pin(at: tuple[float, float]) -> Any:
    """An 11 mm shaft of radius 2 on a 3 mm bush of radius 3, fused into one solid.

    The step is what gives the profile a bounded insertion depth: through a
    5 mm hole it seats 8 mm down, which is the ``z`` every placement below
    is checked against.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    return BRepAlgoAPI_Fuse(
        _cylinder((at[0], at[1], 0.0), 2.0, 11.0), _cylinder((at[0], at[1], 0.0), 3.0, 3.0)
    ).Shape()


def _bored(shape: Any, centres: tuple[tuple[float, float], ...]) -> Any:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    for x, y in centres:
        shape = BRepAlgoAPI_Cut(shape, _cylinder((x, y, -5.0), 2.5, 20.0)).Shape()
    return shape


def _document(parts: tuple[tuple[str, Any], ...]) -> StepDocument:
    return read_step_document(
        build_document([PlacedSolid(shape, name, None, None) for name, shape in parts])
    )


#: Board A's three pins, in the board model's own frame. Deliberately not
#: symmetric about either axis: a symmetric layout pairs equally well with
#: the board turned over, which ``Match`` refuses as ``both-faced-group``.
#: The third is what lets a run place a board while the filter withholds one
#: of its parts.
_PINS_A = ((-7.0, 2.0), (9.0, 2.0), (0.0, -6.0))
#: Board B is board A's first two pins, 35 mm along the model's y axis.
_PINS_B = ((-7.0, 37.0), (9.0, 37.0))

#: Where those pins land in the face frame: the carrier basis is
#: ``u = -y``, ``v = x``, so a hole sits at ``(-y, x)`` of its pin.
_HOLES_A = ((-2.0, -7.0), (-2.0, 9.0), (6.0, 0.0))
_HOLES_B = ((-37.0, -7.0), (-37.0, 9.0))


def _slab(at_y: float) -> tuple[str, Any]:
    """An unnamed 30 x 20 x 1.6 slab: what makes a solid a board body."""
    return ("", _box((-15.0, at_y, -1.6), 30.0, 20.0, 1.6))


def _board_a_parts() -> tuple[tuple[str, Any], ...]:
    """One slab and its three pins -- the board every scenario below seats."""
    return (_slab(-10.0), *(
        (f"RV{number}", _pin(at)) for number, at in enumerate(_PINS_A, start=1)
    ))


@lru_cache(maxsize=None)
def _board_a() -> StepDocument:
    """One unnamed slab with three named pins on it -- the whole of a board."""
    return _document(_board_a_parts())


@lru_cache(maxsize=None)
def _both_boards() -> StepDocument:
    """Two slabs in one file, each with its own pins.

    The second board's parts are named differently from the first's, so a
    run that paired a board's ordinal with another board's solids writes
    ``board:1:SW1`` where the report says board 1 carries ``RV1``. Listed
    **out of ordinal order** on purpose: board 1 is the board nearer the
    face frame's origin, which is the one written second here, so a run
    that numbered boards by the order the file lists them fails rather
    than agreeing by accident.
    """
    return _document(
        (
            _slab(25.0),
            ("SW1", _pin(_PINS_B[0])),
            ("SW2", _pin(_PINS_B[1])),
            *_board_a_parts(),
        )
    )


@lru_cache(maxsize=None)
def _all_named() -> StepDocument:
    """A board file whose every solid is named: no board body to group onto."""
    return _document((("RV1", _pin(_PINS_A[0])), ("RV2", _pin(_PINS_A[1]))))


@lru_cache(maxsize=None)
def _partless() -> StepDocument:
    """Two board bodies where every component contacts the first."""
    return _document((*_board_a_parts(), _slab(200.0)))


@lru_cache(maxsize=None)
def _case(*, post: bool, bores: tuple[tuple[float, float], ...]) -> StepDocument:
    """The drilled panel, bored where the holes are, optionally with a post.

    The post is the one thing the clash scenario changes: it stands where
    the board seats, so the only difference between exit 0 and exit 1 is
    this solid's presence.
    """
    parts: tuple[tuple[str, Any], ...] = (
        ("PANEL", _bored(_box((-50.0, -25.0, 0.0), 100.0, 50.0, 3.0), bores)),
    )
    if post:
        parts = parts + (("POST", _box((-1.0, -1.0, -12.0), 2.0, 2.0, 5.0)),)
    return _document(parts)


#: The timestamp the case model carries, so the assembly's own can be shown
#: to come from the input rather than from a clock or from a default.
_CASE_TIMESTAMP = "2019-03-04T05:06:07+00:00"


def _timestamped(document: StepDocument) -> StepDocument:
    return StepDocument(document.solids, document.document, _CASE_TIMESTAMP)


# --------------------------------------------------------------------------
# The run under test.
# --------------------------------------------------------------------------


def _identity_face() -> FaceFrame:
    return FaceFrame(
        CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )


def _drill(path: Path, holes: tuple[tuple[float, float], ...], *, case: bool = True) -> Path:
    """A real drill document, written through stompmodel's own codec."""
    drilled = tuple(
        replace(
            Hole.from_measurement(nm_from_mm(x), nm_from_mm(y), nm_from_mm(5.0)),
            index=index,
        )
        for index, (x, y) in enumerate(holes, start=1)
    )
    registration = (
        CaseRegistration("1590B", CaseFace.BOX, "case.stp", _identity_face()) if case else None
    )
    path.write_text(
        json.dumps(to_document(DrillData(holes=drilled, case=registration))), encoding="utf-8"
    )
    return path


@dataclass(frozen=True)
class Run:
    """One prepared invocation: its arguments and the two paths it may write."""

    argv: list[str]
    report: Path
    assembly: Path

    def written(self) -> tuple[bool, bool]:
        return (self.report.exists(), self.assembly.exists())


def _prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    holes: tuple[tuple[float, float], ...] = _HOLES_A,
    board: StepDocument | None = None,
    post: bool = False,
    bores: tuple[tuple[float, float], ...] = _HOLES_A,
    case_model: bool = True,
    drill_case: bool = True,
    reference: str = "RV*,SW*",
) -> Run:
    """The baseline run, with exactly the one thing a caller changes changed."""
    drill = _drill(tmp_path / "drill.json", holes, case=drill_case)
    board_path, case_path = tmp_path / "board.stp", tmp_path / "case.stp"
    prepared = {board_path: board if board is not None else _board_a()}
    if case_model:
        prepared[case_path] = _timestamped(_case(post=post, bores=bores))

    def reader(path: Path) -> StepDocument:
        found = prepared.get(Path(path))
        return found if found is not None else read_step(Path(path))

    monkeypatch.setattr(source_step, "read_step", reader)
    report, assembly = tmp_path / "dock.json", tmp_path / "dock.stp"
    return Run(
        argv=[
            str(drill), str(board_path),
            "--case-model", str(case_path),
            "--panel-reference", reference,
            "--match-tolerance", "0.125",
            "--report", str(report),
            "--assembly", str(assembly),
        ],
        report=report,
        assembly=assembly,
    )


# --------------------------------------------------------------------------
# The four exit codes, from one baseline changed one thing at a time.
# --------------------------------------------------------------------------


def test_a_clean_run_exits_zero_and_writes_both_artefacts(tmp_path, monkeypatch) -> None:
    """The baseline every other scenario below is one change away from."""
    run = _prepare(tmp_path, monkeypatch)

    assert main(run.argv) == 0
    assert run.written() == (True, True)
    assert run.report.stat().st_size > 0 and run.assembly.stat().st_size > 0


def test_only_a_case_solid_moves_the_clean_run_to_a_finding(tmp_path, monkeypatch) -> None:
    """One post added to the case model; every other byte of the run is the same.

    A clash is a WARNING, so the artefacts are still written: withholding
    the model here would defeat the tool, which is why exit 1 is asserted
    together with both files rather than on its own.
    """
    run = _prepare(tmp_path, monkeypatch, post=True)

    assert main(run.argv) == 1
    assert run.written() == (True, True)
    assert [d["code"] for d in json.loads(run.report.read_text())["diagnostics"]] == ["clash"]


def test_only_moving_the_holes_moves_the_clean_run_to_an_error(tmp_path, monkeypatch) -> None:
    """Nothing but the two hole centres differs from the clean run."""
    run = _prepare(tmp_path, monkeypatch, holes=((40.0, 20.0), (40.0, 22.0)))

    assert main(run.argv) == 2
    assert run.written() == (False, False)


def test_only_a_malformed_filter_moves_the_clean_run_to_usage(tmp_path, monkeypatch) -> None:
    """Hazard 4: the usage case is otherwise valid, so exit 3 is the flag's own.

    Every other argument is the run that exits 0 above, so this cannot be
    exit 2 arriving early under another name.
    """
    run = _prepare(tmp_path, monkeypatch, reference="D(")

    assert main(run.argv) == 3
    assert run.written() == (False, False)


# --------------------------------------------------------------------------
# Withholding, as a set.
# --------------------------------------------------------------------------


def test_an_error_withholds_the_artefact_the_run_would_have_written_alone(
    tmp_path, monkeypatch
) -> None:
    """Both targets are requested, and neither appears -- not merely the second.

    Asked of the report alone as well: "withholds every artefact" and
    "withholds the one artefact it happened to render last" are the same
    sentence with one output and different sentences with two.
    """
    run = _prepare(tmp_path, monkeypatch, holes=((40.0, 20.0), (40.0, 22.0)))
    only_report = [argument for argument in run.argv[: run.argv.index("--assembly")]]

    assert main(only_report) == 2
    assert not run.report.exists()
    assert main(run.argv) == 2
    assert run.written() == (False, False)


def test_an_error_leaves_an_existing_target_exactly_as_it_was(tmp_path, monkeypatch) -> None:
    """Withheld means untouched, not truncated: an existing file keeps its bytes."""
    run = _prepare(tmp_path, monkeypatch, holes=((40.0, 20.0), (40.0, 22.0)))
    run.report.write_bytes(b"previous")
    run.assembly.write_bytes(b"previous")

    assert main(run.argv) == 2
    assert run.report.read_bytes() == b"previous"
    assert run.assembly.read_bytes() == b"previous"


def test_two_targets_reaching_one_file_are_refused(tmp_path, monkeypatch) -> None:
    """The promoted set check, from its second caller."""
    run = _prepare(tmp_path, monkeypatch)
    together = tmp_path / "one"
    argv = list(run.argv)
    argv[argv.index("--report") + 1] = str(together)
    argv[argv.index("--assembly") + 1] = str(together)

    assert main(argv) == 3
    assert not together.exists()


def test_the_set_check_admits_the_same_two_targets_spelled_apart(
    tmp_path, monkeypatch
) -> None:
    """The control on the refusal above: two paths, one file each, is a clean run."""
    run = _prepare(tmp_path, monkeypatch)

    assert main(run.argv) == 0


# --------------------------------------------------------------------------
# Resolved before any file is opened.
# --------------------------------------------------------------------------


def test_a_malformed_filter_is_reported_before_the_input_is_opened(tmp_path, capsys) -> None:
    """The filter's refusal, not the missing file's, is what the run reports.

    Exit code alone cannot prove the ordering -- a missing input is exit 3
    too -- so the message is what distinguishes them, and the control below
    shows the same arguments reporting the file when the filter parses.
    """
    argv = [
        str(tmp_path / "nowhere.json"), str(tmp_path / "nowhere.stp"),
        "--case-model", str(tmp_path / "nowhere.stp"),
        "--match-tolerance", "0.125",
    ]

    assert main([*argv, "--panel-reference", "D("]) == 3
    refused = capsys.readouterr().err
    assert main([*argv, "--panel-reference", "RV*"]) == 3
    opened = capsys.readouterr().err

    assert "designator filter" in refused and "nowhere.json" not in refused
    assert "nowhere.json" in opened


def test_a_pin_naming_an_impossible_ordinal_is_usage(tmp_path, monkeypatch, capsys) -> None:
    """Boards are numbered from one, so ordinal zero can name no board at all."""
    run = _prepare(tmp_path, monkeypatch)

    assert main([*run.argv, "--pin", "0=1"]) == 3
    assert "0" in capsys.readouterr().err
    assert run.written() == (False, False)


def test_a_place_naming_an_impossible_ordinal_is_usage(tmp_path, monkeypatch) -> None:
    assert main([*_prepare(tmp_path, monkeypatch).argv, "--place", "0=1,2,0"]) == 3


def test_a_malformed_place_is_usage(tmp_path, monkeypatch) -> None:
    assert main([*_prepare(tmp_path, monkeypatch).argv, "--place", "1=1,2"]) == 3


def test_a_well_formed_place_is_refused_because_nothing_honours_it(
    tmp_path, monkeypatch, capsys
) -> None:
    """Stated rather than silently ignored: no stage places a board explicitly.

    An accepted flag that changed nothing would be the worse failure -- the
    operator would read a placement they never got. See the task report.
    """
    run = _prepare(tmp_path, monkeypatch)

    assert main([*run.argv, "--place", "1=1,2,0"]) == 3
    assert "--place" in capsys.readouterr().err
    assert run.written() == (False, False)


def test_a_well_formed_pin_is_refused_for_the_same_reason(tmp_path, monkeypatch) -> None:
    assert main([*_prepare(tmp_path, monkeypatch).argv, "--pin", "1=1"]) == 3


def test_there_is_no_case_face_flag(tmp_path, monkeypatch) -> None:
    """A regression guard on a deliberate omission: the registration is read,
    never chosen. A future contributor adding the flag fails here, and the
    clean run above is the control that these arguments are otherwise good."""
    assert main([*_prepare(tmp_path, monkeypatch).argv, "--case-face", "lid"]) == 3


# --------------------------------------------------------------------------
# The panel-reference filter, applied rather than merely parsed.
# --------------------------------------------------------------------------


def test_a_filter_admitting_nothing_is_empty_group_and_not_a_parse_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    """A flag that does not fit this board: exit 2, at run time, never exit 3."""
    run = _prepare(tmp_path, monkeypatch, reference="J*")

    assert main(run.argv) == 2
    assert "empty-group" in capsys.readouterr().out
    assert run.written() == (False, False)


def test_a_filter_admitting_one_part_leaves_the_board_under_constrained(
    tmp_path, monkeypatch, capsys
) -> None:
    """The filter really narrows: two pins pair, one pin cannot fix a rotation.

    The control on ``empty-group`` above and on the clean run below -- the
    same board reaches three different verdicts through this flag alone,
    so a run that ignored the expression could satisfy at most one of them.
    """
    run = _prepare(tmp_path, monkeypatch, reference="RV1")

    assert main(run.argv) == 1
    assert "under-constrained-board" in capsys.readouterr().out


def test_a_withheld_part_still_reaches_the_report_and_the_model(
    tmp_path, monkeypatch
) -> None:
    """The filter chooses what pairs, never what a board is made of.

    ``RV3`` is no panel reference here, and the board is still placed by
    the other two: the report must still list it and the model must still
    carry its solid, because a filter that dropped components would lose
    geometry the clash check has to place.
    """
    run = _prepare(tmp_path, monkeypatch, reference="RV1,RV2")
    assert main(run.argv) == 0

    written = json.loads(run.report.read_text())
    assert written["boards"][0]["designators"] == ["RV1", "RV2", "RV3"]
    assert [c["designator"] for c in written["boards"][0]["placements"][0]["correspondence"]] == [
        "RV1", "RV2"
    ]
    assert "board:1:RV3" in run.assembly.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# Five decisions about input a run cannot use: which are findings, which end it.
# --------------------------------------------------------------------------


def test_a_board_file_with_no_board_body_is_an_error_diagnostic_not_an_abort(
    tmp_path, monkeypatch, capsys
) -> None:
    """Decision 1: ``no-substrate`` is a finding, exactly as the spec's table says.

    Exit 2 rather than 3 is the whole content of the decision: an abort out
    of the source would report the same sentence with the run classified as
    a usage failure, so the exit code is what pins it.
    """
    run = _prepare(tmp_path, monkeypatch, board=_all_named())

    assert main(run.argv) == 2
    assert "no-substrate" in capsys.readouterr().out
    assert run.written() == (False, False)


def test_a_board_body_carrying_no_component_is_refused_by_type(
    tmp_path, monkeypatch, capsys
) -> None:
    """Decision 2: named, not a bare ``ValueError`` escaping as a crash.

    ``main`` returns rather than raising, and the message names the file
    the input problem is in.
    """
    run = _prepare(tmp_path, monkeypatch, board=_partless())

    assert main(run.argv) == 3
    assert "board.stp" in capsys.readouterr().err
    assert run.written() == (False, False)


def test_an_unreadable_case_model_is_a_usage_failure_and_writes_nothing(
    tmp_path, monkeypatch
) -> None:
    """Decision 3: the run cannot begin, so it is exit 3 and not a diagnostic.

    There is nothing to check clearance against and nothing to assemble, so
    unlike an unreadable *board* -- which the source diagnoses and skips --
    this ends the run.
    """
    run = _prepare(tmp_path, monkeypatch, case_model=False)

    assert main(run.argv) == 3
    assert run.written() == (False, False)


def test_an_unreadable_board_is_diagnosed_rather_than_ending_the_run(
    tmp_path, monkeypatch, capsys
) -> None:
    """The source's own skip-and-diagnose, reached through the command line."""
    run = _prepare(tmp_path, monkeypatch)
    argv = list(run.argv)
    argv[1] = str(tmp_path / "absent.stp")

    assert main(argv) == 2
    assert "unreadable-board" in capsys.readouterr().out


def test_a_kernel_failure_is_reported_as_degenerate_geometry(
    tmp_path, monkeypatch, capsys
) -> None:
    """Decision 4: a boolean that could not be evaluated is a finding, exit 2.

    Injected at the one seam every kernel-backed step of the run passes
    through. Without the mapping this is exit 3, since a ``StompgeomError``
    is a ``StompError`` -- which is what the control below asserts still
    happens to the one failure that is *not* a finding.
    """
    from stompgeom.errors import StompgeomError

    run = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "stompcollider.cli.canonicalise",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(StompgeomError("no common region")),
    )

    assert main(run.argv) == 2
    assert "degenerate-geometry" in capsys.readouterr().out
    assert run.written() == (False, False)


def test_a_missing_kernel_stays_a_usage_failure(tmp_path, monkeypatch) -> None:
    """The control on the mapping above: not every ``StompgeomError`` is geometry.

    ``KernelUnavailable`` is one too, and calling a missing dependency a
    degenerate boolean would send the operator looking at their board.
    """
    from stompgeom.kernel import KernelUnavailable

    run = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "stompcollider.cli.canonicalise",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KernelUnavailable("no kernel")),
    )

    assert main(run.argv) == 3


def test_the_assembly_carries_the_case_models_own_timestamp(tmp_path, monkeypatch) -> None:
    """Decision 5: from the input, never from the clock and never a default."""
    run = _prepare(tmp_path, monkeypatch)
    assert main(run.argv) == 0

    assert _CASE_TIMESTAMP in run.assembly.read_text(encoding="utf-8", errors="replace")


def test_two_runs_over_one_input_write_identical_bytes(tmp_path, monkeypatch) -> None:
    """What the timestamp decision is for: nothing in either artefact varies."""
    first = _prepare(tmp_path, monkeypatch)
    assert main(first.argv) == 0
    report, assembly = first.report.read_bytes(), first.assembly.read_bytes()

    elsewhere = tmp_path / "again"
    elsewhere.mkdir()
    second = _prepare(elsewhere, monkeypatch)
    assert main(second.argv) == 0

    assert (second.report.read_bytes(), second.assembly.read_bytes()) == (report, assembly)


# --------------------------------------------------------------------------
# What the run actually says.
# --------------------------------------------------------------------------


def test_each_boards_ordinal_reaches_the_geometry_that_board_was_measured_from(
    tmp_path, monkeypatch
) -> None:
    """Two boards, differently named, so a swapped pairing is visible.

    The ordinal a board is numbered by is decided from geometry, not from
    the order the file lists its substrates; the solids handed to the clash
    check and to the assembly are paired by that same number. If the two
    were paired the other way round, the model would carry ``board:1:SW1``
    where the report says board 1 carries ``RV1``.
    """
    run = _prepare(
        tmp_path, monkeypatch, board=_both_boards(), holes=_HOLES_A + _HOLES_B,
        bores=_HOLES_A + _HOLES_B,
    )

    assert main(run.argv) == 1  # multiple-boards is a warning, on purpose
    written = json.loads(run.report.read_text())
    model = run.assembly.read_text(encoding="utf-8", errors="replace")

    assert [board["designators"] for board in written["boards"]] == [
        ["RV1", "RV2", "RV3"], ["SW1", "SW2"]
    ]
    assert "board:1:RV1" in model and "board:2:SW1" in model
    assert "board:1:SW1" not in model and "board:2:RV1" not in model


def test_the_report_states_the_seating_the_pipeline_computed(tmp_path, monkeypatch) -> None:
    """The written bytes, parsed: the emitter's document, not the console's prose.

    ``-8 mm`` is the profile's own insertion depth through a 5 mm hole, so a
    run that seated at the panel surface, or that never ran ``Seat``, says
    something else here.
    """
    run = _prepare(tmp_path, monkeypatch)
    assert main(run.argv) == 0

    written = json.loads(run.report.read_text())
    placement = written["boards"][0]["placements"][0]

    assert written["format"] == "stompcollider-dock-report"
    assert written["case"] == {"part": "1590B", "face": "box", "model": "case.stp"}
    assert (placement["x_nm"], placement["y_nm"], placement["z_nm"]) == (0, 0, -8_000_000)
    assert [c["designator"] for c in placement["correspondence"]] == ["RV1", "RV2", "RV3"]


def test_a_run_with_no_target_still_processes_and_reports(tmp_path, monkeypatch, capsys) -> None:
    """Both artefacts are optional; the exit code comes from the findings."""
    run = _prepare(tmp_path, monkeypatch, post=True)
    argv = run.argv[: run.argv.index("--report")]

    assert main(argv) == 1
    assert "clash" in capsys.readouterr().out
    assert run.written() == (False, False)


def test_verbose_traces_the_stages_without_changing_the_verdict(
    tmp_path, monkeypatch, capsys
) -> None:
    """``-v`` adds to what is printed and nothing to what is decided."""
    run = _prepare(tmp_path, monkeypatch)
    assert main(run.argv) == 0
    quiet = capsys.readouterr().out

    assert main([*run.argv, "-v"]) == 0
    loud = capsys.readouterr().out

    assert len(loud) > len(quiet)
    assert "match" in loud and "clashes" in loud


def test_a_drill_document_registering_no_case_model_is_refused(tmp_path, monkeypatch) -> None:
    """There is no face frame to dock against, and none may be invented."""
    run = _prepare(tmp_path, monkeypatch, drill_case=False)

    assert main(run.argv) == 3
    assert run.written() == (False, False)


def test_a_drill_document_holding_an_unnumbered_hole_is_refused(
    tmp_path, monkeypatch
) -> None:
    """Docking reads the drill number each hole was given, and invents none.

    The refusal is the codec's own -- the number is what the report and the
    drawing balloon a hole by -- and what this pins is that the command line
    reports it as a failed run rather than crashing on the way past.
    """
    run = _prepare(tmp_path, monkeypatch)
    drill = tmp_path / "drill.json"
    document = json.loads(drill.read_text())
    del document["holes"][0]["index"]
    drill.write_text(json.dumps(document), encoding="utf-8")

    assert main(run.argv) == 3
    assert run.written() == (False, False)


def test_help_exits_clean_and_lists_no_case_face(capsys) -> None:
    """``--help`` is not a usage failure, and what it lists is the contract."""
    assert main(["--help"]) == 0
    listed = capsys.readouterr().out

    assert "--panel-reference" in listed and "--case-face" not in listed


def test_an_unparseable_tolerance_is_usage(tmp_path, monkeypatch) -> None:
    run = _prepare(tmp_path, monkeypatch)
    argv = list(run.argv)
    argv[argv.index("--match-tolerance") + 1] = "nonsense"

    assert main(argv) == 3


def test_a_tolerance_of_zero_is_usage(tmp_path, monkeypatch) -> None:
    """Half a grid pitch is a length; nothing pairs within none of it."""
    run = _prepare(tmp_path, monkeypatch)
    argv = list(run.argv)
    argv[argv.index("--match-tolerance") + 1] = "0"

    assert main(argv) == 3


# --------------------------------------------------------------------------
# The two flags this build parses and refuses. Their grammar is still a
# contract: a malformed one must be reported as malformed, and the ordinal
# check is what makes "resolved before any file is opened" testable at all.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        "1",           # no separator at all
        "1=",          # an ordinal and nothing to do with it
        "one=1,2,3",   # an ordinal that is not a number
        "1=1,2",       # two fields where a placement needs three
        "1=1,2,3,4",   # four
        "1=1,2,up",    # a field that is not a number
        "1=1,2,nan",   # finite, or it places nothing
        "1=1,2,inf",
        "0=1,2,3",     # an ordinal no board can carry
        "-1=1,2,3",
    ],
)
def test_a_malformed_place_is_refused(spec: str) -> None:
    with pytest.raises(UsageError):
        parse_place(spec)


@pytest.mark.parametrize("spec", ["1", "1=", "one=1", "1=first", "1=0", "1=-2", "0=1"])
def test_a_malformed_pin_is_refused(spec: str) -> None:
    with pytest.raises(UsageError):
        parse_pin(spec)


def test_a_well_formed_place_and_pin_parse_to_what_they_say() -> None:
    """The control on the refusals above: this grammar accepts its own examples.

    Without it every refusal above would pass against a parser that refused
    everything, which is exactly what the two flags do one layer up.
    """
    assert parse_place(" 2 = 1.5 , -2.5 , 90 ") == (2, (1.5, -2.5, 90.0))
    assert parse_pin("3=2") == (3, 2)


# --------------------------------------------------------------------------
# Writing is one transaction over the whole set, not one per path.
# --------------------------------------------------------------------------


def test_a_target_that_cannot_be_staged_leaves_every_other_target_alone(
    tmp_path, monkeypatch
) -> None:
    """The run is clean, and one unwritable target still writes none of them.

    The clean run above is the control that these arguments otherwise
    produce two files, so what this asserts is the set behaving as one.
    """
    run = _prepare(tmp_path, monkeypatch)
    argv = list(run.argv)
    argv[argv.index("--assembly") + 1] = str(tmp_path / "absent" / "dock.stp")

    assert main(argv) == 3
    assert not run.report.exists()


@dataclass
class _RefusingWrite:
    """A staged write that will not commit -- the failure ``_commit`` unwinds."""

    path: Path

    def commit(self) -> int:
        raise OSError("no room on device")

    def discard(self) -> None:
        return None


def _refusing_second(monkeypatch: pytest.MonkeyPatch, refuse: Path) -> None:
    """Stage everything for real but ``refuse``, which fails at commit time."""
    from stompcollider import cli

    real = cli.stage_payload

    def staged(path: Path, payload: object) -> object:
        return _RefusingWrite(path) if path == refuse else real(path, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "stage_payload", staged)


def test_a_commit_that_fails_puts_back_the_target_already_replaced(
    tmp_path, monkeypatch
) -> None:
    """The report commits first; the assembly then fails, and the report goes back.

    Not merely "nothing new is written": the report had bytes of its own,
    and the guarantee is that they are the bytes still there afterwards.
    """
    run = _prepare(tmp_path, monkeypatch)
    run.report.write_bytes(b"previous")
    _refusing_second(monkeypatch, run.assembly)

    assert main(run.argv) == 3
    assert run.report.read_bytes() == b"previous"
    assert not run.assembly.exists()


def test_a_commit_that_fails_removes_a_target_that_was_not_there_before(
    tmp_path, monkeypatch
) -> None:
    """The other half of putting a target back: one that did not exist is removed."""
    run = _prepare(tmp_path, monkeypatch)
    _refusing_second(monkeypatch, run.assembly)

    assert main(run.argv) == 3
    assert run.written() == (False, False)


def test_a_rollback_that_itself_fails_does_not_displace_the_first_failure(
    tmp_path, monkeypatch
) -> None:
    """The residual ADR-0001 names, asserted rather than assumed.

    The assembly refuses to commit and putting the report back refuses too.
    What must survive is the original failure: the run still ends as one
    that could not write, rather than raising the second fault at the
    operator, and the report is left holding this run's bytes -- the one
    target ADR-0001 excludes from the guarantee.
    """
    from stompcollider import cli

    run = _prepare(tmp_path, monkeypatch)
    run.report.write_bytes(b"previous")
    real, seen = cli.stage_payload, set()

    def staged(path: Path, payload: object) -> object:
        if path == run.assembly or path in seen:
            return _RefusingWrite(path)
        seen.add(path)
        return real(path, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "stage_payload", staged)

    assert main(run.argv) == 3
    assert run.report.read_bytes() != b"previous"
