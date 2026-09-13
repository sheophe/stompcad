"""What a run's values are, where each came from, and what disagrees.

Spec decisions 6 and 7: resolution has four ranks and every value reports
its origin, because an artefact must never be quietly attributable to the
wrong settings. A leaf module by design -- it imports nothing from this
package, so ``drive`` may import it without a cycle, and nothing here
knows what a step does with a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

__all__ = ["Origin", "Provenance", "Discovery", "Resolved", "pick"]

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class Origin(Enum):
    """Which rank supplied a value. Ordered worst-to-best, as ranks are."""

    DEFAULT = "default"
    DISCOVERED = "discovered"
    PROJECT = "from the project"
    ARGUMENT = "from the command line"
    USER = "you set this"


@dataclass(frozen=True, slots=True)
class Provenance:
    """An origin, and for a discovered value how it was found.

    ``detail`` is the phrase the row shows -- "the artwork", "found beside
    it", "inferred from tar-case.stp" -- rather than a second enumeration
    that would have to grow every time a new thing becomes discoverable.
    """

    origin: Origin
    detail: str = ""

    def describe(self) -> str:
        """The origin as a row states it, reading as English either way."""
        if self.origin is Origin.DISCOVERED and self.detail:
            return self.detail
        return self.origin.value


@dataclass(frozen=True, slots=True)
class Discovery(Generic[_T_co]):
    """Something the tool found out, and the phrase naming how."""

    value: _T_co
    detail: str


@dataclass(frozen=True, slots=True)
class Resolved(Generic[_T]):
    """One value, its origin, and the project's value where the two differ.

    ``project`` is not the manifest's value in general -- it is only the
    one the manifest holds *and* something else overrode, so a row can
    show the disagreement without the caller looking it up again.
    """

    value: _T
    provenance: Provenance
    project: _T | None = None

    def describe(self) -> str:
        """``0.5, you set this — the project says 0.25``, or the first half alone."""
        stated = f"{self.value}, {self.provenance.describe()}"
        if self.project is None:
            return stated
        return f"{stated} — the project says {self.project}"


def pick(
    argument: _T | None,
    project: _T | None,
    discovered: Discovery[_T] | None,
    default: _T,
) -> Resolved[_T]:
    """The four ranks, best first, and the disagreement the winner overrode.

    ``None`` means absent at every rank, which is exact rather than
    convenient: a flag left unset and a flag passed as nothing are the same
    statement, and no parameter here distinguishes them.

    Only a rank above the project records a disagreement. Discovery that
    differs from the project is not an override but a finding, raised where
    the run can say which file disagreed -- see spec decision 6.
    """
    if argument is not None:
        return Resolved(
            argument,
            Provenance(Origin.ARGUMENT),
            project if project is not None and project != argument else None,
        )
    if project is not None:
        return Resolved(project, Provenance(Origin.PROJECT))
    if discovered is not None:
        return Resolved(discovered.value, Provenance(Origin.DISCOVERED, discovered.detail))
    return Resolved(default, Provenance(Origin.DEFAULT))
