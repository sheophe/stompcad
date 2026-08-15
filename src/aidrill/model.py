"""Canonical data model for aidrill.

Everything here is an immutable value object. Transforms return new instances;
nothing is mutated in place. This is what lets the pipeline be a plain left fold
and lets stages be tested in isolation.

Canonical frame, used by every stage and by every emitter's *input*:

    millimetres, Y up, origin at the centre of the reference outline.

Emitters that need a different frame or different units convert on output, via
``DrillData.with_origin`` and their own unit handling. No stage ever sees inches.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, Mapping

from .tolerance import ROW_SLACK

__all__ = [
    "Severity",
    "Origin",
    "Units",
    "RawHole",
    "Hole",
    "ReferenceOutline",
    "Diagnostic",
    "SourceInfo",
    "ParameterValue",
    "StageRun",
    "DrillData",
]


#: What a stage may record about itself in a ``StageRun``. One member wider than
#: ``Diagnostic.data``: a diameter table is a list of numbers, and flattening it
#: into a string would make the drawing parse its own provenance back out again.
ParameterValue = float | int | str | bool | tuple[float, ...]


class Severity(Enum):
    """How much a diagnostic should worry the operator."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __lt__(self, other: "Severity") -> bool:
        order = [Severity.INFO, Severity.WARNING, Severity.ERROR]
        return order.index(self) < order.index(other)


class Origin(Enum):
    """Where (0, 0) sits for an emitted artifact.

    CENTRE is the canonical internal frame. LOWER_LEFT is what most drilling
    equipment expects, because it keeps every coordinate positive.
    """

    CENTRE = "centre"
    LOWER_LEFT = "lower-left"


class Units(Enum):
    MILLIMETRES = "metric"
    INCHES = "inch"

    @property
    def per_mm(self) -> float:
        """Multiplier to convert a millimetre value into these units."""
        return 1.0 if self is Units.MILLIMETRES else 1.0 / 25.4


@dataclass(frozen=True, slots=True)
class RawHole:
    """As-measured values, before any normalisation.

    Kept for provenance so a drawing can show "0.00 (raw -39.9906)" and so a
    residual can always be recomputed rather than remembered.
    """

    x: float
    y: float
    diameter: float


@dataclass(frozen=True, slots=True)
class Hole:
    """One drilled hole in the canonical frame.

    ``index`` is the hole's stable identity. It is required — a shared default
    would put every hole back under one ambiguous name, which is the whole thing
    this field exists to remove.
    """

    x: float
    y: float
    diameter: float
    raw: RawHole
    index: int

    @classmethod
    def from_measurement(cls, x: float, y: float, diameter: float, index: int) -> "Hole":
        """Build a hole whose nominal values are still its measured values.

        ``index`` is the hole's stable identity, assigned once by the source in
        traversal order and preserved by every transform. It exists because a
        diagnostic needs a referent that survives later stages: keying on
        position went stale the moment a stage moved the hole, and keying on
        ``raw`` cannot work because two coincident circles — precisely the
        duplicate case — share identical raw geometry.
        """
        return cls(x=x, y=y, diameter=diameter, raw=RawHole(x, y, diameter), index=index)

    def moved_to(self, x: float, y: float) -> "Hole":
        return replace(self, x=x, y=y)

    def with_diameter(self, diameter: float) -> "Hole":
        return replace(self, diameter=diameter)

    def translated(self, dx: float, dy: float) -> "Hole":
        return replace(self, x=self.x + dx, y=self.y + dy)

    @property
    def residual(self) -> tuple[float, float, float]:
        """(dx, dy, ddia) between nominal and measured. Positive = nominal is larger."""
        return (self.x - self.raw.x, self.y - self.raw.y, self.diameter - self.raw.diameter)


@dataclass(frozen=True, slots=True)
class ReferenceOutline:
    """The panel outline that establishes the coordinate frame.

    ``centre_x``/``centre_y`` are in *source* space (PDF points, page frame) and
    exist only so a source can report what it used. Everything downstream works
    in the canonical frame where this outline is centred on the origin.
    """

    width: float
    height: float
    centre_x: float = 0.0
    centre_y: float = 0.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"reference outline must be positive, got {self.width}x{self.height}")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A finding. Stages append these; emitters render them.

    ``code`` is the stable machine key — tests and downstream tools match on it,
    never on ``message``.
    """

    severity: Severity
    code: str
    message: str
    location: tuple[float, float] | None = None
    data: tuple[tuple[str, float | int | str], ...] = ()

    @classmethod
    def warning(cls, code, message, location=None, data=()) -> "Diagnostic":
        return cls(Severity.WARNING, code, message, location, tuple(data))

    @classmethod
    def info(cls, code, message, location=None, data=()) -> "Diagnostic":
        return cls(Severity.INFO, code, message, location, tuple(data))

    @classmethod
    def error(cls, code, message, location=None, data=()) -> "Diagnostic":
        return cls(Severity.ERROR, code, message, location, tuple(data))

    def get(self, key: str, default=None):
        """Read one payload value. Emitters use this instead of re-deriving.

        ``data`` exists so that a consumer can act on a finding without
        recomputing the predicate that produced it. The drawing emitter needs to
        know *which* hole a ``duplicate-hole`` refers to; recomputing that from
        positions meant re-implementing Deduplicate's rule, badly.
        """
        for k, v in self.data:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Where the data came from, for title blocks and file headers."""

    path: str = ""
    drill_layer: str = ""
    reference_layer: str = ""
    layers_found: tuple[str, ...] = ()
    producer: str = "aidrill"


@dataclass(frozen=True, slots=True)
class StageRun:
    """What one stage was configured to do, recorded once it has done it.

    Deliberately generic — a name and a key/value payload, the same idiom as
    ``Diagnostic.data`` — rather than one record class per stage. A closed union
    of record types would have to grow a member for every new stage, which is
    precisely the extensibility ``Stage`` exists to protect: ``Pipeline`` records
    what the abstraction hands it and knows nothing about grids or diameters.

    ``parameters`` holds *effective* values, not raw constructor arguments: the
    drawing needs the grid numerically, so recording ``None`` for a threshold
    that resolved to 0.0625 would defeat the point of recording it at all.
    """

    name: str
    parameters: tuple[tuple[str, ParameterValue], ...] = ()

    def get(self, key: str, default=None):
        """Read one parameter. Mirrors ``Diagnostic.get`` so there is one idiom.

        A key a stage did not report is simply absent — the drawing asks for the
        grid and gets ``None`` from a run that never had one, rather than a
        plausible-looking default it would then print on a machinist's sheet.
        """
        for k, v in self.parameters:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class DrillData:
    """The single object that travels the whole pipeline."""

    holes: tuple[Hole, ...] = ()
    reference: ReferenceOutline | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    source: SourceInfo = field(default_factory=SourceInfo)
    processing: tuple[StageRun, ...] = ()

    # -- transforms ------------------------------------------------------
    def with_holes(self, holes: Iterable[Hole]) -> "DrillData":
        return replace(self, holes=tuple(holes))

    def with_diagnostics(self, *diagnostics: Diagnostic) -> "DrillData":
        if not diagnostics:
            return self
        return replace(self, diagnostics=self.diagnostics + tuple(diagnostics))

    def with_processing(self, *runs: "StageRun") -> "DrillData":
        """Append the record of a stage that has just run.

        Appended, never replaced: a stage may legitimately run twice — the CLI
        chooses the order, and nothing forbids two snaps — and the history is
        what happened, not a set of what was configured.
        """
        if not runs:
            return self
        return replace(self, processing=self.processing + tuple(runs))

    def with_origin(self, origin: Origin) -> "DrillData":
        """Translate every hole into the requested frame.

        The canonical frame is CENTRE. LOWER_LEFT needs a reference outline to
        know where the lower-left corner is; without one there is no defensible
        answer, so this raises rather than guessing.
        """
        if origin is Origin.CENTRE:
            return self
        if origin is Origin.LOWER_LEFT:
            if self.reference is None:
                raise ValueError("lower-left origin requires a reference outline")
            dx = self.reference.width / 2.0
            dy = self.reference.height / 2.0
            return self.with_holes(h.translated(dx, dy) for h in self.holes)
        raise ValueError(f"unknown origin {origin!r}")

    # -- derived ---------------------------------------------------------
    def tools(self) -> Mapping[float, int]:
        """Ordered {nominal diameter: 1-based tool number}, ascending by size.

        This lives on the model rather than in the Excellon emitter so that the
        drawing's hole schedule and the drill file's tool table cannot disagree.
        """
        return {d: i for i, d in enumerate(sorted({h.diameter for h in self.holes}), start=1)}

    def tool_counts(self) -> Mapping[float, int]:
        """{nominal diameter: how many holes use it}, ascending by size.

        Beside tools() for the same reason tools() is here at all: the drawing's
        QTY column, the JSON summary and the CLI report must be one computation.
        """
        counts: dict[float, int] = {d: 0 for d in self.tools()}
        for hole in self.holes:
            counts[hole.diameter] += 1
        return counts

    def rows(self, tolerance: float = ROW_SLACK) -> list[tuple[float, list[Hole]]]:
        """Holes grouped by Y, descending. Used for per-row chain dimensions."""
        buckets: dict[float, list[Hole]] = {}
        for hole in self.holes:
            for y in buckets:
                if abs(hole.y - y) <= tolerance:
                    buckets[y].append(hole)
                    break
            else:
                buckets[hole.y] = [hole]
        return [(y, sorted(hs, key=lambda h: h.x)) for y, hs in sorted(buckets.items(), reverse=True)]

    def last_run(self, stage_name: str) -> StageRun | None:
        """The most recent record for ``stage_name``, or ``None`` if it never ran.

        The drawing's title block must state the grid these holes were actually
        snapped to. It was told a second copy through its own options instead,
        so data snapped at 0.5 could be stamped 0.25 on the sheet a machinist
        reads. ``None`` — no such stage ran — is a real answer here, and the
        caller must render it as "not snapped", never as a default value.
        """
        for run in reversed(self.processing):
            if run.name == stage_name:
                return run
        return None

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is severity)

    @property
    def worst_severity(self) -> Severity | None:
        return max((d.severity for d in self.diagnostics), default=None)
