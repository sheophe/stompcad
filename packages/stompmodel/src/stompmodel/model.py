"""Immutable drill-data values with unit and frame invariants.

Nominal lengths are whole nanometres in a Y-up, outline-centred frame; raw
measurements are finite float millimetres. ``_nm`` payloads contain
integers. Here rather than beside the tool that fills them: a sibling
member produces this and stompcollider consumes it, and neither owns it.
See ADR-0009.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum

from .diagnostics import Diagnostic, ParameterValue, Severity, _check_payload_lengths
from .errors import EmitterError
from .units import (
    Millimetre,
    Nanometre,
    _check_millimetres,
    _check_nanometres,
    mm_from_nm,
    nm_from_mm,
)

__all__ = [
    "Origin",
    "RawHole",
    "Hole",
    "RawOutline",
    "ReferenceOutline",
    "EnclosureMatch",
    "SourceInfo",
    "StageRun",
    "DrillData",
]


class Origin(Enum):
    """Where (0, 0) sits for an emitted artefact.

    CENTRE is the canonical internal frame. LOWER_LEFT is what most drilling
    equipment expects, because it keeps every coordinate positive.
    """

    CENTRE = "centre"
    LOWER_LEFT = "lower-left"


@dataclass(frozen=True, slots=True)
class RawHole:
    """One circle as the artwork measured it, in millimetres, before quantising.

    No traversal identity is retained: ADR-0006 forbids artwork order from
    reaching an artifact, so raw values exist only for provenance and residual
    calculation.
    """

    x: Millimetre
    y: Millimetre
    diameter: Millimetre

    def __post_init__(self) -> None:
        _check_millimetres("RawHole", x=self.x, y=self.y, diameter=self.diameter)


@dataclass(frozen=True, slots=True)
class Hole:
    """One drilled hole in the canonical frame.

    Nominal coordinates and diameter are whole nanometres. ``index`` is the
    drill sequence ``RouteHoles`` assigns; it is ``None`` until routed and
    numbered from 1 thereafter.
    """

    x_nm: Nanometre
    y_nm: Nanometre
    diameter_nm: Nanometre
    raw: RawHole
    index: int | None = None

    def __post_init__(self) -> None:
        _check_nanometres(
            "Hole", x_nm=self.x_nm, y_nm=self.y_nm, diameter_nm=self.diameter_nm
        )
        if self.index is not None and self.index < 1:
            raise ValueError(
                f"holes are numbered from 1, not {self.index}: this number is what "
                f"the drawing balloons, the schedule and the report all print"
            )

    @classmethod
    def from_measurement(
        cls,
        x_nm: Nanometre,
        y_nm: Nanometre,
        diameter_nm: Nanometre,
    ) -> Hole:
        """Build an unrouted hole whose nominal values are still its measured values.

        Convert nominal nanometres into the raw millimetre provenance. The
        hole carries no number until ``RouteHoles`` assigns one.
        """
        return cls(
            x_nm=x_nm,
            y_nm=y_nm,
            diameter_nm=diameter_nm,
            raw=RawHole(mm_from_nm(x_nm), mm_from_nm(y_nm), mm_from_nm(diameter_nm)),
        )

    def with_number(self, number: int) -> Hole:
        """Take the drill sequence RouteHoles assigned."""
        return replace(self, index=number)

    def moved_to(self, x_nm: Nanometre, y_nm: Nanometre) -> Hole:
        return replace(self, x_nm=x_nm, y_nm=y_nm)

    def with_diameter(self, diameter_nm: Nanometre) -> Hole:
        return replace(self, diameter_nm=diameter_nm)

    def translated(self, dx_nm: Nanometre, dy_nm: Nanometre) -> Hole:
        """Translate by exact whole-nanometre deltas.

        Deltas are validated before addition so arithmetic cannot coerce a
        boolean into an apparently valid integer coordinate.
        """
        _check_nanometres("Hole.translated", dx_nm=dx_nm, dy_nm=dy_nm)
        return replace(
            self,
            x_nm=Nanometre(self.x_nm + dx_nm),
            y_nm=Nanometre(self.y_nm + dy_nm),
        )

    @property
    def residual_nm(self) -> tuple[Nanometre, Nanometre, Nanometre]:
        """(dx, dy, ddia) between nominal and measured, in nanometres.

        Positive values mean the nominal value is larger. Raw measurements are
        converted to nanometres for subtraction but remain unchanged.
        """
        return (
            Nanometre(self.x_nm - nm_from_mm(self.raw.x)),
            Nanometre(self.y_nm - nm_from_mm(self.raw.y)),
            Nanometre(self.diameter_nm - nm_from_mm(self.raw.diameter)),
        )


@dataclass(frozen=True, slots=True)
class RawOutline:
    """The outline measured from artwork in millimetres before quantising."""

    width: Millimetre
    height: Millimetre

    def __post_init__(self) -> None:
        _check_millimetres("RawOutline", width=self.width, height=self.height)


#: Sentinel replaced with nominal dimensions when no raw measurement is supplied.
_MEASUREMENT_IS_NOMINAL = RawOutline(Millimetre(0.0), Millimetre(0.0))


@dataclass(frozen=True, slots=True)
class ReferenceOutline:
    """The panel outline that establishes the coordinate frame.

    Nominal dimensions and the source-space centre are whole nanometres;
    source-space starts at the page's lower-left. ``raw`` retains measurements.
    """

    width_nm: Nanometre
    height_nm: Nanometre
    centre_x_nm: Nanometre = Nanometre(0)
    centre_y_nm: Nanometre = Nanometre(0)
    raw: RawOutline = _MEASUREMENT_IS_NOMINAL

    def __post_init__(self) -> None:
        _check_nanometres(
            "ReferenceOutline",
            width_nm=self.width_nm,
            height_nm=self.height_nm,
            centre_x_nm=self.centre_x_nm,
            centre_y_nm=self.centre_y_nm,
        )
        if self.width_nm <= 0 or self.height_nm <= 0:
            raise ValueError(
                f"reference outline must be positive, got {self.width_nm}x{self.height_nm}"
            )
        if self.raw is _MEASUREMENT_IS_NOMINAL:
            object.__setattr__(
                self,
                "raw",
                RawOutline(mm_from_nm(self.width_nm), mm_from_nm(self.height_nm)),
            )

    @classmethod
    def from_measurement(
        cls,
        width_nm: Nanometre,
        height_nm: Nanometre,
        centre_x_nm: Nanometre = Nanometre(0),
        centre_y_nm: Nanometre = Nanometre(0),
    ) -> ReferenceOutline:
        """Build an outline whose nominal size is still its measured size.

        Record millimetre provenance before any later resize changes the nominal
        dimensions.
        """
        return cls(
            width_nm=width_nm,
            height_nm=height_nm,
            centre_x_nm=centre_x_nm,
            centre_y_nm=centre_y_nm,
            raw=RawOutline(mm_from_nm(width_nm), mm_from_nm(height_nm)),
        )

    def resized(self, width_nm: Nanometre, height_nm: Nanometre) -> ReferenceOutline:
        """Return new nominal dimensions with measurement and centre unchanged."""
        return replace(self, width_nm=width_nm, height_nm=height_nm)


@dataclass(frozen=True, slots=True)
class EnclosureMatch:
    """A catalogue footprint derived from a panel outline.

    ``candidates`` lists one or more parts sharing the 2-D footprint. Dimensions
    retain catalogue orientation; operator selection may mismatch for diagnostics.
    """

    family: str
    length_nm: Nanometre
    width_nm: Nanometre
    candidates: tuple[str, ...]
    rotated: bool = False
    selected_part: str | None = None

    def __post_init__(self) -> None:
        """Validate dimensions and normalise candidates to a tuple.

        A bare string is rejected before tuple conversion can split it into
        single-character designators.
        """
        _check_nanometres(
            "EnclosureMatch", length_nm=self.length_nm, width_nm=self.width_nm
        )
        # Runtime callers may supply values outside the declared tuple type.
        if isinstance(self.candidates, str):  # type: ignore[unreachable]
            raise TypeError("candidates must be a sequence of designators, not a single string")
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Where the data came from, for title blocks and file headers."""

    path: str = ""
    drill_layer: str = ""
    reference_layer: str = ""
    layers_found: tuple[str, ...] = ()
    #: Named by whoever read the artwork; the shared model is no tool's name.
    producer: str = ""


@dataclass(frozen=True, slots=True)
class StageRun:
    """A completed stage's name and effective configuration.

    ``parameters`` is generic so the pipeline need not know stage-specific
    settings.
    """

    name: str
    parameters: tuple[tuple[str, ParameterValue], ...] = ()

    def __post_init__(self) -> None:
        """Normalise parameters to tuples before validating ``_nm`` values."""
        object.__setattr__(
            self,
            "parameters",
            tuple(
                # JSON sequences arrive as lists despite the declared tuple type.
                (key, tuple(value) if isinstance(value, list) else value)  # type: ignore[unreachable]
                for key, value in self.parameters
            ),
        )
        _check_payload_lengths("StageRun.parameters", self.parameters)

    def get(self, key: str, default=None):
        """Return one effective parameter, or ``default`` when absent."""
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
    enclosure: EnclosureMatch | None = None

    # -- transforms ------------------------------------------------------
    def with_holes(self, holes: Iterable[Hole]) -> DrillData:
        return replace(self, holes=tuple(holes))

    def with_diagnostics(self, *diagnostics: Diagnostic) -> DrillData:
        if not diagnostics:
            return self
        return replace(self, diagnostics=self.diagnostics + tuple(diagnostics))

    def with_processing(self, *runs: StageRun) -> DrillData:
        """Append completed stage records in execution order."""
        if not runs:
            return self
        return replace(self, processing=self.processing + tuple(runs))

    def with_enclosure(self, match: EnclosureMatch) -> DrillData:
        """Replace the panel's current enclosure match."""
        return replace(self, enclosure=match)

    def with_origin(self, origin: Origin) -> DrillData:
        """Translate every hole into the requested frame.

        The canonical frame is ``CENTRE``. ``LOWER_LEFT`` requires an outline
        and shifts by each integer half-dimension, flooring odd nanometres.
        """
        if origin is Origin.CENTRE:
            return self
        if origin is Origin.LOWER_LEFT:
            if self.reference is None:
                raise ValueError("lower-left origin requires a reference outline")
            dx_nm = Nanometre(self.reference.width_nm // 2)
            dy_nm = Nanometre(self.reference.height_nm // 2)
            return self.with_holes(h.translated(dx_nm, dy_nm) for h in self.holes)
        raise ValueError(f"unknown origin {origin!r}")

    # -- derived ---------------------------------------------------------
    def numbered(self) -> tuple[tuple[int, Hole], ...]:
        """Every hole with its drill number, or raise if routing never ran."""
        pairs: list[tuple[int, Hole]] = []
        for hole in self.holes:
            if hole.index is None:
                raise EmitterError(
                    "these holes carry no drill number, so no artifact can state "
                    "a sequence — a hole carries none until a stage assigns one"
                )
            pairs.append((hole.index, hole))
        return tuple(pairs)

    def tools(self) -> Mapping[Nanometre, int]:
        """Map nominal diameter to 1-based tool number, ascending by size."""
        return {d: i for i, d in enumerate(sorted({h.diameter_nm for h in self.holes}), start=1)}

    def tool_counts(self) -> Mapping[Nanometre, int]:
        """Map nominal diameter to hole count, ascending by size."""
        counts: dict[Nanometre, int] = {d: 0 for d in self.tools()}
        for hole in self.holes:
            counts[hole.diameter_nm] += 1
        return counts

    def rows(self) -> list[tuple[Nanometre, list[Hole]]]:
        """Holes grouped by Y, rows from the top down, each row left to right.

        Exact nanometre equality groups rows; ordering supports top-down layout
        and left-to-right chain dimensions.
        """
        buckets: dict[Nanometre, list[Hole]] = {}
        for hole in self.holes:
            buckets.setdefault(hole.y_nm, []).append(hole)
        return [
            (y_nm, sorted(hs, key=lambda h: h.x_nm))
            for y_nm, hs in sorted(buckets.items(), reverse=True)
        ]

    def last_run(self, stage_name: str) -> StageRun | None:
        """Return the latest record for ``stage_name``, or ``None`` if absent."""
        for run in reversed(self.processing):
            if run.name == stage_name:
                return run
        return None

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is severity)

    @property
    def worst_severity(self) -> Severity | None:
        return max((d.severity for d in self.diagnostics), default=None)
