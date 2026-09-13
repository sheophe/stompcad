"""The run drawn above the prompt, driven through Textual's own pilot."""

from __future__ import annotations

import asyncio
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from stompcad import cli
from stompcad.cancel import Cancelled
from stompcad.drive import RunOptions
from stompcad.inline import InlineApp, TerminalPresentation
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import Choice, PlainWriter, Presentation, Question
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import EXIT_ERRORS, EXIT_WARNINGS
from stompmodel.model import CaseFace
from tests.conftest import TAR_AI

__all__: list[str] = []


def _boardless_panel(tmp_path: Path) -> Path:
    """A private copy of the tar fixture, declared to have no boards.

    Copied rather than read in place: the shared fixture must not gain a
    companion project file every other suite reading it would also see.
    """
    panel = tmp_path / "tar.ai"
    shutil.copy(TAR_AI, panel)
    (tmp_path / "tar.stompcad.json").write_text(
        json.dumps({"version": 1, "boards": {"boards": []}}), encoding="utf-8"
    )
    return panel


class _AlwaysATerminal:
    """Stands in for ``out`` so ``choose_presentation`` picks the inline app."""

    def isatty(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_the_bar_names_the_deepest_live_branch() -> None:
    """Decision 3: the bar level draws one bar and one line for the branch."""
    app = InlineApp()
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.advance(0.25, ("seat", "board 1", "coarse"))
        await pilot.pause()

        assert app.position == pytest.approx(0.25)
        assert "coarse" in app.branch


@pytest.mark.asyncio
async def test_a_settled_step_keeps_the_shared_line_format() -> None:
    """Decision 2: what the terminal settles into is what a pipe receives."""
    app = InlineApp()
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.settle(DRILL_AND_DOCK.steps[1], "8 holes, 2 tools")
        await pilot.pause()

        assert app.settled == ["  quantise        8 holes, 2 tools"]


def _accepts_presentation(presentation: Presentation) -> None:
    """Structural conformance, enforced by mypy rather than at runtime."""


@pytest.mark.asyncio
async def test_the_terminal_presentation_satisfies_the_boundary() -> None:
    """Plan A pinned ``Presentation``; this is the second implementation of it."""
    app = InlineApp()
    _accepts_presentation(TerminalPresentation(app))


@pytest.mark.asyncio
async def test_every_call_crosses_back_to_the_app_thread() -> None:
    """Textual forbids touching the UI from a worker; nothing here may.

    The double records what it was asked to run rather than running it, so a
    method that reached a widget directly would leave this list short.
    """
    app = InlineApp()
    crossings: list[str] = []

    def crossed(callback, *args, **kwargs):  # type: ignore[no-untyped-def]
        crossings.append(callback.__name__)
        return callback(*args, **kwargs)

    async with app.run_test() as pilot:
        app.call_from_thread = crossed  # type: ignore[method-assign]
        presentation = TerminalPresentation(app)
        presentation.begin(DRILL_AND_DOCK)
        presentation.update(0.5, ("seat",))
        presentation.finish_step(DRILL_AND_DOCK.steps[0], "tar.ai")
        presentation.report(["read 8 holes"])
        await pilot.pause()

    assert crossings == ["show", "advance", "settle", "record"]


@pytest.mark.asyncio
async def test_the_worker_runs_the_composed_run_and_its_code_comes_back() -> None:
    """The run happens off the main thread; its exit code leaves through ``exit``."""
    app = InlineApp()
    app.drive(lambda: 7)
    async with app.run_test() as pilot:
        for _ in range(50):
            await pilot.pause()
            if app.return_value is not None:
                break
    assert app.return_value == 7


@pytest.mark.asyncio
async def test_q_asks_the_run_to_stop() -> None:
    """Decision 9: the key sets a flag; the sink is what raises."""
    app = InlineApp()
    async with app.run_test() as pilot:
        assert app.stopping is False
        await pilot.press("q")
        assert app.stopping is True


@pytest.mark.asyncio
async def test_ctrl_q_stops_the_run_rather_than_quitting_the_app() -> None:
    """Textual's own priority ``ctrl+q -> quit`` must not reach the app.

    Left unbound here, ``ctrl+q`` would exit the app while the worker still
    ran: ``app.run()`` would return ``None`` with ``app.failure`` unset, and
    a run that never finished would read as a clean exit. Binding it to
    ``action_stop`` keeps it behind the same flag ``q`` sets.
    """
    app = InlineApp()
    async with app.run_test() as pilot:
        assert app.stopping is False
        await pilot.press("ctrl+q")
        assert app.stopping is True
        assert app.is_running is True
        assert app.return_value is None


def test_the_stop_flag_wired_by_run_cancels_the_composed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves the guard: ``_run`` must wire ``stop=lambda: app.stopping`` in.

    ``InlineApp.run`` is replaced with a stand-in that drives the same app
    through the pilot instead of a real terminal, setting ``stopping``
    before ``on_mount`` starts the worker -- the state ``q`` leaves it in.
    Everything else is ``_run`` itself, unmodified.
    """

    def fake_run(self: InlineApp, **_: object) -> int | None:
        self.stopping = True

        async def drive_via_pilot() -> int | None:
            async with self.run_test() as pilot:
                for _ in range(50):
                    await pilot.pause()
                    if self.return_value is not None:
                        break
            return self.return_value

        return asyncio.run(drive_via_pilot())

    monkeypatch.setattr(InlineApp, "run", fake_run)
    monkeypatch.setenv("TERM", "xterm")
    args = cli.build_parser().parse_args(
        [str(_boardless_panel(tmp_path)), "--case", "1590B", "--emit", f"excellon={tmp_path / 'out.drl'}"]
    )

    with pytest.raises(Cancelled):
        cli._run(args, _AlwaysATerminal())  # type: ignore[arg-type]


def test_an_app_that_fails_under_the_run_is_not_reported_as_a_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Decision 9 reserves 130 for a stop the user asked for.

    An app that exits with no result has not run to a code, but neither has
    anybody pressed ``q``; reporting a stop would put 130 on a path the
    specification says may not produce it, so it earns the processing code.
    """

    def fake_run(self: InlineApp, **_: object) -> int | None:
        return None

    monkeypatch.setattr(InlineApp, "run", fake_run)
    monkeypatch.setenv("TERM", "xterm")
    args = cli.build_parser().parse_args(
        [str(_boardless_panel(tmp_path)), "--case", "1590B", "--emit", f"excellon={tmp_path / 'out.drl'}"]
    )

    assert cli._run(args, _AlwaysATerminal()) == EXIT_ERRORS  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_fault_on_the_worker_reaches_the_main_thread() -> None:
    """A failing run must not come back as a success.

    The fault is raised on the worker, where nothing can print it, so it
    travels out on the app and is raised again where ``main`` can map it.
    """
    app = InlineApp()

    def boom() -> int:
        raise OSError("disk full")

    app.drive(boom)
    async with app.run_test() as pilot:
        for _ in range(50):
            await pilot.pause()
            if app.return_value is not None:
                break

    assert isinstance(app.failure, OSError)


@pytest.mark.asyncio
async def test_v_cycles_the_level_without_disturbing_the_run() -> None:
    """Decision 3: the key redraws in place; it restarts nothing."""
    app = InlineApp(level="bar")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.advance(0.4, ("seat", "board 1"))
        app.settle(DRILL_AND_DOCK.steps[0], "tar.ai")
        await pilot.pause()

        await pilot.press("v")
        assert app.level == "steps"
        await pilot.press("v")
        assert app.level == "tree"
        await pilot.press("v")
        assert app.level == "bar"

        assert app.position == pytest.approx(0.4)
        assert app.settled == ["  read panel      tar.ai"]


@pytest.mark.asyncio
async def test_every_level_renders_the_same_recorded_run() -> None:
    """Each level is a projection of one state, not a separate record."""
    frames = {}
    for level in ("bar", "steps", "tree"):
        app = InlineApp(level=level)
        async with app.run_test() as pilot:
            app.show(DRILL_AND_DOCK)
            app.settle(DRILL_AND_DOCK.steps[0], "tar.ai")
            app.advance(0.4, ("quantise", "hole 3"))
            await pilot.pause()
            frames[level] = app.rendered()

    assert "  read panel      tar.ai" in frames["steps"]
    assert "  read panel      tar.ai" in frames["tree"]
    assert "quantise" in frames["bar"]
    assert "hole 3" in frames["tree"]
    assert "hole 3" not in frames["steps"]


@pytest.mark.asyncio
async def test_the_tree_expands_divisions_and_counts_per_item_leaves() -> None:
    """Decision 3: the divisions a step reports, not its every hole."""
    app = InlineApp(level="tree")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        for hole in range(25):
            app.advance(0.5, ("drill", "route", f"hole {hole}.000,0.000"))
        for phase in ("coarse", "fine", "settle"):
            app.advance(0.6, ("seat", "board 1", phase))
        await pilot.pause()
        drawn = app.rendered()

    assert "    route" in drawn
    assert "25 items" in drawn
    assert "hole 0.000,0.000" not in drawn
    assert "      coarse" in drawn


@pytest.mark.asyncio
async def test_a_question_blocks_the_worker_until_it_is_answered() -> None:
    """``ask`` runs on the worker; the answer arrives from a keypress."""
    app = InlineApp()
    answers: list[str] = []

    async with app.run_test() as pilot:
        presentation = TerminalPresentation(app)
        app.run_worker(
            lambda: answers.append(
                presentation.ask(Choice(prompt="which enclosure?", candidates=("1590B", "1590BB")))
            ),
            thread=True,
        )
        await pilot.pause()
        assert answers == []          # still waiting: nobody has chosen

        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()

    assert answers == ["1590BB"]


def _asking(
    presentation: TerminalPresentation, results: list[tuple[str, str | None]]
) -> Callable[[], None]:
    """A worker body that turns ``ask``'s outcome into one recorded tuple."""

    def run() -> None:
        try:
            results.append(
                ("answer", presentation.ask(Choice(prompt="which enclosure?", candidates=("1590B", "1590BB"))))
            )
        except Cancelled:
            results.append(("cancelled", None))

    return run


async def _await_result(results: list[tuple[str, str | None]], timeout: float = 5.0) -> None:
    """Poll for the worker's recorded outcome, bounded so a stall fails fast."""

    async def poll() -> None:
        while not results:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout=timeout)


@pytest.mark.asyncio
async def test_pressing_q_on_the_modal_abandons_the_question() -> None:
    """``q`` means the same thing everywhere: the modal's own binding stops it."""
    app = InlineApp()
    results: list[tuple[str, str | None]] = []

    async with app.run_test() as pilot:
        presentation = TerminalPresentation(app)
        app.run_worker(_asking(presentation, results), thread=True)
        await pilot.pause()
        assert results == []

        await pilot.press("q")
        await _await_result(results)

    assert results == [("cancelled", None)]


@pytest.mark.asyncio
async def test_the_app_going_away_abandons_a_pending_question() -> None:
    """A screen popped by shutdown never calls back; the wait must still end."""
    app = InlineApp()
    results: list[tuple[str, str | None]] = []

    async with app.run_test() as pilot:
        presentation = TerminalPresentation(app)
        app.run_worker(_asking(presentation, results), thread=True)
        await pilot.pause()
        assert results == []

        app.exit()
        await _await_result(results)

    assert results == [("cancelled", None)]


@pytest.mark.asyncio
async def test_the_settled_lines_are_the_lines_a_pipe_receives() -> None:
    """Decision 2: one presentation serves a terminal and a pipe alike.

    Both are driven with the same calls in the same order, so any divergence
    is a formatting difference between the two writers rather than a
    difference in what the run reported. ``rendered()`` is compared rather
    than ``app.settled`` alone, because the settled frame is what a person
    watching the terminal is left with, and ``report`` is in the driven
    sequence so the provenance lines are part of what must match.
    """
    calls = [
        (DRILL_AND_DOCK.steps[0], "tar.ai, 1590B.stp"),
        (DRILL_AND_DOCK.steps[1], "8 holes, 2 tools"),
        (DRILL_AND_DOCK.steps[2], "7 holes"),
    ]
    report = ["  pitch          1.00 mm, half the drill grid"]

    piped = io.StringIO()
    writer = PlainWriter(piped)
    writer.begin(DRILL_AND_DOCK)
    for step, outcome in calls:
        writer.finish_step(step, outcome)
    writer.report(report)

    app = InlineApp(level="steps")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        for step, outcome in calls:
            app.settle(step, outcome)
        app.record(report)
        app._settle(0)
        await pilot.pause()
        settled = list(app.settled)
        rendered = app.rendered()

    piped_lines = piped.getvalue().splitlines()
    assert settled == piped_lines
    assert rendered == "\n".join(piped_lines)


@pytest.mark.asyncio
async def test_a_settled_run_renders_its_full_record_at_bar_level() -> None:
    """Decision 2: the terminal settles into the record whatever level drew it.

    ``bar`` is the default level, and the one that draws neither the steps
    nor the report line while a run continues -- exactly where fix 2's
    defect hid.
    """
    app = InlineApp(level="bar")
    async with app.run_test() as pilot:
        app.show(DRILL_AND_DOCK)
        app.settle(DRILL_AND_DOCK.steps[0], "tar.ai")
        app.record(["  pitch          1.00 mm, half the drill grid"])
        app._settle(0)
        await pilot.pause()

        rendered = app.rendered()

    assert rendered == "\n".join(app.settled)
    assert "read panel" in rendered
    assert "pitch" in rendered


class _RecordingTerminal(TerminalPresentation):
    """``TerminalPresentation`` keeping the answers it handed back.

    A picker's answer is otherwise invisible from outside the run: the line
    a step settles into names holes and tools, never the part a tie was
    resolved to. Everything else is the real boundary, on the real app.
    """

    def __init__(self, app: InlineApp) -> None:
        super().__init__(app)
        self.answers: list[str] = []

    def ask(self, question: Question) -> str:
        answer = super().ask(question)
        self.answers.append(answer)
        return answer


@pytest.mark.asyncio
async def test_a_tie_is_answered_in_the_terminal_and_the_run_carries_on(
    tmp_path: Path,
) -> None:
    """Decision 6 end to end: the gap asks, the keypress answers, the run finishes.

    The tar fixture ties three parts when no case is declared. The worker
    blocks on the modal, a keypress chooses, and the step runs again under
    the answer -- so the settled record shows one line for it, not two.
    """
    app = InlineApp(level="steps")
    options = RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case=None,
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(),
        panel_reference="RV*",
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=(("excellon", tmp_path / "out.drl"),),
    )
    presentation = _RecordingTerminal(app)
    app.drive(lambda: cli._compose(options, presentation, promote_warnings=False))

    async with app.run_test() as pilot:
        for _ in range(200):
            await pilot.pause()
            if app.screen_stack and app.screen_stack[-1].__class__.__name__ == "ChoiceScreen":
                break
        assert app.screen_stack[-1].__class__.__name__ == "ChoiceScreen"
        await pilot.press("enter")
        for _ in range(400):
            await pilot.pause()
            if app.return_value is not None:
                break

    assert app.failure is None
    # ``enter`` takes the option list's opening highlight, the first
    # candidate the tie recorded; the stage's order is not this test's to pick.
    assert presentation.answers == ["1590BS"]
    # The fixture's two coincident holes warn whichever part resolves the
    # tie, so a run that carried on under the answer earns exactly 1.
    assert app.return_value == EXIT_WARNINGS
    assert (tmp_path / "out.drl").exists()
    quantise_lines = [line for line in app.settled if line.strip().startswith("quantise")]
    assert len(quantise_lines) == 1, app.settled
