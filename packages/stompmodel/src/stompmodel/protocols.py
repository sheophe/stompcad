"""The contracts a stomp pipeline is built from, generic in what it folds.

stompdrill folds stages over DrillData and stompcollider folds Match and
Seat over DockData; stompcad reads both tools' StageRun provenance and
reduces it uniformly. Two hand-copied folds would drift exactly where
ADR-0001's consistency argument bites. See ADR-0009.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import ClassVar, Protocol, TypeVar, overload, runtime_checkable

from .diagnostics import Diagnostic, Severity
from .model import StageRun

__all__ = [
    "Processable",
    "Diagnosable",
    "Stage",
    "Emitter",
    "Payload",
    "write_payload",
    "Pipeline",
]


#: Binds ``with_processing`` to the caller's own type. A protocol naming
#: itself as the return type would widen the folded value to ``Processable``
#: at the first stage, and the fold would stop being generic in what it folds.
SelfT = TypeVar("SelfT")


@runtime_checkable
class Processable(Protocol):
    """A value a pipeline can fold over: it can record the stages it survived."""

    def with_processing(self: SelfT, *runs: StageRun) -> SelfT: ...


@runtime_checkable
class Diagnosable(Protocol):
    """A value that carries findings and reduces them by severity.

    Separate from ``Processable`` on purpose: most stage- and emitter-bound
    values carry no diagnostics of their own, and folding this vocabulary
    into ``Processable`` would make every one of them carry it. A second
    tool's value type implements this to reach the shared exit-code
    reduction with no tool-specific glue. See ADR-0009.
    """

    diagnostics: tuple[Diagnostic, ...]

    def with_diagnostics(self: SelfT, *diagnostics: Diagnostic) -> SelfT: ...

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]: ...

    @property
    def worst_severity(self) -> Severity | None: ...


#: Invariant: a stage both consumes and produces the value it folds over.
T = TypeVar("T", bound=Processable)

#: Contravariant: an emitter only consumes, so one serialising any Processable
#: stands in wherever one serialising a narrower value is asked for.
T_contra = TypeVar("T_contra", bound=Processable, contravariant=True)


@runtime_checkable
class Stage(Protocol[T]):
    """A deterministic preprocessing step independent of pipeline position."""

    name: ClassVar[str]

    def apply(self, data: T) -> T: ...

    def describe(self) -> StageRun:
        """Report the effective configuration applied by this stage."""
        ...


#: What an emitter hands back. Text formats return ``str``; a byte format such
#: as PDF returns ``bytes``. The writing site chooses how to put it on disk —
#: see ADR-0005.
Payload = str | bytes


def write_payload(path: Path, payload: Payload) -> int:
    """Write ``payload``, letting its own type choose the mode.

    Returns the encoded byte count, which is the number both tools report
    and ``stompcad`` reduces over. A second copy of this branch is a second
    counting convention, which is the drift ADR-0005's consequence forbids.
    """
    if isinstance(payload, bytes):
        path.write_bytes(payload)
        return len(payload)
    encoded = payload.encode("utf-8")
    # newline="\n" disables universal-newline translation, which otherwise
    # rewrites "\n" to os.linesep and makes the returned count -- the
    # untranslated encoding length -- wrong on a platform where the two
    # differ. On POSIX os.linesep is already "\n", so no artefact byte
    # changes here; this makes the contract true everywhere, not just here.
    path.write_text(payload, encoding="utf-8", newline="\n")
    return len(encoded)


@runtime_checkable
class Emitter(Protocol[T_contra]):
    """Serialises one value into one output format.

    Emitters may translate frames and convert units, but do not quantise,
    deduplicate, sort, or renumber the model.
    """

    name: ClassVar[str]
    media_type: ClassVar[str]
    extension: ClassVar[str]

    def emit(self, data: T_contra) -> Payload: ...


class Pipeline(Sequence[Stage[T]]):
    """An ordered, immutable sequence of stages. Contains no domain knowledge."""

    __slots__ = ("_stages",)

    def __init__(self, stages: Iterable[Stage[T]] = ()) -> None:
        self._stages: tuple[Stage[T], ...] = tuple(stages)

    @overload
    def __getitem__(self, index: int) -> Stage[T]: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Stage[T], ...]: ...
    def __getitem__(self, index: int | slice) -> Stage[T] | tuple[Stage[T], ...]:
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage[T]]:
        return iter(self._stages)

    def __repr__(self) -> str:
        return f"Pipeline({[s.name for s in self._stages]!r})"

    def then(self, stage: Stage[T]) -> Pipeline[T]:
        """Return a new pipeline with ``stage`` appended."""
        return Pipeline(self._stages + (stage,))

    def run(self, data: T) -> T:
        """Fold the stages over ``data``, recording each one as it succeeds.

        A record is appended only after ``apply`` returns successfully.
        """
        for stage in self._stages:
            data = stage.apply(data).with_processing(stage.describe())
        return data
