"""The generic pipeline contracts, exercised on a value that is not DrillData."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pytest

from stompmodel.diagnostics import (
    EXIT_ERRORS,
    Diagnostic,
    Severity,
    exit_for_severity,
    of_severity,
    worst_severity,
)
from stompmodel.model import DrillData, StageRun
from stompmodel.protocols import Diagnosable, Pipeline, Processable, Stage, write_payload


@dataclass(frozen=True, slots=True)
class Counter:
    """A minimal Processable: anything foldable, so the fold is proved generic."""

    count: int = 0
    processing: tuple[StageRun, ...] = ()

    def with_processing(self, *runs: StageRun) -> Counter:
        return replace(self, processing=self.processing + tuple(runs))


class Add:
    name: ClassVar[str] = "add"

    def __init__(self, by: int) -> None:
        self.by = by

    def apply(self, data: Counter) -> Counter:
        return replace(data, count=data.count + self.by)

    def describe(self) -> StageRun:
        return StageRun(name=self.name, parameters=(("by", self.by),))


def test_a_value_implementing_with_processing_is_processable_at_runtime() -> None:
    assert isinstance(Counter(), Processable)
    assert not isinstance(object(), Processable)


def test_a_pipeline_folds_its_stages_in_order() -> None:
    result = Pipeline([Add(2), Add(3)]).run(Counter())

    assert result.count == 5


def test_each_stage_is_recorded_after_it_succeeds() -> None:
    result = Pipeline([Add(2), Add(3)]).run(Counter())

    assert [run.name for run in result.processing] == ["add", "add"]
    assert [dict(run.parameters)["by"] for run in result.processing] == [2, 3]


def test_a_stage_is_recorded_only_after_it_succeeds() -> None:
    """``describe()`` must run after ``apply()``, not before it.

    A fold that recorded first would report a stage that never ran. The
    list below is the observable: ``Boom.describe`` appends to it, so an
    empty list proves the record was never taken.
    """
    described: list[str] = []

    class Boom:
        name: ClassVar[str] = "boom"

        def apply(self, data: Counter) -> Counter:
            raise RuntimeError("no")

        def describe(self) -> StageRun:
            described.append(self.name)
            return StageRun(name="boom", parameters=())

    stages: list[Stage[Counter]] = [Add(1), Boom()]

    with pytest.raises(RuntimeError, match="no"):
        Pipeline(stages).run(Counter())

    assert described == []


def test_then_returns_a_new_pipeline_and_leaves_the_original_alone() -> None:
    first = Pipeline([Add(1)])
    second = first.then(Add(1))

    assert len(first) == 1
    assert len(second) == 2
    assert second.run(Counter()).count == 2


def test_a_text_payload_is_written_as_utf_eight(tmp_path) -> None:
    path = tmp_path / "out.txt"

    write_payload(path, "⌀7.000")

    assert path.read_text(encoding="utf-8") == "⌀7.000"


def test_a_text_payload_counts_encoded_bytes_not_characters(tmp_path) -> None:
    """``⌀`` is three bytes in UTF-8 and one character. The count is the whole
    reason this lives here: ``stompcad`` reduces over both tools' numbers and
    they have to mean one thing."""
    assert write_payload(tmp_path / "out.txt", "⌀7.000") == 8


def test_a_binary_payload_is_written_unchanged(tmp_path) -> None:
    path = tmp_path / "out.bin"

    write_payload(path, b"%PDF-1.7\n\x00\xff")

    assert path.read_bytes() == b"%PDF-1.7\n\x00\xff"


def test_a_binary_payload_counts_its_own_length(tmp_path) -> None:
    assert write_payload(tmp_path / "out.bin", b"%PDF-1.7\n\x00\xff") == 11


def test_a_failed_write_leaves_a_preexisting_file_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two clauses of a failed write are independent: a fix that cleans
    up its temporary but still corrupts the target passes the companion test
    below and fails this one.
    """
    path = tmp_path / "out.bin"
    path.write_bytes(b"ORIGINAL")

    def _boom(self: Path, data: bytes) -> int:
        # Actually truncate and partially write whatever file this call
        # targets, so the fault is indistinguishable from a real disk-full
        # error partway through -- a mock that raises before touching the
        # filesystem would leave the pre-existing file untouched by
        # construction and prove nothing about a direct-write implementation.
        with open(self, "wb") as handle:
            handle.write(data[: len(data) // 2])
        raise OSError("simulated disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)

    with pytest.raises(OSError):
        write_payload(path, b"REPLACEMENT-THAT-NEVER-ARRIVES")

    assert path.read_bytes() == b"ORIGINAL"


def test_a_failed_write_leaves_no_temporary_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two clauses are independent: a fix that preserves the target but
    litters the directory with an abandoned temporary passes the test above
    and fails this one.
    """
    path = tmp_path / "out.bin"
    path.write_bytes(b"ORIGINAL")

    def _boom(self: Path, data: bytes) -> int:
        # Actually truncate and partially write whatever file this call
        # targets, so the fault is indistinguishable from a real disk-full
        # error partway through -- a mock that raises before touching the
        # filesystem would leave the pre-existing file untouched by
        # construction and prove nothing about a direct-write implementation.
        with open(self, "wb") as handle:
            handle.write(data[: len(data) // 2])
        raise OSError("simulated disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)

    with pytest.raises(OSError):
        write_payload(path, b"REPLACEMENT-THAT-NEVER-ARRIVES")

    assert [entry.name for entry in tmp_path.iterdir()] == ["out.bin"]


def test_the_temporary_and_the_target_share_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proved rather than asserted: spy on the rename call itself, so the
    replacement is shown to be atomic on the target's own filesystem rather
    than merely tidy.
    """
    path = tmp_path / "out.bin"
    seen: dict[str, Path] = {}
    real_replace = os.replace

    def _spy_replace(src: str | Path, dst: str | Path) -> None:
        seen["src"] = Path(src)
        seen["dst"] = Path(dst)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy_replace)

    write_payload(path, b"DATA")

    assert seen["src"] != seen["dst"]
    assert seen["src"].parent == seen["dst"].parent == tmp_path


def test_a_target_whose_directory_is_missing_still_raises_an_os_error(
    tmp_path: Path,
) -> None:
    """The temp-and-rename mechanism must not change which failures occur --
    only what a failure leaves behind. A missing parent is still the same
    class of error the command line already translates to its IO exit code.
    """
    missing = tmp_path / "nope" / "out.bin"

    with pytest.raises(OSError):
        write_payload(missing, b"DATA")


# --------------------------------------------------------------------------
# Diagnosable: the vocabulary the exit-code reduction consumes, published so
# a second value type reaches it with no tool-specific glue.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinimalDockData:
    """The second tool's minimal value object: implements only the four
    ``Diagnosable`` members, exactly as ``stompcollider``'s ``DockData`` will."""

    diagnostics: tuple[Diagnostic, ...] = ()

    def with_diagnostics(self, *diagnostics: Diagnostic) -> MinimalDockData:
        return replace(self, diagnostics=self.diagnostics + tuple(diagnostics))

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        return of_severity(self.diagnostics, severity)

    @property
    def worst_severity(self) -> Severity | None:
        return worst_severity(self.diagnostics)


def _read_worst_severity(value: Diagnosable) -> Severity | None:
    """Typed against ``Diagnosable`` so a missing member is a static error too."""
    return value.worst_severity


if TYPE_CHECKING:
    # Never executed: Counter has no `diagnostics`, `with_diagnostics`,
    # `of_severity` or `worst_severity`, so passing it where `Diagnosable`
    # is required is a static rejection. mypy flags the line below without
    # the ignore; the ignore records that the rejection is expected, not
    # accidental.
    _read_worst_severity(Counter())  # type: ignore[arg-type]


def test_a_processable_only_value_is_refused_by_diagnosable_at_runtime() -> None:
    """``Counter`` implements the entirety of ``Processable`` and nothing more:
    the two protocols are separate on purpose, so satisfying one must not
    satisfy the other."""
    assert isinstance(Counter(), Processable)
    assert not isinstance(Counter(), Diagnosable)


def test_a_value_implementing_the_four_members_is_diagnosable_and_reaches_the_shared_exit_reduction() -> (
    None
):
    """The second tool's minimal value object, standing in for ``DockData``:
    implementing exactly the four declared members is enough to reach
    ``exit_for_severity`` with no ``stompdrill``-specific glue."""
    data = MinimalDockData().with_diagnostics(Diagnostic.error("dock-fouled", "clash"))

    assert isinstance(data, Diagnosable)
    assert exit_for_severity(data.worst_severity) == EXIT_ERRORS


def test_drill_data_satisfies_both_processable_and_diagnosable() -> None:
    assert isinstance(DrillData(), Processable)
    assert isinstance(DrillData(), Diagnosable)


def _some_diagnostics() -> tuple[Diagnostic, ...]:
    return (
        Diagnostic.warning("off-grid", "hole 4 moved"),
        Diagnostic.error("unknown-diameter", "no bit in the drawer"),
        Diagnostic.info("duplicate-hole", "two circles in one place"),
    )


@pytest.mark.parametrize("severity", list(Severity))
def test_drill_data_of_severity_matches_the_published_function(severity: Severity) -> None:
    """One implementation of 'of this severity' exists in the workspace: the
    method must return exactly what the published function returns, for the
    identical diagnostics, at every severity — not merely one that agrees."""
    diagnostics = _some_diagnostics()
    data = DrillData(diagnostics=diagnostics)

    assert data.of_severity(severity) == of_severity(diagnostics, severity)


def test_drill_data_of_severity_matches_the_published_function_when_empty() -> None:
    data = DrillData()

    assert data.of_severity(Severity.ERROR) == of_severity((), Severity.ERROR) == ()


def test_drill_data_worst_severity_matches_the_published_function() -> None:
    """One implementation of 'worst severity' exists in the workspace."""
    diagnostics = _some_diagnostics()
    data = DrillData(diagnostics=diagnostics)

    assert data.worst_severity == worst_severity(diagnostics)


def test_drill_data_worst_severity_matches_the_published_function_when_empty() -> None:
    data = DrillData()

    assert data.worst_severity == worst_severity(()) is None


# -- AC5: each of the four members is independently load-bearing -----------


def test_missing_diagnostics_fails_the_protocol_check() -> None:
    class NoDiagnostics:
        def with_diagnostics(self, *diagnostics: Diagnostic) -> NoDiagnostics:
            return self

        def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
            return ()

        @property
        def worst_severity(self) -> Severity | None:
            return None

    assert not isinstance(NoDiagnostics(), Diagnosable)


def test_missing_with_diagnostics_fails_the_protocol_check() -> None:
    class NoWithDiagnostics:
        diagnostics: tuple[Diagnostic, ...] = ()

        def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
            return ()

        @property
        def worst_severity(self) -> Severity | None:
            return None

    assert not isinstance(NoWithDiagnostics(), Diagnosable)


def test_missing_of_severity_fails_the_protocol_check() -> None:
    class NoOfSeverity:
        diagnostics: tuple[Diagnostic, ...] = ()

        def with_diagnostics(self, *diagnostics: Diagnostic) -> NoOfSeverity:
            return self

        @property
        def worst_severity(self) -> Severity | None:
            return None

    assert not isinstance(NoOfSeverity(), Diagnosable)


def test_missing_worst_severity_fails_the_protocol_check() -> None:
    class NoWorstSeverity:
        diagnostics: tuple[Diagnostic, ...] = ()

        def with_diagnostics(self, *diagnostics: Diagnostic) -> NoWorstSeverity:
            return self

        def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
            return ()

    assert not isinstance(NoWorstSeverity(), Diagnosable)
