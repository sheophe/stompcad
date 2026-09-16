"""Every rule the workbench holds, driven without an application."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad import cli, manifest
from stompcad.cli import Resolution
from stompcad.present import Choice
from stompcad.readiness import Blocker, Readiness, readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.keys import Place
from stompcad.workbench.session import Locked, PendingGap, Phase, Refused, Session
from stompmodel.diagnostics import Diagnostic, Severity

__all__: list[str] = []

_PANEL = Path("/project/tar.ai")
_PLAN = frozenset({
    "read-panel", "quantise", "drill", "write-case",
    "read-boards", "match", "seat", "clash", "write-assembly",
})
#: What a project with no boards runs: decision 17's drill-only row.
_DRILL_ONLY = frozenset({"read-panel", "quantise", "drill", "write-case"})


def _settings(**places: object) -> Settings:
    """A complete, runnable project, with whatever this test overrides."""
    base = replace(
        Settings.of_defaults(_PANEL),
        enclosure=replace(
            DEFAULTS.enclosure,
            case_model=Resolved(Path("/project/1590B.stp"), Provenance(Origin.PROJECT)),
        ),
        boards=replace(
            DEFAULTS.boards,
            boards=Resolved((Path("/project/tar-pcb.stp"),), Provenance(Origin.PROJECT)),
            panel_reference=Resolved("RV*,SW*", Provenance(Origin.PROJECT)),
        ),
        output=replace(
            DEFAULTS.output,
            targets=Resolved((("excellon", Path("/project/tar-case.drl")),), Provenance(Origin.PROJECT)),
        ),
    )
    return replace(base, **places)  # type: ignore[arg-type]


def _session(settings: Settings | None = None, project: manifest.Manifest | None = None) -> Session:
    resolved = settings if settings is not None else _settings()
    held = project if project is not None else manifest.Manifest()
    return Session(
        Resolution(
            settings=resolved,
            notes=(),
            blockers=readiness(resolved),
            project=held,
        )
    )


def test_a_complete_project_may_run_and_says_so() -> None:
    """Decision 4: the one positive statement belongs on Project."""
    session = _session()
    assert session.may_run()
    assert session.statement() == "Everything needed is here. Press Enter to run."


def test_an_unresolved_board_list_blocks_the_run_and_marks_its_place() -> None:
    """Decision 17: not discovered and not declared is unresolved, not drill only."""
    session = _session(_settings(boards=DEFAULTS.boards))
    assert not session.may_run()
    assert session.attention(Place.BOARDS)
    assert not session.attention(Place.DRILLING)


def test_a_clean_project_shows_a_clean_sidebar() -> None:
    """Decision 4: the marker marks the exception, never the accomplishment."""
    session = _session()
    assert not any(row.attention for row in session.rows())


def test_findings_carries_a_count_rather_than_a_mark() -> None:
    session = _session()
    session.record_findings([
        Diagnostic(Severity.ERROR, "cannot-enter", "board 1 never enters"),
        Diagnostic(Severity.INFO, "inferred-enclosure", "from tar-case.stp"),
    ])
    row = next(row for row in session.rows() if row.place is Place.FINDINGS)
    assert row.count == 1
    assert not row.attention


def test_an_edit_records_its_origin_and_the_project_it_overrode() -> None:
    """Decision 7: where two ranks disagree, the row shows both."""
    session = _session(project=manifest.Manifest(values={"drilling": {"grid_mm": 0.25}}))
    session.set(Place.DRILLING, "grid_mm", 0.5)
    row = session.settings.drilling.grid_mm
    assert row.provenance.origin is Origin.USER
    assert row.describe() == "0.5, you set this — the project says 0.25"


def test_an_edit_agreeing_with_the_project_shows_no_disagreement() -> None:
    """The control: a row that always showed a disagreement would show nothing."""
    session = _session(project=manifest.Manifest(values={"drilling": {"grid_mm": 0.25}}))
    session.set(Place.DRILLING, "grid_mm", 0.25)
    assert session.settings.drilling.grid_mm.describe() == "0.25, you set this"


def test_an_output_change_makes_only_the_write_steps_stale() -> None:
    """Decision 10: propagation follows data, and a filename costs no kernel work."""
    session = _session()
    session.set(Place.OUTPUT, "targets", (("excellon", Path("/project/other.drl")),))
    assert session.stale() == {"write-case", "write-assembly"}
    assert session.roadmap() is Place.OUTPUT


def test_the_roadmap_falls_back_to_the_earliest_place_a_change_touched() -> None:
    session = _session()
    session.set(Place.OUTPUT, "targets", ())
    session.set(Place.DRILLING, "grid_mm", 0.5)
    assert session.roadmap() is Place.DRILLING


def test_the_left_marker_is_derived_from_the_stale_set() -> None:
    """Decision 4: the roadmap has no way to disagree with the engine."""
    session = _session()
    session.begin_run(_PLAN)
    for step in sorted(_PLAN):
        session.credit(step)
    session.finish_run(0)
    assert all(session.reached(place) for place in (Place.DRILLING, Place.OUTPUT))

    session.set(Place.DRILLING, "grid_mm", 0.5)
    assert not session.reached(Place.DRILLING)
    assert not session.reached(Place.OUTPUT)
    assert session.reached(Place.ARTWORK)


def test_a_credited_step_clears_a_change_only_once_every_reader_has_run() -> None:
    """`targets` is read twice; clearing it at the first would un-stale the second."""
    session = _session()
    session.set(Place.OUTPUT, "targets", ())
    session.begin_run(_PLAN)
    session.credit("write-case")
    assert "write-assembly" in session.stale()
    session.credit("write-assembly")
    assert session.stale() == frozenset()


def test_a_resume_adds_to_what_the_project_has_reached() -> None:
    """A resume runs a subset; it does not un-run everything it skipped."""
    session = _session()
    session.begin_run(_PLAN)
    for step in sorted(_PLAN):
        session.credit(step)
    session.finish_run(0)

    session.set(Place.OUTPUT, "targets", ())
    session.begin_run(session.stale(), fresh=False)
    session.credit("write-case")
    session.credit("write-assembly")
    session.finish_run(0)

    assert session.reached(Place.ARTWORK)
    assert session.reached(Place.OUTPUT)


def test_a_fresh_run_forgets_what_an_earlier_one_reached() -> None:
    """The control: a run of a different plan must not inherit the old one's credit."""
    session = _session()
    session.begin_run(_PLAN)
    for step in sorted(_PLAN):
        session.credit(step)
    session.begin_run(frozenset({"read-panel"}))
    assert not session.reached(Place.OUTPUT)


def test_an_interrupted_resume_leaves_the_steps_it_never_reached_stale() -> None:
    """Decision 4: a change clears when every step it invalidated has run, not its readers.

    ``grid_mm`` is read by ``quantise`` alone but invalidates the drill and
    write steps too, so a resume stopped after quantisation must still
    report drilling as unreached.
    """
    session = _session()
    session.begin_run(_PLAN)
    for step in sorted(_PLAN):
        session.credit(step)
    session.finish_run(0)

    session.set(Place.DRILLING, "grid_mm", 0.5)
    session.begin_run(session.stale(), fresh=False)
    session.credit("quantise")

    assert session.stale() != frozenset()
    assert not session.reached(Place.DRILLING)


def _boardless() -> Settings:
    """A project that has declared it has no boards, and is ready to run anyway."""
    base = _settings()
    return replace(
        base, boards=replace(base.boards, boards=Resolved((), Provenance(Origin.PROJECT)))
    )


def test_a_first_run_plans_the_steps_this_project_s_own_plan_holds() -> None:
    """Decision 17: no boards means no dock half, so no dock step is planned."""
    session = _session(_boardless())
    session.start_run(resuming=False)
    for step in sorted(_DRILL_ONLY):
        session.credit(step)
    assert session.phase is Phase.RUNNING
    assert session.reached(Place.OUTPUT)


def test_a_boardless_resume_returns_the_project_to_reached() -> None:
    """Decision 4: the roadmap cannot claim a step stale that this project never runs.

    With no boards the driver drops the dock half, so planning ``write
    assembly`` would wait on a step no run will credit: ``targets`` would
    stay stale for ever and `Output` would never read as reached again.
    """
    session = _session(_boardless())
    session.begin_run(_DRILL_ONLY)
    for step in sorted(_DRILL_ONLY):
        session.credit(step)
    session.finish_run(0)
    assert session.reached(Place.OUTPUT)

    session.set(Place.OUTPUT, "targets", ())
    assert session.stale() == frozenset({"write-case"})
    session.start_run(resuming=True)
    session.credit("write-case")
    session.finish_run(0)

    assert session.stale() == frozenset()
    assert session.reached(Place.OUTPUT)


def test_a_project_with_a_board_still_plans_its_dock_half() -> None:
    """The control: dropping the dock half is the boards' answer, never a default."""
    session = _session()
    session.begin_run(_PLAN)
    for step in sorted(_PLAN):
        session.credit(step)
    session.finish_run(0)

    session.set(Place.OUTPUT, "targets", ())
    assert session.stale() == frozenset({"write-case", "write-assembly"})
    session.start_run(resuming=True)
    session.credit("write-case")
    assert not session.reached(Place.OUTPUT), "the dock half's write step has not run"

    session.credit("write-assembly")
    assert session.stale() == frozenset()
    assert session.reached(Place.OUTPUT)


def test_nothing_is_editable_while_a_run_is_active() -> None:
    """Decision 5: read-only, never hidden."""
    session = _session()
    session.begin_run(_PLAN)
    for place in Place:
        assert not session.may_edit(place)
    with pytest.raises(Locked):
        session.set(Place.DRILLING, "grid_mm", 0.5)


def test_every_place_is_still_reachable_while_a_run_is_active() -> None:
    """The other half of decision 5: readable everywhere, editable nowhere."""
    session = _session()
    session.begin_run(_PLAN)
    session.go(Place.DRILLING)
    assert session.place is Place.DRILLING
    assert session.settings.drilling.grid_mm.value == 0.25


def test_only_the_paused_place_accepts_an_edit() -> None:
    """Decision 12: the app navigates to the place that can answer."""
    session = _session()
    session.begin_run(_PLAN)
    session.pause(PendingGap(
        code="ambiguous-enclosure",
        step="quantise",
        place=Place.ENCLOSURE,
        choice=Choice("which part?", ("1590B", "1590B2")),
    ))
    assert session.place is Place.ENCLOSURE
    assert session.may_edit(Place.ENCLOSURE)
    assert not session.may_edit(Place.DRILLING)


def test_a_second_gap_replaces_the_first_rather_than_queueing() -> None:
    """Decision 12: the second may not exist once the first is answered."""
    session = _session()
    session.begin_run(_PLAN)
    session.pause(PendingGap("ambiguous-enclosure", "quantise", Place.ENCLOSURE, None))
    session.pause(PendingGap("empty-group", "read-boards", Place.BOARDS, None))
    assert session.gap is not None
    assert session.gap.code == "empty-group"
    assert session.place is Place.BOARDS


def test_answering_returns_the_run_to_running_with_no_second_action() -> None:
    session = _session()
    session.begin_run(_PLAN)
    session.pause(PendingGap("empty-group", "read-boards", Place.BOARDS, None))
    session.resumed()
    assert session.phase is Phase.RUNNING
    assert session.gap is None


def test_a_finished_run_leaves_the_code_it_earned() -> None:
    """Decision 14: the exit code is the last completed run's."""
    session = _session()
    assert session.exit_code == 0
    session.begin_run(_PLAN)
    session.finish_run(1)
    assert session.phase is Phase.DONE
    assert session.exit_code == 1


def test_an_unreadable_project_blocks_the_run_and_says_why() -> None:
    """Decision 9: a project whose declarations cannot be read is never run under defaults."""
    resolved = _settings()
    session = Session(Resolution(
        settings=resolved,
        notes=(),
        blockers=Readiness((
            (Blocker.UNREADABLE_PROJECT, "project", "tar.stompcad.json: expecting ',' at line 3"),
        )),
        obstacle="tar.stompcad.json: expecting ',' at line 3",
    ))
    assert not session.may_run()
    assert "line 3" in session.statement()
    assert session.attention(Place.PROJECT)


def _blocked(panel: Path, *flags: str) -> Session:
    """A session opened on whatever ``cli.blocked`` made of this command line."""
    args = cli.build_parser().parse_args([str(panel), *flags])
    return Session(
        cli.blocked(args, panel.parent),
        validator=lambda settings, place: cli.validate_place(settings, place, panel),
    )


def test_a_refused_value_is_asked_again_once_its_place_answers(tmp_path: Path) -> None:
    """Decision 4: the roadmap has no way to disagree with the engine.

    The marker sends a builder to the place that owns the refused value, so
    answering it there must lift the refusal. A run still refused over a
    value nobody holds teaches a builder that the marker means nothing.
    """
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    session = _blocked(panel, "--case", "bogus")
    assert not session.may_run()
    assert session.attention(Place.ENCLOSURE)

    session.set(Place.ENCLOSURE, "case", "1590B")
    session.set(Place.BOARDS, "boards", ())
    session.set(Place.OUTPUT, "targets", (("excellon", tmp_path / "tar-case.drl"),))

    assert session.may_run()
    assert "bogus" not in session.statement().lower()
    assert session.statement() == "Everything needed is here. Press Enter to run."
    assert not any(row.attention for row in session.rows())


def test_a_duplicate_target_marks_the_place_that_owns_it(tmp_path: Path) -> None:
    """Decision 4: a marker on a place holding no values is no marker at all.

    Two artefacts naming one file is ``stompmodel``'s own sentence and names
    no flag of ours, so the refusal has to be labelled on the way past. Filed
    under `Project` it marks a place with no row to change, and no edit
    anywhere can then discharge it.
    """
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    session = _blocked(panel, "--emit", "excellon=out", "--emit", "json=out")
    assert [place for _blocker, place, _sentence in session.ready().blockers] == ["output"]
    assert session.attention(Place.OUTPUT)
    assert not session.attention(Place.PROJECT)

    session.set(Place.OUTPUT, "targets", (("excellon", tmp_path / "tar-case.drl"),))
    session.set(Place.BOARDS, "boards", ())

    assert session.may_run()
    assert session.statement() == "Everything needed is here. Press Enter to run."


def test_a_duplicate_target_the_project_declares_marks_output_too(tmp_path: Path) -> None:
    """The same sentence from the other rank, answered in the same place."""
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps(
            {"version": 1, "output": {"targets": {"excellon": "x.out", "json": "x.out"}}}
        ),
        encoding="utf-8",
    )
    session = _blocked(panel)
    assert [place for _blocker, place, _sentence in session.ready().blockers] == ["output"]
    assert "x.out" in session.statement()


def test_an_unreadable_project_survives_an_edit_to_something_else(tmp_path: Path) -> None:
    """Decision 9: the file is still unreadable, whatever else has been said.

    The control for the refusal above: an obstacle any edit at all lifted
    would lift this one too, and the project would then run under values
    that look like the user's own.
    """
    panel = tmp_path / "tar.ai"
    panel.write_bytes(b"")
    (tmp_path / "tar.stompcad.json").write_text("{not json", encoding="utf-8")
    session = _blocked(panel)
    assert not session.may_run()

    session.set(Place.DRILLING, "grid_mm", 0.5)

    assert not session.may_run()
    assert "tar.stompcad.json" in session.statement()
    assert session.attention(Place.PROJECT)


def test_a_file_already_on_disk_is_labelled_found_rather_than_current() -> None:
    """Decision 2: the manifest holds no hashes, so the app must not imply one."""
    session = _session()
    path = Path("/project/tar-case.drl")
    assert session.label_for(path, exists=True) == (
        "already on disk; this session has not made or verified it"
    )
    session.record_written([path])
    assert session.label_for(path, exists=True) == "made by this run"


def test_an_edit_the_consuming_tool_refuses_is_reverted_and_reported() -> None:
    """The rule belongs to the tool that reads the value, never to the workbench."""
    def refuse(settings: Settings, place: str) -> None:
        raise ValueError("drilling.grid_mm: a grid pitch of 0 describes no grid")

    session = Session(
        Resolution(settings=_settings(), notes=(), blockers=readiness(_settings()),
                   project=manifest.Manifest()),
        validator=refuse,
    )
    before = session.settings.drilling.grid_mm
    with pytest.raises(Refused, match="describes no grid"):
        session.set(Place.DRILLING, "grid_mm", 0.0)
    assert session.settings.drilling.grid_mm == before
    assert session.stale() == frozenset()


def test_an_edit_the_tool_accepts_stands() -> None:
    """The control: a validator that refused everything would prove nothing."""
    session = Session(
        Resolution(settings=_settings(), notes=(), blockers=readiness(_settings()),
                   project=manifest.Manifest()),
        validator=lambda settings, place: None,
    )
    session.set(Place.DRILLING, "grid_mm", 0.5)
    assert session.settings.drilling.grid_mm.value == 0.5


@pytest.mark.parametrize("place", [Place.PROJECT, Place.RUN, Place.FINDINGS])
def test_a_place_holding_no_values_refuses_an_edit_by_name(place: Place) -> None:
    """Only the five configuration places carry values; the others must say so."""
    session = _session()
    with pytest.raises(ValueError, match=place.value):
        session.set(place, "grid_mm", 0.5)


def test_designators_are_every_board_s_names_once_in_name_order() -> None:
    """Absent before a run, then the union a multiple picker offers."""
    session = _session()
    assert not session.designators
    session.record_designators({1: ("SW1", "RV1"), 2: ("RV1", "RV2")})
    assert session.designators == ("RV1", "RV2", "SW1")
