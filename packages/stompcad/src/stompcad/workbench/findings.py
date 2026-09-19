"""A run's findings, what to do about each, and the count the sidebar carries.

Spec decision 11: one ``Finding`` per diagnostic, classified by
``families`` into the remedy that owns it, the row that answers it where
one does, and the register a fit finding is stated in. The count covers
errors and warnings but never the family that asks nothing of anybody.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from stompmodel.diagnostics import Diagnostic, Severity

from .families import Family, Register, Remedy, family_of, register_of, remedy_of, secondary_of
from .keys import Place

__all__ = ["Finding", "classify", "counted"]

#: What the sidebar can count. "Worth knowing" is excluded by family as well,
#: because a WARNING can still be information.
_COUNTED = frozenset({Severity.ERROR, Severity.WARNING})


@dataclass(frozen=True, slots=True)
class Finding:
    """One diagnostic, the family that owns its remedy, and where that lives.

    ``family`` has no default: a finding nobody classified is what this
    module exists to prevent, and the type keeps it prevented. ``remedy``
    is set only where a row answers the finding, ``register`` only inside
    the family with three of them, ``secondary`` only where there are two
    honest answers.
    """

    diagnostic: Diagnostic
    family: Family
    remedy: Remedy | None = None
    register: Register | None = None
    secondary: str = ""

    @property
    def place(self) -> Place | None:
        """The place holding this finding's remedy: what the sidebar marks."""
        return None if self.remedy is None else self.remedy.place


def classify(diagnostics: Sequence[Diagnostic]) -> tuple[Finding, ...]:
    """One finding per diagnostic, in the order the run raised them.

    Order is the run's, not the family's: grouping happens where the lines
    are drawn, so this record still matches the step lines a piped run
    printed, which are byte-compared against the workbench's own.
    """
    return tuple(
        Finding(
            diagnostic,
            family_of(diagnostic),
            remedy_of(diagnostic),
            register_of(diagnostic),
            secondary_of(diagnostic),
        )
        for diagnostic in diagnostics
    )


def counted(findings: Sequence[Finding]) -> int:
    """How many findings the sidebar's count covers.

    Errors and warnings, less "worth knowing": ``multiple-boards`` is a
    WARNING on every deliberate multi-board pedal, and a count including it
    would report a successful run as attention owed. Only the badge reads
    this; no severity and no exit code depends on it.
    """
    return sum(
        1
        for finding in findings
        if finding.diagnostic.severity in _COUNTED and finding.family is not Family.KNOWING
    )
