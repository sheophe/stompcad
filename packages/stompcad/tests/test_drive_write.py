"""The driver's writing: one transaction over the whole set, not one per path.

CLAUDE.md forbids a second write mechanism and requires ADR-0001's and
ADR-0005's rollback preserved. A bare ``commit()`` loop replaces each target
in turn and leaves the earlier ones replaced when a later one fails, so this
drives a failing commit and asserts what ``commit_all`` alone provides: the
already-replaced target back as it was, and every pending write discarded.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from stompcad.drive import Driver, RunOptions
from stompcad.plan import DRILL_AND_DOCK, RunPlan, Step
from stompmodel.model import DrillData
from stompmodel.progress import track
from tests.conftest import PANEL_REFERENCE, TAR_AI, NullSink

__all__: list[str] = []

_BEFORE = b"the bytes an earlier run left here"


class _SilentPresentation:
    """A presentation that accepts every call and records nothing."""

    def begin(self, plan: RunPlan) -> None:
        return None

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None

    def finish_step(self, step: Step, outcome: str) -> None:
        return None

    def ask(self, question: object) -> str:
        raise AssertionError("a write step must not ask a question of its own")

    def report(self, lines: Sequence[str]) -> None:
        return None


def _options(targets: tuple[tuple[str, Path], ...]) -> RunOptions:
    return RunOptions(
        panel=TAR_AI,
        boards=(),
        case="1590B",
        case_model=None,
        panel_reference=PANEL_REFERENCE,
        targets=targets,
    )


def _fail_the_second_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the second commit of the set fail, and only that one.

    Patched at ``os.replace`` rather than at ``StagedWrite``: the rollback
    restores its target through the same call, so a patch on the staged
    write itself would also disable the mechanism under test. The staging
    step writes its temporaries through ``Path.write_bytes``, so only the
    commits and the rollback reach this.
    """
    real = os.replace
    seen = 0

    def replace(src: object, dst: object) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            raise OSError(errno.EIO, "forced for the transaction guard")
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", replace)


def test_a_failed_commit_restores_the_first_target_and_discards_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three targets, the second unable to commit: the set moves or none does."""
    first, second, third = (tmp_path / "a.json", tmp_path / "b.svg", tmp_path / "c.pdf")
    first.write_bytes(_BEFORE)
    targets = (("json", first), ("drawing-svg", second), ("drawing-pdf", third))
    driver = Driver(DRILL_AND_DOCK, _SilentPresentation(), _options(targets))
    _fail_the_second_replace(monkeypatch)

    with pytest.raises(OSError):
        with track(NullSink()) as scope:
            driver._write_case(DrillData(), scope)

    assert first.read_bytes() == _BEFORE, "the committed target was not put back"
    assert not second.exists()
    assert not third.exists()
    assert [path.name for path in tmp_path.iterdir()] == ["a.json"]
