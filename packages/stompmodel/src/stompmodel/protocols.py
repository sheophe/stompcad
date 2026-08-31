"""The contracts a stomp pipeline is built from, generic in what it folds.

stompdrill folds stages over DrillData and stompcollider folds Match and
Seat over DockData; stompcad reads both tools' StageRun provenance and
reduces it uniformly. Two hand-copied folds would drift exactly where
ADR-0001's consistency argument bites. See ADR-0009.
"""

from __future__ import annotations

import errno
import os
import unicodedata
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
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
    "StagedWrite",
    "stage_payload",
    "stage_all",
    "commit_all",
    "target_key",
    "check_target_set",
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


@dataclass(frozen=True, slots=True)
class StagedWrite:
    """One payload already written in full to a temporary beside its target.

    Produced only by :func:`stage_payload`; never built by hand. ``path`` is
    the target :meth:`commit` will replace and ``size`` is the encoded byte
    count both tools report -- the two facts a caller's report line needs.
    Exactly one of :meth:`commit` and :meth:`discard` is owed on every value
    handed out; the temporary is not a caller's business, so neither verb
    names it and neither is reachable without the value it applies to.
    """

    path: Path
    size: int
    _tmp: Path

    def commit(self) -> int:
        """Replace :attr:`path` from its temporary. Returns :attr:`size`.

        Atomic: afterwards :attr:`path` holds either the complete payload
        or exactly what it held before, and the temporary survives neither
        outcome. The count is the one :func:`stage_payload` already
        computed, returned unchanged -- a second derivation of it is the
        drift ADR-0005's consequence forbids.
        """
        try:
            os.replace(self._tmp, self.path)
        except BaseException:
            self._tmp.unlink(missing_ok=True)
            raise
        return self.size

    def discard(self) -> None:
        """Abandon a staged write without touching its target. Never raises."""
        self._tmp.unlink(missing_ok=True)


def stage_payload(path: Path, payload: Payload) -> StagedWrite:
    """Encode ``payload`` and write it in full to a fresh temporary beside ``path``.

    ``path`` itself is never touched here. A directory target is refused
    before any temporary exists, rather than deferred to a later rename
    failure. Every other precondition is the filesystem's own answer to the
    write below; on failure the temporary is unlinked and the raised
    exception is corrected to name ``path``, never the temporary.
    """
    # Encoding first means one write path serves both payload types, and it
    # is what makes the "untranslated encoded length" contract exact: bytes
    # written this way are never subject to newline translation, on any
    # platform, so there is no "\n"-vs-os.linesep case to reason about.
    data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    if path.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
    except OSError as failure:
        # Cleanup is best-effort here: the same broken parent that failed
        # the write (not a directory, say) fails the unlink identically,
        # and that second failure must not displace the first -- the one
        # ``failure`` below is corrected to report.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        failure.filename = str(path)
        raise
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return StagedWrite(path=path, size=len(data), _tmp=tmp)


#: One target already replaced during a commit loop, beside the bytes it
#: held before -- ``None`` when the target did not exist. Rolling the two
#: back differs: rewrite one, delete the other.
_Committed = tuple[Path, bytes | None]


def stage_all(targets: Iterable[tuple[Path, Payload]]) -> list[StagedWrite]:
    """Stage every payload through :func:`stage_payload`; touch no target.

    A failure partway through discards every staged write this call has
    already produced and re-raises, so one payload that cannot be staged
    leaves every target of the set exactly as it was. This is the
    set-level half of ADR-0001's guarantee; :func:`stage_payload` owns the
    per-path half, and no caller states either mechanism itself.
    """
    staged: list[StagedWrite] = []
    try:
        for path, payload in targets:
            staged.append(stage_payload(path, payload))
    except BaseException:
        for written in staged:
            written.discard()
        raise
    return staged


def _rollback(committed: list[_Committed]) -> None:
    """Undo every target already replaced earlier in a commit loop.

    Restores each through the same published mechanism every other write
    here uses, and never raises: a target this cannot restore is the one
    residual ADR-0001 excludes from the guarantee, and swallowing it keeps
    the failure that triggered the rollback the one that propagates.
    """
    for path, previous in reversed(committed):
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                stage_payload(path, previous).commit()
        except OSError:
            pass


def commit_all(staged: Iterable[StagedWrite]) -> list[int]:
    """Replace every target from its already-staged write, in order.

    Returns each :meth:`StagedWrite.commit`'s own byte count, positionally.
    An existing target's prior bytes are read before its own commit so they
    can be put back; on failure :func:`_rollback` restores what this loop
    already replaced and every write still pending is discarded. That is
    what makes the whole set one transaction rather than each path one.
    """
    sizes: list[int] = []
    committed: list[_Committed] = []
    pending = list(staged)
    try:
        while pending:
            written = pending[0]
            previous = written.path.read_bytes() if written.path.exists() else None
            size = written.commit()
            pending.pop(0)
            committed.append((written.path, previous))
            sizes.append(size)
    except BaseException:
        _rollback(committed)
        for written in pending:
            written.discard()
        raise
    return sizes


def target_key(path: Path) -> str:
    """A key under which two spellings of one file compare equal.

    Resolved first: a filesystem may hold two spellings, or two paths joined
    by a symlink, as one file. Folded twice because casefolding can itself
    denormalise -- see ADR-0001.
    """
    resolved = str(path.resolve())
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", resolved).casefold())


def check_target_set(paths: Sequence[Path]) -> None:
    """Refuse a set two of whose members would reach one file.

    Raises ``ValueError``; the caller owns what that means for its own exit
    code, because this package cannot see a command line.
    """
    seen: dict[str, Path] = {}
    for path in paths:
        key = target_key(path)
        if key in seen:
            raise ValueError(
                f"{path} and {seen[key]} name one file; each artefact needs its own"
            )
        seen[key] = path
        if path.exists() and not path.is_file():
            raise ValueError(f"{path} exists and is not a regular file")


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
