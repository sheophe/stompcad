"""The run as an event: starting it, watching it, stopping it, quitting."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, SelectionList, Static

from stompcad import cli, manifest
from stompcad.cancel import EXIT_CANCELLED, Cancelled
from stompcad.cli import Resolution
from stompcad.drive import Driver, Project, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan
from stompcad.present import Choice, Presentation
from stompcad.readiness import readiness
from stompcad.resolve import RESOLVABLE
from stompcad.settings import DEFAULTS, Origin, Provenance, Resolved, Settings
from stompcad.workbench import run
from stompcad.workbench.app import Workbench
from stompcad.workbench.dialog import Dialog
from stompcad.workbench.keys import Place
from stompcad.workbench.places import FocusRow, ValueRow
from stompcad.workbench.run import Launch, WorkbenchPresentation
from stompcad.workbench.session import PendingGap, Phase, Session
from stompmodel.diagnostics import EXIT_WARNINGS, Diagnostic, Severity
from stompmodel.progress import Scope

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

    def __init__(self, hold: bool, finding: Diagnostic | None = None) -> None:
        self.hold = hold
        self.finding = finding
        self.released = Event()

    def __call__(
        self,
        plan: RunPlan,
        presentation: Presentation,
        options: RunOptions,
        project: Project | None = None,
        stop: object = None,
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
        found = () if self.finding is None else (self.finding,)
        return Driver(plan, presentation, options), _Data(found), None


def _fake_launch(hold: bool = False, finding: Diagnostic | None = None) -> Launch:
    """A launch whose composed run costs nothing; Task 11 runs the real one."""
    return Launch(panel=_PANEL, plan=DRILL_AND_DOCK, compose=_Compose(hold, finding))


class _Asking:
    """A composed run that raises one gap, and keeps whatever answered it.

    The candidates are a tool's own answers for the code named, so the
    picker the app opens is the picker a real run would have raised.
    """

    def __init__(self, code: str, candidates: tuple[str, ...]) -> None:
        self.code = code
        self.candidates = candidates
        self.answers: list[str] = []

    def __call__(
        self,
        plan: RunPlan,
        presentation: Presentation,
        options: RunOptions,
        project: Project | None = None,
        stop: object = None,
    ) -> tuple[Driver, _Data, _Data | None]:
        presentation.begin(plan)
        gap = RESOLVABLE[self.code]
        self.answers.append(
            presentation.ask(
                Choice(
                    prompt="reference outline is within tolerance of more than one footprint",
                    candidates=self.candidates,
                    multiple=gap.multiple,
                    code=self.code,
                )
            )
        )
        return Driver(plan, presentation, options), _Data(), None


def _launch_raising(code: str, candidates: tuple[str, ...] = ("1590B", "1590B2")) -> Launch:
    """A launch whose run stops once on this code and waits to be answered."""
    return Launch(panel=_PANEL, plan=DRILL_AND_DOCK, compose=_Asking(code, candidates))


def _answers(app: Workbench) -> list[str]:
    """Every answer the faked run received, from the fake that received them."""
    launch = app.launch
    assert launch is not None and isinstance(launch.compose, _Asking)
    return launch.compose.answers


class _RecordingDriver(Driver):
    """A driver that records what a resume asked of it, and runs no step.

    Subclassed rather than duck-typed because the workbench keeps whatever
    ``compose`` hands back and spends it on the next `Ctrl+R`: a double
    that is not a ``Driver`` would prove nothing about that.
    """

    def __init__(self, plan: RunPlan, presentation: Presentation, options: RunOptions) -> None:
        super().__init__(plan, presentation, options)
        self.resumed: list[frozenset[str]] = []
        self.declared: list[Settings] = []

    def declare(self, settings: Settings) -> None:
        self.declared.append(settings)

    def resume(self, stale: frozenset[str], options: RunOptions, scope: Scope) -> None:
        self.resumed.append(stale)
        steps = tuple(step for step in self._plan.steps if step.key in stale)
        self._presentation.begin(RunPlan(steps))
        for step in steps:
            self._presentation.finish_step(step, f"{step.key} done")


#: What the stopped run below committed before the stop was heard.
_ARTEFACT = Path("/project/tar-case.drl")


class _StoppingDriver(_RecordingDriver):
    """A resume that commits one artefact and is then stopped at the next leaf.

    The order a real run has: ``write case`` commits, and the stop is heard
    at the leaf after it -- which is why a stopped run has something to say
    about what is on disk.
    """

    def resume(self, stale: frozenset[str], options: RunOptions, scope: Scope) -> None:
        self._written.append(_ARTEFACT)
        raise Cancelled("stopped after the artefact was committed")


class _Recording:
    """A composed run that hands back a driver the app can resume against."""

    def __init__(self, driver: type[_RecordingDriver] = _RecordingDriver) -> None:
        self.driver_type = driver
        self.driver: _RecordingDriver | None = None

    def __call__(
        self,
        plan: RunPlan,
        presentation: Presentation,
        options: RunOptions,
        project: Project | None = None,
        stop: object = None,
    ) -> tuple[Driver, _Data, _Data | None]:
        presentation.begin(plan)
        for step in plan.steps:
            presentation.finish_step(step, f"{step.key} done")
        self.driver = self.driver_type(plan, presentation, options)
        return self.driver, _Data(), None


def _recording_launch(driver: type[_RecordingDriver] = _RecordingDriver) -> Launch:
    """A launch whose driver outlives its run, as a real one's does."""
    return Launch(panel=_PANEL, plan=DRILL_AND_DOCK, compose=_Recording(driver))


def _recorded(app: Workbench) -> _RecordingDriver:
    """The driver the faked run handed back, from the fake that made it."""
    launch = app.launch
    assert launch is not None and isinstance(launch.compose, _Recording)
    driver = launch.compose.driver
    assert driver is not None, "nothing was composed, so nothing could be kept"
    return driver


async def _paused(pilot: Pilot[int], app: Workbench) -> None:
    """Pause until the run has stopped for its gap and the picker is drawn."""
    for _ in range(400):
        if app.session.phase is Phase.PAUSED:
            await pilot.pause()
            return
        await pilot.pause()
        await asyncio.sleep(0.01)
    raise AssertionError(f"the run never paused; the phase is {app.session.phase}")


async def _open_editor(pilot: Pilot[int], app: Workbench, field: str) -> None:
    """Open the one text field, on a row that carries one."""
    row = next(row for row in app.query(ValueRow) if row.field == field)
    row.focus()
    await pilot.pause()
    await pilot.press("enter")
    assert app.query("#editor"), "no field opened, so nothing below is about one"


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
    """Decision 3: an open text field suppresses every key a place owns, chords too.

    The message is the discriminator, not the phase: an unsuppressed
    ``ctrl+r`` here reaches the application and is refused for belonging to
    another place, which leaves the phase alone and would prove nothing.
    """
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _open_editor(pilot, app, "title")
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert app.message == ""
        assert app.session.phase is Phase.IDLE


@pytest.mark.asyncio
async def test_the_same_chord_with_no_field_open_reaches_the_application() -> None:
    """The control: a suppression that never lifted would silence the refusal too."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("d", "ctrl+r")
        await pilot.pause()
        assert "belongs to Run" in app.message


@pytest.mark.asyncio
async def test_an_open_field_keeps_the_chords_no_place_claims() -> None:
    """The other control: only what a table claims is suppressed, not every chord.

    ``ctrl+k`` is Textual's own "delete to the end of the line". Suppressing
    chords by their spelling took it, and every other editing chord, away
    from the one field this application has.
    """
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.press("d")
        await _open_editor(pilot, app, "title")
        for character in "Tar":
            await pilot.press(character)
        await pilot.press("left", "ctrl+k")
        assert app.query_one("#editor", Input).value == "Ta"


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
async def test_the_stop_is_heard_over_a_modal_holding_the_screen() -> None:
    """Why the stop is the one priority binding: a modal hides the app's table."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.screen.query("#confirm")
        await pilot.press("ctrl+c")
        assert app.stopping


@pytest.mark.asyncio
async def test_confirming_a_quit_during_a_run_earns_the_stop_code() -> None:
    """Decision 14: a run the user stopped exits 130, whatever it had reached."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value == EXIT_CANCELLED


@pytest.mark.asyncio
async def test_a_run_finishing_while_the_dialog_is_open_keeps_its_own_code() -> None:
    """The answer decides, not the moment the question was asked.

    A run can complete between the two, and a completed run earned its own
    code: a stop may end a run, never change what a completed one produced.
    """
    finding = Diagnostic(Severity.WARNING, "off-grid", "a hole moved 0.01 mm")
    composed = _Compose(hold=True, finding=finding)
    app = Workbench(_session(), launch=Launch(panel=_PANEL, compose=composed))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.screen.query("#confirm"), "no dialog, so nothing raced it"
        composed.released.set()  # the run finishes with the dialog still open
        await _settle(pilot, app)
        assert app.session.phase is Phase.DONE
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value == EXIT_WARNINGS


@pytest.mark.asyncio
async def test_quitting_after_a_completed_run_keeps_the_code_it_earned() -> None:
    """The control: a stop may end a run, never change what a completed one produced."""
    finding = Diagnostic(Severity.WARNING, "off-grid", "a hole moved 0.01 mm")
    app = Workbench(_session(), launch=_fake_launch(finding=finding))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        await pilot.press("q")
        await pilot.pause()
    assert app.return_value == EXIT_WARNINGS


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


@pytest.mark.asyncio
async def test_a_stopped_run_still_owns_what_it_committed() -> None:
    """Decision 2: "already on disk" is for a file this session did not make.

    A stop is noticed at the next leaf, so a write may have committed
    before it was heard. Labelling that file as merely found would deny
    work this very session did.
    """
    app = Workbench(_session(), launch=_recording_launch(_StoppingDriver))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        app.session.set(Place.OUTPUT, "targets", ())
        await pilot.press("ctrl+r")
        await _settle(pilot, app)
        assert app.session.exit_code == EXIT_CANCELLED
        assert app.session.label_for(_ARTEFACT, exists=True) == "made by this run"


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
async def test_the_run_place_lists_a_step_that_has_not_finished() -> None:
    """Decision 2: the `Run` place holds the step list live, not only what is done."""
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        await pilot.pause()
        listed = str(app.screen.query_one("#run-lines", Static).content)
        assert "read panel" in listed, "a finished step is missing from the list"
        assert "read-panel done" in listed
        assert "write assembly" in listed, "a step still to come is missing from the list"
        assert "write-assembly done" not in listed


@pytest.mark.asyncio
async def test_a_fault_after_the_app_has_gone_is_not_raised_on_the_worker() -> None:
    """A confirmed quit outruns the worker, and a raise there ends nowhere."""

    def explode(*_args: object, **_kwargs: object) -> NoReturn:
        raise ValueError("the kernel gave up")

    app = Workbench(_session(), launch=Launch(panel=_PANEL, compose=explode))
    async with app.run_test() as pilot:
        await pilot.pause()
    run._attempt(app)  # the crossing cannot be made; the fault has nowhere to go


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


# -- the pause that navigates ---------------------------------------------


@pytest.mark.asyncio
async def test_a_gap_pauses_the_run_and_takes_the_user_to_its_place() -> None:
    """Decision 12: the app navigates, rather than marking and leaving them to hunt."""
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        assert app.session.place is Place.ENCLOSURE
        assert app.session.phase is Phase.PAUSED


@pytest.mark.asyncio
async def test_only_the_paused_place_accepts_an_edit() -> None:
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        await pilot.press("d")
        await _edit_first_row(pilot, app)
        assert "nothing is editable" in app.message


@pytest.mark.asyncio
async def test_committing_the_answer_is_the_continuation() -> None:
    """Decision 12: no second action to find."""
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        await pilot.press("enter")
        await _settle(pilot, app)
        assert app.session.phase is Phase.DONE
        assert _answers(app) == ["1590B"]


@pytest.mark.asyncio
async def test_the_picker_says_that_choosing_continues_the_run() -> None:
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        titled = app.screen.query_one(Dialog).border_title
        assert titled is not None and "continue" in str(titled).lower()


@pytest.mark.asyncio
async def test_leaving_the_place_abandons_the_picker_without_stopping_the_run() -> None:
    """A picker is a transient widget; the run stays paused and reopenable."""
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        await pilot.press("d")
        assert not app.screen.query("#picker")
        assert app.session.phase is Phase.PAUSED
        assert not app.stopping


@pytest.mark.asyncio
async def test_the_gap_s_own_row_reopens_the_picker_that_was_abandoned() -> None:
    """Decision 12: abandoning a picker is recoverable, not the end of the run."""
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        await pilot.press("escape")
        assert not app.screen.query("#picker")
        await pilot.press("e")
        row = app.query_one("#gap-row", FocusRow)
        row.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query("#picker")


@pytest.mark.asyncio
async def test_esc_closes_the_picker_before_it_stops_the_run() -> None:
    """Decision 12: `esc` is a ladder, innermost first."""
    app = Workbench(_session(), launch=_launch_raising("ambiguous-enclosure"))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        await pilot.press("escape")
        assert not app.stopping
        await pilot.press("escape")
        assert app.stopping


@pytest.mark.asyncio
async def test_a_place_answering_by_a_free_edit_carries_a_continue_row() -> None:
    """The only control a place otherwise closed to editing gains.

    No code reaches this today: both resolvable codes are pickers, and
    ``question_for`` raises nothing without candidates. The mechanism is
    built and tested here rather than left for the first code that needs it.
    """
    app = Workbench(_session(), launch=_fake_launch(hold=True))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await pilot.pause()
        app.session.pause(PendingGap("off-grid", "quantise", Place.DRILLING, None))
        await app.redraw()
        await pilot.pause()
        assert app.query("#continue-run")


@pytest.mark.asyncio
async def test_a_gap_picker_committed_with_nothing_ticked_abandons_it() -> None:
    """Decision 11: an empty tick list is abandonment, never an answer.

    ``empty-group``'s answer widens a designator expression, so committing
    nothing would widen it with an empty term -- a filter the next step
    refuses, taking the paused run down with it one keypress from where the
    app itself sent the builder.
    """
    app = Workbench(_session(), launch=_launch_raising("empty-group", ("RV1", "RV2")))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        assert app.screen.query_one("#picker", SelectionList).selected == []

        await pilot.press("enter")
        await pilot.pause()

        assert app.session.phase is Phase.PAUSED
        assert app.session.gap is not None and app.session.gap.code == "empty-group"
        assert app.failure is None
        assert _answers(app) == [], "the run was answered with the empty commit"
        row = app.query_one("#gap-row", FocusRow)
        row.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query("#picker"), "the abandoned picker cannot be reopened"


@pytest.mark.asyncio
async def test_a_ticked_designator_still_answers_and_continues() -> None:
    """The control: what is abandoned is the empty commit, not every commit."""
    app = Workbench(_session(), launch=_launch_raising("empty-group", ("RV1", "RV2")))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _paused(pilot, app)
        app.screen.query_one("#picker", SelectionList).select("RV1")
        await pilot.pause()

        await pilot.press("enter")
        await _settle(pilot, app)

        assert app.session.phase is Phase.DONE
        assert _answers(app) == ["RV1"]


# -- resuming what a change invalidated -----------------------------------


@pytest.mark.asyncio
async def test_a_second_ctrl_r_after_a_change_resumes_rather_than_starting_over() -> None:
    """Decision 10: the stale set is what runs, against what the driver holds."""
    app = Workbench(_session(), launch=_recording_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        app.session.set(Place.OUTPUT, "targets", ())
        await pilot.press("ctrl+r")
        await _settle(pilot, app)
    assert _recorded(app).resumed == [frozenset({"write-case", "write-assembly"})]


@pytest.mark.asyncio
async def test_a_resume_is_never_automatic() -> None:
    """Decision 10: kernel work takes minutes, and a run that starts on a keystroke is hostile."""
    app = Workbench(_session(), launch=_recording_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        app.session.set(Place.DRILLING, "grid_mm", 0.5)
        await app.redraw()
        await pilot.pause()
    assert _recorded(app).resumed == []


@pytest.mark.asyncio
async def test_the_roadmap_retreats_to_the_place_a_change_touched() -> None:
    """Decision 4: the marker is the earliest place owning a stale step."""
    app = Workbench(_session(), launch=_recording_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        app.session.set(Place.DRILLING, "grid_mm", 0.5)
        await app.redraw()
        await pilot.pause()
        assert app.session.roadmap() is Place.DRILLING
        assert not app.session.reached(Place.DRILLING)
        assert app.session.reached(Place.ARTWORK)


@pytest.mark.asyncio
async def test_a_resume_declares_the_values_it_actually_ran_under() -> None:
    """Decision 8: the manifest records what made the outputs."""
    app = Workbench(_session(), launch=_recording_launch())
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        app.session.set(Place.DRILLING, "title", "Tar")
        await pilot.press("ctrl+r")
        await _settle(pilot, app)
    assert _recorded(app).declared[-1].drilling.title.value == "Tar"


# -- an invocation that said "do not ask me" -------------------------------


@pytest.mark.asyncio
async def test_an_argument_beyond_the_panel_opens_with_the_run_already_moving() -> None:
    """Decision 1: there is no batch flag, because there is nothing to batch."""
    app = Workbench(_session(), launch=_fake_launch(), autostart=True)
    async with app.run_test() as pilot:
        await _settle(pilot, app)
        assert app.session.phase is Phase.DONE


@pytest.mark.asyncio
async def test_a_project_opened_to_be_looked_at_starts_nothing() -> None:
    """The control: a manifest value is a standing declaration, not an act of intent."""
    app = Workbench(_session(), launch=_fake_launch())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert app.session.phase is Phase.IDLE


# -- the boundary the worker reports through -------------------------------


def _accepts_presentation(presentation: Presentation) -> None:
    """Structural conformance, enforced by mypy rather than at runtime."""


def test_the_workbench_presentation_satisfies_the_boundary() -> None:
    """ADR-0013 pinned ``Presentation``; this is the terminal's implementation of it."""
    _accepts_presentation(WorkbenchPresentation(Workbench(_session())))


@pytest.mark.asyncio
async def test_every_call_crosses_back_to_the_app_thread() -> None:
    """Textual forbids touching the UI from a worker; nothing here may.

    The double records what it was asked to run rather than running it, so a
    method that reached a widget directly would leave this list short. The
    fault is in the sequence because it crosses through ``_tell`` rather
    than through the presentation, and it is no less a worker's call.
    """
    app = Workbench(_session(), launch=_fake_launch())
    crossings: list[str] = []

    def crossed(callback, *args, **kwargs):  # type: ignore[no-untyped-def]
        crossings.append(callback.__name__)
        return callback(*args, **kwargs)

    async with app.run_test() as pilot:
        app.call_from_thread = crossed  # type: ignore[method-assign]
        presentation = WorkbenchPresentation(app)
        presentation.begin(DRILL_AND_DOCK)
        presentation.update(0.5, ("seat",))
        presentation.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai")
        presentation.report(["read 8 holes"])
        run._tell(app, app.fault, OSError("disk full"))
        await pilot.pause()

    assert crossings == ["show", "advance", "settle", "record", "fault"]


@pytest.mark.asyncio
async def test_a_fault_on_the_worker_reaches_the_main_thread() -> None:
    """A failing run must not come back as a success.

    The fault happens where nothing can print it, so it travels to the app,
    which outlives the run and can show it. The run ends; the app does not.
    """

    def explode(*_args: object, **_kwargs: object) -> NoReturn:
        raise OSError("disk full")

    app = Workbench(_session(), launch=Launch(panel=_PANEL, compose=explode))
    async with app.run_test() as pilot:
        await pilot.press("r", "ctrl+r")
        await _settle(pilot, app)
        assert isinstance(app.failure, OSError)
        assert app.session.phase is Phase.DONE


def _asking(presentation: WorkbenchPresentation, results: list[str]) -> Callable[[], None]:
    """A worker body recording how ``ask`` ended: answered, or abandoned."""

    def body() -> None:
        try:
            results.append(
                presentation.ask(
                    Choice(
                        prompt="reference outline is within tolerance of more than one footprint",
                        candidates=("1590B", "1590B2"),
                        code="ambiguous-enclosure",
                    )
                )
            )
        except Cancelled:
            results.append("cancelled")

    return body


async def _await_result(results: list[str], timeout: float = 5.0) -> None:
    """Poll for the worker's recorded outcome, bounded so a stall fails fast."""

    async def poll() -> None:
        while not results:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=timeout)


@pytest.mark.asyncio
async def test_the_app_going_away_abandons_a_pending_question() -> None:
    """A screen the shutdown popped never calls back; the wait must still end.

    Nothing else ends it: the answer is a keypress, and there is no longer
    anybody to press one, so a worker left waiting would hold a thread for
    as long as the process lived.
    """
    app = Workbench(_session(), launch=_fake_launch())
    results: list[str] = []

    async with app.run_test() as pilot:
        presentation = WorkbenchPresentation(app)
        app.run_worker(_asking(presentation, results), thread=True)
        await _paused(pilot, app)
        assert results == []

        app.exit()
        await _await_result(results)

    assert results == ["cancelled"]
