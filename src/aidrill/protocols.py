"""The three abstractions the whole design rests on.

Kept deliberately narrow (ISP): a Stage knows nothing about emitters, an Emitter
knows nothing about sources, and ``Pipeline`` depends on ``Stage`` alone (DIP).
Only ``cli.py`` is allowed to name concrete implementations.
"""

from __future__ import annotations

from typing import ClassVar, Iterable, Iterator, Protocol, Sequence, runtime_checkable

from .model import DrillData, StageRun

__all__ = ["Source", "Stage", "Emitter", "Pipeline"]


@runtime_checkable
class Source(Protocol):
    """Parses some artwork format into DrillData in the canonical frame."""

    def read(self) -> DrillData: ...


@runtime_checkable
class Stage(Protocol):
    """One preprocessing step.

    Must be a pure function of its input: same DrillData in, same DrillData out.
    Must not assert anything about which stage ran before it (LSP) — a stage that
    only works after snapping is a design error, not a documentation problem.
    """

    name: ClassVar[str]

    def apply(self, data: DrillData) -> DrillData: ...

    def describe(self) -> StageRun:
        """Report what this stage was configured to do, with *effective* values.

        The drawing's title block must state the grid the holes were actually
        snapped to. Threading that through the emitter's options instead meant a
        library consumer could emit a sheet stamped 0.25 for data snapped at 0.5.
        """
        ...


@runtime_checkable
class Emitter(Protocol):
    """Serialises DrillData into one output format.

    Emitters may translate frames and convert units, but must never round
    positions, cluster diameters, drop duplicates, or otherwise re-derive
    anything the pipeline is responsible for.
    """

    name: ClassVar[str]
    media_type: ClassVar[str]
    extension: ClassVar[str]

    def emit(self, data: DrillData) -> str: ...


class Pipeline(Sequence[Stage]):
    """An ordered, immutable sequence of stages. Contains no domain knowledge."""

    __slots__ = ("_stages",)

    def __init__(self, stages: Iterable[Stage] = ()) -> None:
        self._stages: tuple[Stage, ...] = tuple(stages)

    def __getitem__(self, index):  # type: ignore[override]
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    def __repr__(self) -> str:
        return f"Pipeline({[s.name for s in self._stages]!r})"

    def then(self, stage: Stage) -> "Pipeline":
        """Return a new pipeline with ``stage`` appended."""
        return Pipeline(self._stages + (stage,))

    def run(self, data: DrillData) -> DrillData:
        """Fold the stages over ``data``, recording each one as it succeeds.

        The record is appended *after* ``apply`` returns, so a stage never sees
        provenance for itself in its own input and a stage that raises leaves no
        claim that it ran. What the record contains is the stage's business:
        this fold asks ``describe()`` and stores the answer, which is how it
        stays free of any knowledge of grids, diameters or tolerances.
        """
        for stage in self._stages:
            data = stage.apply(data).with_processing(stage.describe())
        return data
