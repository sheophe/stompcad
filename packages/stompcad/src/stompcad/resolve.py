"""Which gaps a run can ask about, and what an answer changes.

Decision 6: only an ERROR carrying a known resolvable code reaches a
picker, and the candidates offered are the tool's own -- nothing here
invents one or reorders them. Pure throughout: it reads a diagnostic and
what carried it, and returns what to ask, never asking anything itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from stompmodel.diagnostics import Diagnostic, Severity

from .present import Choice

if TYPE_CHECKING:  # ``drive`` imports this module, so this cannot be a runtime import
    from .drive import RunOptions

__all__ = ["RESOLVABLE", "promoted", "question_for", "revision_for"]

#: Each resolvable code, and the step that runs again once it is answered.
#: Decision 6: a code absent from here never becomes a question, which is
#: how a refusal stays a refusal. Each step must read the field its answer
#: revises, which ``test_resolve`` checks against ``_STEP_INPUTS``.
RESOLVABLE: dict[str, str] = {
    "ambiguous-enclosure": "quantise",
    "empty-group": "read-boards",
}


def promoted(diagnostics: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Every warning raised to an error, leaving the rest as they are.

    Decision 6: promotion happens before the resolvable check, so a
    promoted warning is asked about on the same path an error is rather
    than on a second one written beside it. A code with no picker is
    unaffected either way -- being an error is necessary, not sufficient.
    """
    return tuple(
        replace(diagnostic, severity=Severity.ERROR)
        if diagnostic.severity is Severity.WARNING
        else diagnostic
        for diagnostic in diagnostics
    )


def question_for(
    diagnostic: Diagnostic,
    designators: Mapping[int, tuple[str, ...]] | None = None,
) -> Choice | None:
    """The choice this diagnostic offers, or ``None`` where it offers none.

    ``designators`` supplies a board's own names, because ``empty-group``
    records the board rather than the list. A resolvable code with no
    candidates asks nothing: a picker with no answers helps nobody.
    """
    if diagnostic.severity is not Severity.ERROR or diagnostic.code not in RESOLVABLE:
        return None
    candidates = _candidates(diagnostic, designators or {})
    if not candidates:
        return None
    return Choice(prompt=diagnostic.message, candidates=candidates)


def _candidates(
    diagnostic: Diagnostic, designators: Mapping[int, tuple[str, ...]]
) -> tuple[str, ...]:
    """Where each resolvable code keeps the answers it will accept.

    The enclosure stage formats its tied parts into one string, so the
    split belongs here beside the knowledge of what made it.
    """
    data = dict(diagnostic.data)
    if diagnostic.code == "ambiguous-enclosure":
        return tuple(part.strip() for part in str(data.get("candidates", "")).split(",") if part.strip())
    board = data.get("board")
    return designators.get(board, ()) if isinstance(board, int) else ()


def revision_for(diagnostic: Diagnostic, options: RunOptions, answer: str) -> RunOptions:
    """The options the step should run again under, given this answer.

    Each code revises exactly the field its own step reads, so the driver
    never refuses a revision a picker produced. A tie declares the part;
    a board nothing was admitted of widens the expression rather than
    replacing it, which would resolve one board by emptying the others.
    """
    if diagnostic.code == "ambiguous-enclosure":
        return replace(options, case=answer)
    if diagnostic.code == "empty-group":
        return replace(options, panel_reference=f"{options.panel_reference},{answer}")
    raise KeyError(diagnostic.code)
