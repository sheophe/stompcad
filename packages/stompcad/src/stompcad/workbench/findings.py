"""A run's findings, and the count the sidebar carries.

Spec decision 11 groups findings into six families by remedy, and gives each
family its prose; that is plan 3's whole subject. What plan 2 needs is the
seam: one ``Finding`` per diagnostic, a count that covers errors and
warnings but never information, and a place a remedy can live in. Until plan
3 fills ``classify``, every finding has an empty family and no place --
which is honest rather than provisional: nothing in this plan claims a
classification it has not made.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from stompmodel.diagnostics import Diagnostic, Severity

from .keys import Place

__all__ = ["Finding", "classify", "counted"]

#: What the sidebar counts. Decision 4: a "worth knowing" entry is listed in
#: the place but never counted and never marks anything, because a sidebar
#: reporting a successful run as attention owed teaches a builder to ignore
#: the marker.
_COUNTED = frozenset({Severity.ERROR, Severity.WARNING})


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic, the family that owns its remedy, and where that lives.

    ``family`` and ``place`` are empty here and filled by plan 3. A finding
    belongs to exactly one family; a code usually does, which is why the
    classification is per finding rather than per code.
    """

    diagnostic: Diagnostic
    family: str = ""
    place: Place | None = None


def classify(diagnostics: Sequence[Diagnostic]) -> tuple[Finding, ...]:
    """One finding per diagnostic, in the order the run raised them."""
    return tuple(Finding(diagnostic) for diagnostic in diagnostics)


def counted(findings: Sequence[Finding]) -> int:
    """How many findings the sidebar's count covers."""
    return sum(1 for finding in findings if finding.diagnostic.severity in _COUNTED)
