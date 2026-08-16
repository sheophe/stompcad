"""Protocols for reading, processing, and emitting drill data."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import ClassVar, Protocol, runtime_checkable

from .model import DrillData, RawDrillData, StageRun

__all__ = ["Source", "Stage", "Emitter", "Payload", "Pipeline"]


@runtime_checkable
class Source(Protocol):
    """Read artwork as unquantised finite millimetres in ``RawDrillData``.

    Coordinates are Y-up and centred on the reference outline when present;
    otherwise they remain page-relative and the missing frame is diagnosed.
    """

    def read(self) -> RawDrillData: ...


@runtime_checkable
class Stage(Protocol):
    """A deterministic preprocessing step independent of pipeline position."""

    name: ClassVar[str]

    def apply(self, data: DrillData) -> DrillData: ...

    def describe(self) -> StageRun:
        """Report the effective configuration applied by this stage."""
        ...


#: What an emitter hands back. Text formats return ``str``; a byte format such
#: as PDF returns ``bytes``. The writing site chooses how to put it on disk —
#: see ADR-0005.
Payload = str | bytes


@runtime_checkable
class Emitter(Protocol):
    """Serialises DrillData into one output format.

    Emitters may translate frames and convert units, but do not quantise,
    deduplicate, sort, or renumber the model.
    """

    name: ClassVar[str]
    media_type: ClassVar[str]
    extension: ClassVar[str]

    def emit(self, data: DrillData) -> Payload: ...


class Pipeline(Sequence[Stage]):
    """An ordered, immutable sequence of stages. Contains no domain knowledge."""

    __slots__ = ("_stages",)

    def __init__(self, stages: Iterable[Stage] = ()) -> None:
        self._stages: tuple[Stage, ...] = tuple(stages)

    def __getitem__(self, index):
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    def __repr__(self) -> str:
        return f"Pipeline({[s.name for s in self._stages]!r})"

    def then(self, stage: Stage) -> Pipeline:
        """Return a new pipeline with ``stage`` appended."""
        return Pipeline(self._stages + (stage,))

    def run(self, data: DrillData) -> DrillData:
        """Fold the stages over ``data``, recording each one as it succeeds.

        A record is appended only after ``apply`` returns successfully.
        """
        for stage in self._stages:
            data = stage.apply(data).with_processing(stage.describe())
        return data
