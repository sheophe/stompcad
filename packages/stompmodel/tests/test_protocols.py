"""The generic pipeline contracts, exercised on a value that is not DrillData."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar

import pytest

from stompmodel.model import StageRun
from stompmodel.protocols import Pipeline, Processable, Stage, write_payload


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
