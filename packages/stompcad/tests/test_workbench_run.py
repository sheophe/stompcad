"""The run as an event: starting it, watching it, stopping it, quitting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event

import pytest
from textual.pilot import Pilot

from stompcad import cli, manifest
from stompcad.cancel import EXIT_CANCELLED, Cancelled
from stompcad.cli import Resolution
from stompcad.drive import Driver, Project, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan
from stompcad.present import Presentation
from stompcad.readiness import readiness
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench.app import Workbench
from stompcad.workbench.keys import Place
from stompcad.workbench.places import ValueRow
from stompcad.workbench.run import Launch, WorkbenchPresentation
from stompcad.workbench.session import Phase, Session
from stompmodel.diagnostics import Diagnostic, Severity

__all__: list[str] = []

_PANEL = Path("/project/tar.ai")


# -- the run, faked -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Data:
    """One half's data, as much of it as a run's outcome actually reads."""

    diagnostics: tuple[Diagnostic, ...] = ()

    def with_diagnostics(self, *diagnostics: Diagnostic) -> _Data:
        return _Data(self.diagnostics + diagnostics)

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        return tuple(found for found in self.diagnostics if found.severity is severity)

    @property
    def worst_severity(self) -> Severity | None:
        return max((found.severity for found in self.diagnostics), default=None)


class _Compose:
    """A stand-in for ``drive.compose``: a plan, its steps, and no kernel work.

    ``hold`` keeps the run in flight so the rules that only apply while one
    works have something to work against. It releases as soon as the app
    asks it to stop or stops running, because a fake that outlives its app
    is a hung suite rather than a failing test.
    """

    def __init__(self, hold: bool) -> None:
        self.hold = hold
        self.released = Event()

    def __call__(
        self,
        plan: RunPlan,
        presentation: Presentation,
        options: RunOptions,
        project: Project | None = None,
        stop: object = None,
        promote_warnings: bool = False,
    ) -> tuple[Driver, _Data, _Data | None]:
        assert isinstance(presentation, WorkbenchPresentation)
        app = presentation._app
        presentation.begin(plan)
        steps = plan.steps[:2] if self.hold else plan.steps
        for step in steps:
            presentation.finish_step(step, f"{step.key} done")
        while self.hold and not self.released.wait(0.02):
            if callable(stop) and stop():
                raise Cancelled("cancelled at 22%")
            if not app.is_running:
                raise Cancelled("the app went away")
        return Driver(plan, presentation, options), _Data(), None


def _fake_launch(hold: bool = False) -> Launch:
    """A launch whose composed run costs nothing; Task 11 runs the real one."""
    return Launch(panel=_PANEL, plan=DRILL_AND_DOCK, compose=_Compose(hold))


# -- the project ----------------------------------------------------------


def _session(ready: bool = True) -> Session:
    """A session whose edits are checked by the real consuming tool, as a run's are."""
    resolved = _runnable() if ready else replace(_runnable(), boards=DEFAULTS.boards)
    return Session(
        Resolution(
            settings=resolved,
            notes=(),
            blockers=readiness(resolved),
            project=manifest.Manifest(),
        ),
        validator=lambda settings, place: cli.validate_place(settings, place, _PANEL),
    )


def _runnable() -> Settings:
    """A project with nothing outstanding, so a run is one keypress away."""
    base = Settings.of_defaults(_PANEL)
    return replace(
        base,
        enclosure=replace(
            base.enclosure,
            case_model=Resolved(Path("/project/1590B.stp"), Provenance(Origin.PROJECT)),
        ),
        boards=replace(
            base.boards,
            boards=Resolved((Path("/project/tar-pcb.stp"),), Provenance(Origin.PROJECT)),
            panel_reference=Resolved("RV*", Provenance(Origin.PROJECT)),
        ),
        output=replace(
            base.output,
            targets=Resolved(
                (("excellon", Path("/project/tar-case.drl")),), Provenance(Origin.PROJECT)
            ),
        ),
    )


async def _settle(pilot: Pilot[int], app: Workbench) -> None:
    """Pause until the run is no longer working, however many frames that takes."""
    for _ in range(400):
        if app.session.phase is not Phase.RUNNING:
            return
        await pilot.pause()
        await asyncio.sleep(0.01)
    raise AssertionError(f"the run never settled; the phase is {app.session.phase}")


async def _edit_first_row(pilot: Pilot[int], app: Workbench) -> None:
    """Drive an edit into whatever this place states first."""
    rows = list(app.query(ValueRow))
    assert rows, f"{app.session.place.value} states no value, so no edit was driven"
    rows[0].focus()
    await pilot.pause()
    await pilot.press("enter")


# -- starting -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_takes_two_keys_to_start() -> None:
    """Decision 3: one bare letter committing minutes of kernel work is a hazard."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r")
        assert app.session.phase is Phase.IDLE
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.session.phase in (Phase.RUNNING, Phase.DONE)


@pytest.mark.asyncio
async def test_enter_on_the_project_run_row_is_the_other_way_in() -> None:
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        assert app.session.phase in (Phase.RUNNING, Phase.DONE)


@pytest.mark.asyncio
async def test_a_run_is_refused_while_the_project_is_not_ready() -> None:
    """Decision 17: readiness gates the run, and says which place answers."""
    app = Workbench(_session(ready=False), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        assert app.session.phase is Phase.IDLE
        assert "boards" in app.message.lower()


# -- while the run works --------------------------------------------------


@pytest.mark.asyncio
async def test_no_place_accepts_an_edit_while_the_run_works() -> None:
    """Decision 5. The guard: driven into every place, not just one."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        for key in "aedbo":
            await pilot.press(key)
            await _edit_first_row(pilot, app)
            assert "nothing is editable" in app.message
        assert app.session.settings == _session().settings


@pytest.mark.asyncio
async def test_every_bare_letter_still_moves_while_the_run_works() -> None:
    """The other half of decision 5: read-only, never hidden."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("d")
        assert app.session.place is Place.DRILLING


@pytest.mark.asyncio
async def test_an_open_editor_suppresses_the_chord_that_starts_a_run() -> None:
    """Decision 3: an open text field suppresses every key a place owns, chords too."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("d")
        row = next(row for row in app.query(ValueRow) if row.field == "title")
        row.focus()
        await pilot.pause()
        await pilot.press("enter", "ctrl+r")
        await pilot.pause()
        assert app.session.phase is Phase.IDLE


@pytest.mark.asyncio
async def test_the_same_chord_on_the_run_place_does_start_one() -> None:
    """The control: a suppression that never lifted would refuse every run."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        assert app.session.phase in (Phase.RUNNING, Phase.DONE)


# -- stopping and quitting ------------------------------------------------


@pytest.mark.asyncio
async def test_esc_on_the_run_place_stops_the_run() -> None:
    """Decision 14: `esc` is the cancel of the thing that place owns."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("escape")
        assert app.stopping


@pytest.mark.asyncio
async def test_ctrl_c_stops_a_run_from_anywhere() -> None:
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("d", "ctrl+c")
        assert app.stopping


@pytest.mark.asyncio
async def test_q_quits_rather_than_stopping() -> None:
    """Decision 14 splits ADR-0013's `q`: quitting and stopping are different acts."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running


@pytest.mark.asyncio
async def test_q_confirms_while_a_run_is_in_flight() -> None:
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert app.screen.query("#confirm")


@pytest.mark.asyncio
async def test_the_app_opening_with_no_run_exits_clean() -> None:
    """Decision 14: `0` if the app opened and no run happened."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
    assert app.return_value == 0


@pytest.mark.asyncio
async def test_a_cancelled_run_earns_the_shell_s_own_stop_code() -> None:
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("ctrl+c")
        await _settle(pilot, app)
        await pilot.press("q")
        await pilot.pause()
    assert app.return_value == EXIT_CANCELLED


# -- what the run leaves behind -------------------------------------------


@pytest.mark.asyncio
async def test_each_step_is_credited_as_it_completes() -> None:
    """The sidebar's left marker is derived from exactly this."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        assert app.session.reached(Place.DRILLING)


@pytest.mark.asyncio
async def test_the_run_place_keeps_the_line_a_pipe_would_have_received() -> None:
    """Decision 15: a run leaves its record behind either way."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        assert any("quantise" in line for line in app.settled)


@pytest.mark.asyncio
async def test_the_settled_lines_are_padded_to_the_plan_the_run_declared() -> None:
    """Decision 15: the workbench's exit lines are byte-compared against the pipe."""
    from stompcad.present import step_line

    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        width = max(len(step.label) for step in DRILL_AND_DOCK.steps)
        assert step_line("quantise", "quantise done", width) in app.settled
