"""The viewer: an artefact chosen in Output, a path and a mode, nothing coming back."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import pytest
from textual.pilot import Pilot

from stompcad.manifest import DOCK_TARGET_NAMES
from stompcad.settings import Origin, Provenance, Resolved
from stompcad.workbench.app import Workbench
from stompcad.workbench.places import OutputRow
from stompcad.workbench.session import Session
from stompcad.workbench.window import (
    UNVIEWABLE,
    VIEWS,
    NullWindow,
    ViewMode,
    ViewRequest,
    Window,
    view_mode_for,
)
from stompdrill.emitters import available

from .projects import runnable, session

__all__: list[str] = []


class _Opened:
    """A window that records what it was handed, and answers nothing."""

    def __init__(self) -> None:
        self.requests: list[ViewRequest] = []
        self.closed = 0

    def available(self) -> bool:
        return True

    def open(self, request: ViewRequest) -> None:
        self.requests.append(request)

    def close_all(self) -> None:
        self.closed += 1


class _Raising:
    """A window that answers available and then breaks its promise not to raise."""

    def available(self) -> bool:
        return True

    def open(self, request: ViewRequest) -> None:
        raise OSError("no display connection")

    def close_all(self) -> None:
        return None


def _with_outputs(tmp_path: Path, *kinds: str, written: bool = True) -> Session:
    """A project making these artefacts, on disk or not, at real paths."""
    made: list[tuple[str, Path]] = []
    for kind in kinds:
        path = tmp_path / f"tar-{kind}.out"
        if written:
            path.write_bytes(b"written")
        made.append((kind, path))
    project = runnable()
    targets: Resolved[tuple[tuple[str, Path], ...]] = Resolved(
        tuple(made), Provenance(Origin.PROJECT)
    )
    return session(settings=replace(project, output=replace(project.output, targets=targets)))


async def _focus_the_artefact(pilot: Pilot[int]) -> None:
    """Go to Output and move below the row that names the artefacts, onto the first."""
    await pilot.press("o")
    await pilot.press("down")


def test_the_null_window_is_unavailable_and_does_nothing() -> None:
    window = NullWindow()
    assert window.available() is False
    window.open(ViewRequest(Path("/project/tar.drl"), ViewMode.DRAWING, "tar"))
    window.close_all()


def test_the_null_window_satisfies_the_protocol() -> None:
    def accepts(window: Window) -> None:
        return None

    accepts(NullWindow())


def test_a_request_carries_no_geometry() -> None:
    """A control on the field list: a shape or a document added "for the viewer"
    is how the no-geometry rule would be lost, one convenience at a time."""
    assert {field.name for field in fields(ViewRequest)} == {"path", "mode", "title", "highlight"}


def test_every_artefact_has_a_view_or_is_only_listed() -> None:
    """A new emitter must be given a mode or named listed-only, never forgotten."""
    kinds = set(available()) | set(DOCK_TARGET_NAMES)
    assert kinds == set(VIEWS) | UNVIEWABLE
    assert not set(VIEWS) & UNVIEWABLE
    assert view_mode_for("report") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "mode"), [("excellon", ViewMode.DRAWING), ("step", ViewMode.MODEL)])
async def test_enter_on_a_written_artefact_opens_the_viewer_on_it(
    tmp_path: Path, kind: str, mode: ViewMode
) -> None:
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, kind), window=window)
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        await pilot.press("enter")
    (request,) = window.requests
    assert request.path == tmp_path / f"tar-{kind}.out"
    assert request.mode is mode


@pytest.mark.asyncio
async def test_nothing_opens_by_itself(tmp_path: Path) -> None:
    """The user's rule: moving through every place, onto the artefact and off it,
    opens nothing. Only enter on the row does."""
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, "excellon"), window=window)
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        for key in ("up", "down", "f", "o", "a", "r", "p"):
            await pilot.press(key)
    assert window.requests == []


@pytest.mark.asyncio
async def test_an_unwritten_artefact_says_so(tmp_path: Path) -> None:
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, "excellon", written=False), window=window)
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        await pilot.press("enter")
        assert "not been written" in app.message
    assert window.requests == []


@pytest.mark.asyncio
async def test_the_report_is_listed_but_is_not_a_row(tmp_path: Path) -> None:
    """The user's decision: the report is named in Output and never offered to
    the viewer, so enter cannot land on it."""
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, "excellon", "report"), window=window)
    async with app.run_test() as pilot:
        await pilot.press("o")
        assert "tar-report.out" in app.pane_text()
        assert [row.kind for row in app.query(OutputRow)] == ["excellon"]
    assert window.requests == []


@pytest.mark.asyncio
async def test_w_views_the_focused_artefact_and_otherwise_says_where_to_go(
    tmp_path: Path,
) -> None:
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, "excellon"), window=window)
    async with app.run_test() as pilot:
        await pilot.press("w")
        assert "Output" in app.message and "viewer" in app.message
        assert window.requests == []
        await _focus_the_artefact(pilot)
        await pilot.press("w")
    assert len(window.requests) == 1


@pytest.mark.asyncio
async def test_no_viewer_is_explained_rather_than_raised(tmp_path: Path) -> None:
    app = Workbench(_with_outputs(tmp_path, "excellon"), window=NullWindow())
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        await pilot.press("enter")
        assert "no viewer" in app.message
        assert app.is_running


@pytest.mark.asyncio
async def test_a_viewer_that_raises_is_caught_and_named(tmp_path: Path) -> None:
    """The contract says `open` never raises; a viewer that does is the
    viewer's failure, reported by name, not the workbench's crash."""
    app = Workbench(_with_outputs(tmp_path, "excellon"), window=_Raising())
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        await pilot.press("enter")
        assert "no display connection" in app.message
        assert app.is_running


@pytest.mark.asyncio
async def test_quitting_closes_what_was_opened(tmp_path: Path) -> None:
    window = _Opened()
    app = Workbench(_with_outputs(tmp_path, "excellon"), window=window)
    async with app.run_test() as pilot:
        await _focus_the_artefact(pilot)
        await pilot.press("enter")
    assert len(window.requests) == 1
    assert window.closed == 1
