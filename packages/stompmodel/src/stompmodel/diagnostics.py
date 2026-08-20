"""Findings, and how much they should worry the operator.

Separate from the drill data on purpose: a docking finding and a drilling
finding are the same kind of thing, and stompcollider must be able to raise
one without importing a hole. See ADR-0009.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from functools import total_ordering

from stompmodel.units import Nanometre, _check_nanometres

__all__ = [
    "Severity",
    "ParameterValue",
    "Diagnostic",
    "EXIT_CLEAN",
    "EXIT_WARNINGS",
    "EXIT_ERRORS",
    "EXIT_USAGE",
    "exit_for_severity",
]

#: Stage parameters may include scalars or tuples; ``_nm`` keys enforce integers.
ParameterValue = float | int | str | bool | tuple[float, ...]


@total_ordering
class Severity(Enum):
    """How much a diagnostic should worry the operator.

    Order is ``INFO < WARNING < ERROR``. Mixed-type comparisons return
    ``NotImplemented`` through ``__lt__``.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        order = (Severity.INFO, Severity.WARNING, Severity.ERROR)
        return order.index(self) < order.index(other)


def _tupled(value: object) -> object:
    """Convert a value to a tuple, recursively, leaving a scalar untouched.

    ``json.load`` returns a list for every array, including a nested one, so
    a location payload such as ``tied_locations`` needs both levels turned
    back into tuples to be hashable and to equal the value a stage built.
    """
    if isinstance(value, list):
        return tuple(_tupled(element) for element in value)
    return value


def _check_payload_lengths(owner: str, items: Iterable[tuple[str, object]]) -> None:
    """Enforce whole nanometres for payload keys ending ``_nm``.

    Tuple values are checked elementwise; values under other keys remain open
    to non-length scalars.
    """
    for key, value in items:
        if not key.endswith("_nm"):
            continue
        if isinstance(value, tuple):
            for position, element in enumerate(value):
                _check_nanometres(owner, **{f"{key}[{position}]": element})
        else:
            _check_nanometres(owner, **{key: value})


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A finding. Stages append these; emitters render them.

    ``code`` is the stable machine key; ``message`` is human-readable.
    """

    severity: Severity
    code: str
    message: str
    location_nm: tuple[Nanometre, Nanometre] | None = None
    #: Scalars, tuples of hole identities, or tuples of locations for
    #: panel-wide findings.
    data: tuple[
        tuple[str, float | int | str | tuple[int, ...] | tuple[tuple[int, int], ...]], ...
    ] = ()

    def __post_init__(self) -> None:
        """Normalise sequences before validating canonical nanometre lengths.

        ``location_nm`` may be absent for panel-wide findings. Nested list
        payload values are converted to tuples, recursively, for immutable
        round trips through a location-carrying payload such as
        ``tied_locations``.
        """
        if self.location_nm is not None:
            x_nm, y_nm = self.location_nm
            object.__setattr__(self, "location_nm", (x_nm, y_nm))
            _check_nanometres("Diagnostic", location_x_nm=x_nm, location_y_nm=y_nm)
        object.__setattr__(
            self,
            "data",
            tuple((key, _tupled(value)) for key, value in self.data),
        )
        _check_payload_lengths("Diagnostic.data", self.data)

    @classmethod
    def warning(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.WARNING, code, message, location_nm, data)

    @classmethod
    def info(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.INFO, code, message, location_nm, data)

    @classmethod
    def error(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.ERROR, code, message, location_nm, data)

    def get(self, key: str, default=None):
        """Return a payload value without re-deriving the finding's predicate."""
        for k, v in self.data:
            if k == key:
                return v
        return default


#: The workspace's exit-code contract. Shared, because stompcad reduces
#: findings from more than one tool to a single status and a second copy of
#: this table is a second chance to disagree about what a warning is.
EXIT_CLEAN = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_USAGE = 3

_EXIT_FOR_SEVERITY: dict[Severity | None, int] = {
    None: EXIT_CLEAN,
    Severity.INFO: EXIT_CLEAN,
    Severity.WARNING: EXIT_WARNINGS,
    Severity.ERROR: EXIT_ERRORS,
}


def exit_for_severity(worst: Severity | None) -> int:
    """The exit status a run reporting ``worst`` should end with.

    Derived from the worst finding rather than recounted, so the report and
    the status cannot disagree. ``None`` means no finding at all.
    """
    return _EXIT_FOR_SEVERITY[worst]
