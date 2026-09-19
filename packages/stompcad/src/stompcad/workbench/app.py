"""The workbench: eight places on one screen, and the keys that move them.

Spec decisions 1, 3, 4, 5 and 14. Every rule lives in ``Session``; this is
drawing and dispatch. Bindings are built from ``keys``, so the table proved
distinct is the table the application answers. A run is an event here rather
than the app's exit, so starting it, stopping it and quitting are three acts.

No bare letter is a priority binding: an open text field consumes a printable
key before any binding is checked. The stop is, because it must outrank a modal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from rich.cells import cell_len
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Input, Static, TextArea

from stompmodel.diagnostics import EXIT_ERRORS, Diagnostic
from stompmodel.errors import StompError
from stompmodel.model import CaseFace

from .. import discover
from ..cancel import EXIT_CANCELLED
from ..plan import RunPlan, Step
from ..present import step_line
from .dialog import Dialog
from .footer import MOVING, TYPING, Mode, ModeLine
from .keys import (
    GLOBAL_VERBS,
    LOCAL_KEYS,
    PLACE_KEYS,
    RUN_KEYS,
    SIDEBAR_KEYS,
    STEP_KEYS,
    TO_SIDEBAR,
    Place,
)
from .places import (
    Editor,
    Field,
    FocusRow,
    GapRow,
    Kind,
    PickerScreen,
    RunView,
    ValueRow,
    choices_for,
    chosen_for,
    field_of,
    label_of,
    pane_for,
    position_line,
    table_bindings,
)
from .run import Launch, may_resume, start
from .runner import ProcessRunner, Runner
from .session import Locked, PendingGap, Phase, Refused, Session
from .sidebar import Sidebar
from .theme import shades

__all__ = ["Workbench", "KeysScreen", "ConfirmScreen"]

_multiprocessing_primed = False


def _prime_multiprocessing() -> None:
    """Start multiprocessing's resource tracker before Textual owns stderr.

    A first ``spawn`` synchronisation primitive starts that tracker, which
    reads ``sys.stderr.fileno()`` to launch itself. Textual's redirect
    answers that call with an invalid descriptor for as long as an app is
    running, so priming here, before the app takes the terminal, keeps a
    run's first spawn from failing. Cheap to call again, so every
    workbench may call it.
    """
    global _multiprocessing_primed
    if _multiprocessing_primed:
        return
    get_context("spawn").Lock()
    _multiprocessing_primed = True


class Workbench(App[int], inherit_bindings=False):
    """The project open, full screen. ``run`` hands back the exit code it earned.

    Textual's own chords are not inherited: its priority ``ctrl+q`` would quit
    without the session's exit code, and the palette's ``ctrl+p`` would answer
    in every place. Neither is in the table decision 3 proves distinct.
    """

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #body { width: 1fr; padding: 0 1; }
    """

    BINDINGS = [
        *table_bindings(),
        *(Binding(key, "focus_sidebar", detail, show=False) for key, detail in TO_SIDEBAR.items()),
    ]

    message: reactive[str] = reactive("")

    def get_css_variables(self) -> dict[str, str]:
        """Textual's own variables, plus the two selection shades.

        Given to the stylesheet rather than written into each widget, so
        the sidebar and a place cannot come to mark the same state two
        different ways -- which is exactly what they had done.
        """
        variables = super().get_css_variables()
        return {**variables, **shades(variables["accent"])}

    def __init__(
        self,
        session: Session,
        launch: Launch | None = None,
        autostart: bool = False,
        cache: Path | None = None,
        runner: Runner | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.launch = launch
        # Where cached enclosure models live. ``None`` asks the tool that
        # owns that location at the press rather than here, because it is a
        # repository script and an app installed elsewhere has no such tool.
        self.cache = cache
        self.runner: Runner = runner or ProcessRunner()
        _prime_multiprocessing()
        # Decision 1: an invocation carrying something beyond the panel means
        # "do not ask me", so the app opens with the run already moving. A
        # manifest value is a standing declaration and starts nothing, or
        # opening last week's project to look at it would cost kernel work.
        self.autostart = autostart
        self._base: Screen[Any] | None = None
        # What the run leaves behind, in the form a pipe would have received
        # it (decision 15), plus where the run stands while it is working.
        self.plan: RunPlan | None = None
        self.settled: list[str] = []
        self.reports: list[str] = []
        self.outcomes: dict[str, str] = {}
        self.position = 0.0
        self.branch = ""
        # That a stop was asked for this run, which is not the same as the
        # run having heard one: the runner is asked as well, and only the
        # ask reaches the process. Cleared as each run starts.
        self.stopping = False
        self.failure: BaseException | None = None
        # What outlives one run: a driver in the run's own process, which
        # the next `Ctrl+R` spends, and whether this run is that. The app
        # holds no driver -- it holds the fact that one exists.
        self.composed = False
        self.resuming = False
        # One worker carries events in for the app's whole life, started
        # with the first run rather than at open, because the runner has
        # no process to listen to until then.
        self.listening = False
        # What a paused run is waiting on: the number of the question the
        # runner has open, held only while a gap is unanswered.
        self._asked = 0

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Sidebar()
            yield Vertical(id="body")
        yield ModeLine()

    async def on_mount(self) -> None:
        self._base = self.screen
        await self.redraw()
        if self.autostart and self.session.may_run():
            self.action_start_run()

    def on_unmount(self) -> None:
        """The run's process is asked to go, and waited for if it is writing."""
        self.runner.close()

    # -- drawing -----------------------------------------------------------

    def mode(self) -> Mode:
        """Which mode is in force. Decision 3's one hazard, closed."""
        focused = self.focused
        typing = focused is not None and focused.can_focus and _is_text(focused)
        return TYPING if typing else MOVING

    async def redraw(self, field: str | None = None) -> None:
        """Draw the sidebar, the current place and the mode line.

        Drawn on the base screen, which a picker may still be covering. The
        old pane's removal is awaited first, since both carry one id when the
        place is unchanged. A run reports through ``call_later``, so one can
        arrive after the app has begun tearing its widgets down; there is
        nothing left to draw on. Focus lands on ``field``'s row, else a
        pending gap's, else the first -- unless the sidebar holds focus, where
        a step through the places leaves it.
        """
        if not self.is_running:
            return
        base = self._base if self._base is not None else self.screen
        body = next(iter(base.query("#body").results(Vertical)), None)
        if body is None or not _mounted(body):
            return
        base.query_one(Sidebar).show(self.session.rows())
        # Read before the old pane goes: removing a focused row hands focus to
        # the next focusable widget, which is the sidebar.
        in_sidebar = isinstance(self.focused, Sidebar)
        await body.remove_children()
        if not _mounted(body):
            return  # the app went during the await; there is nothing to mount into
        await body.mount(pane_for(self.session, self.session.place, self._run_view()))
        target = _entry_row(body, field)
        if not in_sidebar:
            if target is not None:
                target.focus()
            else:
                base.set_focus(None)  # a place with nothing to select holds no focus
        self._show_mode()

    def _run_view(self) -> RunView:
        """The whole step list, live, and what the run reported besides it.

        Built from the plan rather than from ``settled``, so a step still to
        come is listed beside the ones already done; ``settled`` stays the
        record in the order a pipe receives it, which decision 15 compares.
        """
        width = self._label_width()
        steps = () if self.plan is None else tuple(
            step_line(step.label, self.outcomes.get(step.key, ""), width).rstrip()
            for step in self.plan.steps
        )
        return RunView(steps, tuple(self.reports), self.position, self.branch)

    def _refresh(self) -> None:
        """Schedule a redraw from a method the worker crossed into.

        ``redraw`` remounts the pane and so must be awaited; the run reports
        from a thread and cannot await anything, so the app's own loop takes
        it from here.
        """
        self.call_later(self.redraw)

    def redraw_run(self) -> None:
        """Update the live line alone. A full redraw per leaf would move focus."""
        if not self.is_running:
            return
        base = self._base if self._base is not None else self.screen
        for line in base.query("#run-position").results(Static):
            line.update(position_line(self.position, self.branch))

    def _show_mode(self) -> None:
        if self._base is not None and self.is_running:
            self._base.query_one(ModeLine).show(self.mode(), self.message)

    def watch_message(self) -> None:
        self._show_mode()

    def on_descendant_focus(self, _event: events.DescendantFocus) -> None:
        """The footer follows focus, because focus is what decides the mode."""
        self._show_mode()

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self._show_mode()

    def sidebar_text(self) -> str:
        """Every sidebar row as one string. For tests, and for nothing else."""
        return "\n".join(
            str(row.content) for row in self.query_one(Sidebar).query(Static)
        )

    def pane_text(self) -> str:
        """Every line the current place draws, as one string. For tests alone."""
        return "\n".join(
            str(line.content) for line in self.query_one("#body", Vertical).query(Static)
        )

    # -- moving ------------------------------------------------------------

    async def action_go(self, place: str) -> None:
        self._leave_modal()
        self.session.go(Place(place))
        self.message = ""
        await self.redraw()

    async def action_step_place(self, forward: bool) -> None:
        self._leave_modal()
        self.session.step_place(forward)
        self.message = ""
        await self.redraw()

    def _leave_modal(self) -> None:
        """Decision 12: a picker is transient, so leaving closes it uncommitted.

        The keys screen closes the same way: a place letter pressed over it
        means what it means anywhere else, and leaving the help open behind
        the place it moved to would be a second state to get out of.
        """
        if isinstance(self.screen, (PickerScreen, KeysScreen)):
            self.pop_screen()

    def action_focus_sidebar(self) -> None:
        """`←`: leave the place for the list, keeping the place where it is."""
        base = self._base if self._base is not None else self.screen
        base.query_one(Sidebar).focus()

    def action_enter_place(self) -> None:
        """`→` or `enter` in the list: into the place, onto the row a letter lands on."""
        base = self._base if self._base is not None else self.screen
        target = _entry_row(base.query_one("#body", Vertical), None)
        if target is not None:
            target.focus()

    async def on_sidebar_chosen(self, event: Sidebar.Chosen) -> None:
        """A click goes to the place and into it, as a letter does."""
        await self.action_go(event.place.value)
        self.action_enter_place()

    # -- changing ----------------------------------------------------------

    async def on_value_row_edit(self, event: ValueRow.Edit) -> None:
        """`enter` on a row: a field for text, a picker for a list."""
        if not self.session.may_edit(event.place):
            self.message = "nothing is editable while a run is working"
            return
        field = field_of(event.place, event.field)
        if self._picks(field):
            self._open_picker(event.place, field)
            return
        base = self._base if self._base is not None else self.screen
        await base.query(Editor).remove()
        editor = Editor(event.row)
        editor.placeholder = str(event.row.content)
        pane = event.row.parent
        assert isinstance(pane, Widget)
        await pane.mount(editor, after=event.row)
        editor.focus()

    def _picks(self, field: Field) -> bool:
        """Whether `enter` here opens a list rather than a field. Decision 3.

        Two rows carry answers only sometimes, so neither is decided by its
        kind: the panel is a typed path until the directory offers
        candidates, and a board's designators arrive with the run that reads
        it. Everything else is a list wherever the tool that owns it has one.
        """
        if field.name == "panel":
            return bool(self.session.panel_candidates)
        if field.name == "panel_reference":
            return bool(self.session.designators)
        return field.kind in (Kind.CHOICE, Kind.MANY)

    def _open_picker(self, place: Place, field: Field) -> None:
        """Offer the owning tool's answers, or say why there are none to offer."""
        try:
            choices = choices_for(self.session, place, field.name)
        except (StompError, OSError) as failure:
            self.message = str(failure)
            return
        if field.kind is Kind.CHOICE and not choices:
            self.message = f"there is nothing to choose from for {field.name.replace('_', ' ')}"
            return
        picker = PickerScreen(
            field,
            choices,
            multiple=field.kind is Kind.MANY,
            label=label_of(self.session, place, field.name),
            chosen=chosen_for(self.session, place, field.name),
        )
        self.push_screen(picker, lambda answer: self._picked(place, field, answer))

    def _picked(self, place: Place, field: Field, answer: object) -> None:
        """A picker's answer, or ``None`` when `escape` abandoned it."""
        if answer is None:
            return
        self._commit(place, field.name, answer)
        self.call_later(self.redraw, field.name)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        editor = event.input
        if not isinstance(editor, Editor):
            return
        self._commit(editor.row.place, editor.row.field, event.value)
        await self.redraw(editor.row.field)

    def _commit(self, place: Place, field: str, answer: object) -> None:
        """Convert, then hand the value over; a refusal is shown, never taken.

        A panel is not one value of a project: it *is* the project, so that
        row starts one rather than setting a field. Decision 6's blocked
        start is only usable because of this.
        """
        try:
            value = _as_value(self.session, place, field, answer)
            if place is Place.ARTWORK and field == "panel":
                self._adopt_panel(value)
            else:
                self.session.set(place, field, value)
        except (Refused, Locked, ValueError, StompError, OSError) as failure:
            self.message = str(failure)
            return
        self.message = ""

    def _adopt_panel(self, value: object) -> None:
        """Resolve the project this path names, and aim the run at it.

        The launch follows the panel because a workbench opened without one
        has no project to run: leaving it behind would resolve a project the
        run row still could not start.
        """
        if not isinstance(value, Path):
            raise ValueError("artwork.panel: name the artwork file to read")
        self.session.adopt_panel(value)
        self.launch = (
            Launch(panel=value) if self.launch is None else replace(self.launch, panel=value)
        )

    # -- the run -----------------------------------------------------------

    def show(self, plan: RunPlan) -> None:
        """The plan the run intends to take, which may be less than the whole."""
        self.plan = plan
        self.session.begin_run(
            frozenset(step.key for step in plan.steps), fresh=not self.resuming
        )
        self._refresh()

    def advance(self, position: float, path: tuple[str, ...]) -> None:
        self.position = position
        self.branch = " / ".join(path)
        self.redraw_run()

    def settle(self, step: Step, outcome: str) -> None:
        """Keep the finished line in the form a pipe would have received."""
        self.settled.append(step_line(step.label, outcome, self._label_width()))
        self.outcomes[step.key] = outcome
        self.session.credit(step.key)
        self._refresh()

    def record(self, lines: list[str]) -> None:
        """What a write step said, kept in two places on purpose.

        ``settled`` is the record in the order a pipe receives it, step
        lines and reports interleaved; ``reports`` is the part the `Run`
        place draws beneath a step list it builds from the plan.
        """
        self.settled.extend(lines)
        self.reports.extend(lines)
        self._refresh()

    def completed(
        self,
        code: int,
        diagnostics: Sequence[Diagnostic] | None,
        written: Sequence[Path],
        designators: Mapping[int, tuple[str, ...]],
    ) -> None:
        """The run ended. Its code is the app's until another run earns one."""
        self.session.finish_run(code)
        if diagnostics is not None:
            self.session.record_findings(diagnostics)
        self.session.record_written(written)
        self.session.record_designators(designators)
        self._refresh()

    def fault(self, failure: BaseException) -> None:
        """A run that broke. The app stays; the run does not."""
        self.failure = failure
        self.session.finish_run(EXIT_ERRORS)
        self.message = f"the run failed: {failure}"
        self._refresh()

    def _label_width(self) -> int:
        """The column a step's label is padded into, from the plan the run declared.

        Decision 15: these lines are byte-compared against the same run
        piped, and ``PlainWriter`` pads from the plan it was given in
        ``begin``. Deriving the width any other way is how the two diverge.
        """
        if self.plan is None:
            return 0
        return max((len(step.label) for step in self.plan.steps), default=0)

    def action_start_run(self) -> None:
        """`Ctrl+R` on the Run place, and `enter` on Project's run row."""
        if self.session.phase is Phase.RUNNING:
            self.message = "a run is already working"
            return
        if not self.session.may_run():
            self.message = self.session.statement()
            return
        if self.launch is None:
            self.message = "no project is open"
            return
        self.resuming = may_resume(self)
        self.plan = self.launch.plan
        self.settled = []
        self.reports = []
        self.outcomes = {}
        self.position = 0.0
        self.branch = ""
        self.failure = None
        self.message = ""
        # Decision 5 binds from the keypress, not from the worker's first
        # crossing: a window in which a place still accepts an edit is a
        # window in which a value can change under work already under way.
        self.session.start_run(self.resuming)
        try:
            start(self)
        except Exception as failure:  # noqa: BLE001 - shown, not raised
            # Decision 1: a process that will not start is this run's
            # failure, not the workbench's. Letting it out of an action
            # tears the application down and costs the user the session
            # they opened to look at a project.
            self.fault(failure)
            return
        self._refresh()

    def action_stop_run(self) -> None:
        """Ask the run to stop; it is heard at its next reported leaf."""
        if self.session.phase in (Phase.RUNNING, Phase.PAUSED):
            self.stopping = True
            self.runner.stop()
            self.message = "stopping…"

    def enquire(self, asked: int, gap: PendingGap) -> None:
        """Stop for this gap and go to the place that answers it. Decision 12."""
        self.session.pause(gap)
        # Which question is open, so an answer can name it. An answer that
        # arrives for a question already closed is stale, and a boundary
        # delays everything, so the run needs to be able to tell.
        self._asked = asked
        self._refresh()
        self._open_gap_picker()

    def _open_gap_picker(self) -> None:
        """Offer the gap's own candidates, named as the continuation they are."""
        gap = self.session.gap
        if gap is None or gap.choice is None:
            return
        self.push_screen(
            PickerScreen(
                None,
                gap.choice.candidates,
                multiple=gap.choice.multiple,
                label="Use this and continue",
            ),
            self._answered,
        )

    def _answered(self, answer: object | None) -> None:
        """Committing the answer *is* the continuation -- no second action.

        ``None`` is a picker abandoned, and so is a multiple one committed
        with nothing ticked: the workbench specification's decision 11
        forbids substituting an answer the tool did not compute, and an
        empty one revises a field into something no step can read. Both
        leave the run paused, with the gap's own row to reopen the picker.
        """
        if answer is None or self.session.gap is None:
            return
        ticked = _many(answer) if isinstance(answer, tuple) else (str(answer),)
        if not ticked:
            return
        self._resume(",".join(ticked))

    def action_answer_gap(self) -> None:
        """`enter` on the paused place's own row: its picker, or the continuation."""
        gap = self.session.gap
        if gap is None:
            return
        if gap.choice is None:
            self.action_continue_run()
            return
        self._open_gap_picker()

    def action_continue_run(self) -> None:
        """The focused row a place answering by a free edit gains."""
        if self.session.gap is None:
            return
        self._resume("")

    def _resume(self, answer: str) -> None:
        """Let the waiting run go again, once the session says it is running.

        The session is told first and the run second: the answer crosses a
        boundary, so the run goes again at a moment this side does not
        choose, and a place still read-only when it does is a place the
        user was locked out of for no reason.
        """
        self.session.resumed()
        self._refresh()
        self.runner.answer(self._asked, answer)

    def action_escape(self) -> None:
        """The ladder, innermost first: a modal, an editor, then the run itself."""
        if isinstance(self.screen, (PickerScreen, KeysScreen)):
            self.pop_screen()
            return
        if self._editors():
            self._close_editor()
            return
        if self.session.phase is Phase.PAUSED and self.session.gap is not None:
            self.action_stop_run()
            return
        if self.session.place is Place.RUN:
            self.action_stop_run()

    def _editors(self) -> list[Editor]:
        base = self._base if self._base is not None else self.screen
        return list(base.query(Editor))

    def _close_editor(self) -> None:
        for editor in self._editors():
            editor.action_close()

    # -- the verbs ---------------------------------------------------------

    def action_verb(self, verb: str) -> None:
        if verb == "window":
            self.action_window()
        elif verb == "keys":
            self.action_keys()
        else:
            self._quit()

    def _quit(self) -> None:
        """Decision 14: `q` quits, stopping any run first and confirming during one.

        Quitting and stopping are different acts once the app outlives the
        run, so throwing minutes of kernel work away takes an answer rather
        than one key.
        """
        if self.session.phase in (Phase.RUNNING, Phase.PAUSED):
            self.push_screen(ConfirmScreen(), self._quit_confirmed)
            return
        self.exit(self.session.exit_code)

    def _quit_confirmed(self, leave: bool | None) -> None:
        """Decision 14: the answer decides, not the moment the question was asked.

        A run can finish while the dialog is open, and one that finished
        earned its own code -- a stop may end a run but never change what a
        completed run produced. Only a run still in flight exits 130; with
        no run at all ``exit_code`` has never moved from 0.
        """
        if not leave:
            return
        if self.session.phase in (Phase.RUNNING, Phase.PAUSED):
            self.action_stop_run()
            self.exit(EXIT_CANCELLED)
            return
        self.exit(self.session.exit_code)

    def action_window(self) -> None:
        """Open the viewer on the current subject.

        Decision 13: ``available()`` false means ``w`` explains why rather
        than failing, and the default implementation is the null one -- so
        the whole workbench ships, runs and passes its suite with no window
        in existence. Plan 4 replaces this body with ``Window.open``.
        """
        self.message = "no viewer is installed, so there is nothing to open"

    def action_keys(self) -> None:
        self.push_screen(KeysScreen())

    def action_local(self, key: str) -> None:
        """A place's own key: its owner's action here, and a refusal anywhere else."""
        owner, detail = LOCAL_KEYS[key]
        if self.session.place is not owner:
            self.message = f"{key} belongs to {owner.value.capitalize()} ({detail})"
        elif key == "ctrl+l":
            self.action_reread_artwork()
        elif key == "ctrl+f":
            self.action_find_model()
        else:
            self.action_start_run()

    def action_reread_artwork(self) -> None:
        """`Ctrl+L`: the artwork changed on disk, so read it again.

        Marks the panel changed, which makes ``read panel`` stale and every
        step consuming what it produced with it. Nothing is re-read here:
        the run is what reads artwork, and this says that it must.
        """
        panel = self.session.settings.artwork.panel.value
        if panel is None:
            self.message = "no artwork is selected"
            return
        try:
            self.session.invalidate(Place.ARTWORK, "panel")
        except Locked as failure:
            self.message = str(failure)
            return
        self.message = f"{panel.name} will be read again on the next run"
        self._refresh()

    def action_find_model(self) -> None:
        """`Ctrl+F`: look in the cache for this part's model. Never downloads.

        CLAUDE.md keeps model acquisition in ``tools/fetch_case_model.py``,
        so this asks the cache what it already holds and names that tool
        where it holds nothing. A workbench that fetched would be a
        workbench that acquires models, which is somebody else's decision.
        """
        part = self.session.settings.enclosure.case.value
        if part is None:
            self.message = "name the enclosure part first, so there is something to look for"
            return
        cache = self._cache()
        if cache is None:
            self.message = "no cache location is known; tools/fetch_case_model.py owns one"
            return
        found = discover.cached_model(part, cache)
        if found is None:
            self.message = f"no cached model for {part}; tools/fetch_case_model.py acquires one"
            return
        try:
            self.session.adopt(Place.ENCLOSURE, "case_model", found)
        except (Refused, Locked) as failure:
            # The same two a row's own edit shows rather than takes: a run
            # holds the place, or the tool that consumes the model says no.
            self.message = str(failure)
            return
        self.message = f"using {found.value.name}, {found.detail}"
        self._refresh()

    def _cache(self) -> Path | None:
        """Where cached models live, or ``None`` when nothing here knows.

        ``tools/fetch_case_model.py`` owns that location and is a repository
        script rather than an installed package, so it is asked for at the
        press: an app that cannot import it knows no location, which is not
        the same as an app that failed to start.
        """
        if self.cache is not None:
            return self.cache
        try:
            from tools.fetch_case_model import cache_dir
        except ImportError:
            return None
        return cache_dir()


#: Rows whose empty answer means "not given" rather than an empty string.
_OPTIONAL = frozenset({
    "case", "case_model", "grid_warn_mm", "drill_sizes", "no_drill_sizes", "match_tolerance_mm",
})


def _as_value(session: Session, place: Place, field: str, answer: object) -> object:
    """What an editor or picker handed back, as the value ``Settings`` carries.

    Every conversion is here, keyed by the row's kind, so kinds and
    conversions are one statement. Targets are paired and sorted by format
    name -- the manifest's own order -- so an edit never disagrees with its
    own spelling. Whether a value is *acceptable* is the tool's question.
    """
    if field == "targets":
        panel = session.settings.artwork.panel.value
        if panel is None:
            raise ValueError("output.targets: no artwork is selected, so no artefact has a place")
        names = sorted(str(name) for name in _many(answer))
        return tuple((name, discover.output_path(name, panel)) for name in names)
    if field == "boards":
        return tuple(Path(str(path)) for path in _many(answer))
    if field == "panel_reference":
        return answer.strip() if isinstance(answer, str) else ",".join(_many(answer))
    if field == "case_face":
        return CaseFace(str(answer))
    text = str(answer).strip()
    if not text and field in _OPTIONAL:
        return None
    kind = field_of(place, field).kind
    if kind is Kind.NUMBER:
        try:
            return int(text) if field == "form_depth" else float(text)
        except ValueError:
            whole = "a whole number" if field == "form_depth" else "a number"
            raise ValueError(f"{place.value}.{field}: {text!r} is not {whole}") from None
    if kind is Kind.PATH:
        return Path(text) if text else None
    return text


def _many(answer: object) -> tuple[str, ...]:
    """A multiple picker's ticks, as strings in the order they arrived."""
    return tuple(str(item) for item in answer) if isinstance(answer, (tuple, list)) else ()


def _is_text(widget: object) -> bool:
    """Whether this widget is an open text field, which is what suppresses letters."""
    return isinstance(widget, (Input, TextArea))


def _mounted(widget: Widget) -> bool:
    """Whether this widget can still be mounted into, asked afresh each time.

    ``Widget.mount`` refuses a node that is not attached to the app through
    the DOM, and an app on its way out detaches every node it has, so that
    is the question this must ask. A call rather than the attribute: what
    was true before an ``await`` is not what the next line is asking about,
    and a reader that keeps the first answer -- mypy's ``warn_unreachable``
    does -- calls the second check dead code.
    """
    return widget.is_attached


#: The blank rows and columns between the keys window's border and its text.
_KEYS_MARGIN: tuple[int, int] = (1, 2)


class KeysScreen(ModalScreen[None]):
    """What `?` shows: the same table the bindings were built from.

    A modal screen hides the application's bindings, so this one carries
    the same table as well as its own two closes: decision 3 needs every
    bare letter to work while the help is open, exactly as it does over a
    picker. Its own `escape` and `?` are listed first, so both close it.
    Drawn as a window over the place, like the picker, so the help never
    hides what it is helping with.
    """

    DEFAULT_CSS = """
    KeysScreen { align: center middle; }
    KeysScreen > Dialog {
        max-width: 100%; max-height: 100%; overflow: auto auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "close", show=False),
        Binding("question_mark", "dismiss", "close", show=False),
        *table_bindings("app."),
    ]

    def compose(self) -> ComposeResult:
        text = _key_list()
        lines = text.splitlines()
        width = max(cell_len(line) for line in lines)
        height = len(lines)
        rows, columns = _KEYS_MARGIN
        with Dialog("Keys", id="keys") as window:
            window.styles.padding = (rows, columns)
            # Sized from the text rather than left to `auto`: an auto-sized
            # container around an auto-sized text collapses to its border.
            window.styles.width = width + 2 * (columns + 1)
            window.styles.height = height + 2 * (rows + 1)
            key_list = Static(text, id="key-list", markup=False)
            key_list.styles.width = width
            key_list.styles.height = height
            yield key_list


class ConfirmScreen(ModalScreen[bool]):
    """A yes or no over the app: `enter` leaves, `esc` stays.

    No bare letter is claimed, because every one of them belongs to a place
    and a question is not a place. `Ctrl+C` is bound with priority and so
    still stops the run from here.
    """

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Dialog { width: 52; height: auto; padding: 0 1; }
    """

    BINDINGS = [
        Binding("enter", "leave", "quit", show=False),
        Binding("escape", "stay", "stay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Dialog("Quit", id="confirm"):
            yield Static("A run is working. Quit anyway?", markup=False)
            yield Static("enter — stop it and quit     esc — stay", markup=False)

    def action_leave(self) -> None:
        self.dismiss(True)

    def action_stay(self) -> None:
        self.dismiss(False)


#: How the keys screen spells an arrow; every other key is shown as it is named.
_GLYPHS: dict[str, str] = {"left": "←", "right": "→", "up": "↑", "down": "↓"}


def _entry_row(body: Vertical, field: str | None) -> FocusRow | None:
    """The row focus lands on entering a place: ``field``'s, a gap's, else the first."""
    rows = list(body.query(FocusRow))
    target = next((row for row in rows if row.field == field), None) if field else None
    if target is None:
        target = next(
            (row for row in rows if isinstance(row, GapRow)), rows[0] if rows else None
        )
    return target


def _key_list() -> str:
    """Every key and what it does, read from the tables rather than restated."""
    lines = ["Places"]
    lines += [f"  {key}   {place.value.capitalize()}" for key, place in PLACE_KEYS.items()]
    lines += ["", "Anywhere"]
    lines += [
        f"  {key.replace('question_mark', '?')}   {verb}" for key, verb in GLOBAL_VERBS.items()
    ]
    lines += [f"  {key}   {detail}" for key, (_action, detail) in RUN_KEYS.items()]
    lines += [f"  {STEP_KEYS[0]}   previous place", f"  {STEP_KEYS[1]}   next place"]
    lines += ["", "Moving between the list and the place"]
    lines += [f"  {_GLYPHS.get(key, key)}   {detail}" for key, detail in TO_SIDEBAR.items()]
    lines += [
        f"  {_GLYPHS.get(key, key)}   {detail}" for key, (_action, detail) in SIDEBAR_KEYS.items()
    ]
    lines += ["", "In a place"]
    lines += [
        f"  {key}   {detail} ({owner.value.capitalize()})"
        for key, (owner, detail) in LOCAL_KEYS.items()
    ]
    return "\n".join(lines)
