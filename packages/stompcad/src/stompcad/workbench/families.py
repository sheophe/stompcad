"""What to do about a finding, grouped by remedy rather than by complainer.

Spec decision 11. Seven families, each owning the shared prose -- what its
findings mean and the routes out of them -- and each code contributing its
own sentence. A finding belongs to exactly one family; a code usually does,
which is why the functions below read the payload of the one code raised
twice with different remedies. The tables are data because the prose is
revised by people who are not editing logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from stompmodel.diagnostics import Diagnostic, Severity

from .keys import Place

__all__ = [
    "CODES",
    "FAMILIES",
    "NEAR_MISS",
    "REMEDIES",
    "Family",
    "Prose",
    "Register",
    "Remedy",
    "family_of",
    "register_of",
    "remedy_of",
    "secondary_of",
]


class Family(Enum):
    """The seven remedies. The value is the heading a builder reads."""

    ARTWORK = "Change the artwork"
    SETTING = "Change a setting"
    CANDIDATES = "Choose between candidates"
    BOARD = "Fix or re-export a board"
    MODEL = "Could not analyse a model"
    FIT = "This is what the fit is"
    KNOWING = "Worth knowing"


class Register(Enum):
    """How gravely a fit finding is stated. Decision 11 names three.

    The code decides before the severity does: ``enclosure-too-shallow`` is
    a WARNING that means the case will not close and
    ``every-seating-clashes`` an INFO that means nothing fits, and both are
    graver than an ERROR that only withheld an artefact.
    """

    INSPECT = "result available for inspection"
    WITHHELD = "assembly withheld"
    DO_NOT_BUILD = "do not build this yet"


@dataclass(frozen=True, slots=True)
class Prose:
    """One family's shared text, and the codes that belong to it."""

    means: str
    routes: str
    codes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Remedy:
    """The row that answers a finding: its place, and the field within it.

    A place alone lands on its first row, which for most places is an input
    file rather than the value the finding is about -- so a jump carrying
    only the place would take a builder somewhere that cannot fix what they
    came to fix.
    """

    place: Place
    field: str


FAMILIES: dict[Family, Prose] = {
    Family.ARTWORK: Prose(
        means=(
            "Something in the drawing needs attention: the tool adjusted it, dropped "
            "it, refused it, or could only warn."
        ),
        routes=(
            "Each line says which. Where a hole was adjusted -- moved onto the grid, "
            "drilled at a stocked size, dropped as a duplicate -- change the artwork "
            "if that is not what you meant. Where the tool only warns, check the "
            "drawing. Where it refused, nothing is substituted: an answer it declined "
            "to give is not one it will invent."
        ),
        codes=frozenset({
            "duplicate-hole", "hole-obstructed", "hole-off-face",
            "hole-outside-outline", "hole-through-boss", "no-reference-outline",
            "non-circular-path", "off-grid", "off-size",
            "reference-outline-not-found", "unknown-diameter",
            "unverifiable-enclosure",
        }),
    ),
    Family.SETTING: Prose(
        means="A different instruction may resolve this.",
        routes=(
            "Press enter on the line to go to the row that holds the value. The "
            "artwork can be the cause instead, and where it can, the line says so."
        ),
        codes=frozenset({
            "ambiguous-pairing", "grid-ambiguous", "grid-too-fine",
            "nesting-truncated", "reference-size-mismatch",
            "under-constrained-board", "unmatched-enclosure", "wrong-case-model",
            "wrong-enclosure",
        }),
    ),
    Family.CANDIDATES: Prose(
        means="A finite tie the tool cannot break for you.",
        routes=(
            "Choose one of the answers offered. Every candidate was computed from "
            "your inputs, and nothing outside the list is on offer."
        ),
        codes=frozenset({"ambiguous-enclosure", "empty-group"}),
    ),
    Family.BOARD: Prose(
        means="The board file looks like the problem, rather than the panel.",
        routes=(
            "Re-export the board, or supply the file that was meant. Widening a "
            "tolerance can hide a wrong board file; it does not fix one."
        ),
        codes=frozenset({"no-correspondence", "no-substrate", "unreadable-board"}),
    ),
    Family.MODEL: Prose(
        means="The kernel failed on geometry it was handed.",
        routes=(
            "Supply a different model. Redrawing the artwork will not help, "
            "because nothing was wrong with what was asked."
        ),
        codes=frozenset({"degenerate-geometry"}),
    ),
    Family.FIT: Prose(
        means="What the parts do when they are put together.",
        routes=(
            "Read the register on each line. A clash is this tool's deliverable "
            "rather than proof that a placement is wrong, but some of these say "
            "the pedal cannot be assembled as drawn, and those say so explicitly."
        ),
        codes=frozenset({
            "ambiguous-placement", "cannot-enter", "clash",
            "enclosure-too-shallow", "every-seating-clashes", "seated-short",
            "zero-clearance",
        }),
    ),
    Family.KNOWING: Prose(
        means="The tool assumed, bounded a search, or could not confirm something.",
        routes=(
            "Nothing is required of you. Each line states what was assumed, so "
            "you can disagree with it. These are never counted and mark no place."
        ),
        codes=frozenset({
            "case-model-unverified", "case-orientation-unverifiable",
            "inferred-enclosure", "multiple-boards", "seating-search-bounded",
            "unknown-enclosure",
        }),
    ),
}

#: The gravest register, by code. Every other fit code is a result to inspect,
#: unless it is an ERROR, which withheld an artefact.
_CANNOT_ASSEMBLE = frozenset({"enclosure-too-shallow", "every-seating-clashes"})

#: The row each finding a row can answer goes to. Absent codes have none: a
#: refusal names a change to the drawing, and information marks no place.
REMEDIES: dict[str, Remedy] = {
    "ambiguous-pairing": Remedy(Place.BOARDS, "panel_reference"),
    "grid-ambiguous": Remedy(Place.DRILLING, "grid_mm"),
    "grid-too-fine": Remedy(Place.DRILLING, "grid_mm"),
    "nesting-truncated": Remedy(Place.ARTWORK, "form_depth"),
    "under-constrained-board": Remedy(Place.BOARDS, "panel_reference"),
    "unmatched-enclosure": Remedy(Place.ENCLOSURE, "case"),
    "wrong-case-model": Remedy(Place.ENCLOSURE, "case_model"),
    "wrong-enclosure": Remedy(Place.ENCLOSURE, "case"),
    "ambiguous-enclosure": Remedy(Place.ENCLOSURE, "case"),
    "empty-group": Remedy(Place.BOARDS, "panel_reference"),
}

#: A part landing a stated offset from its nearest hole: the tolerance is the
#: setting that decides whether it pairs, so that is where the jump lands.
NEAR_MISS = Remedy(Place.BOARDS, "match_tolerance_mm")

#: A second honest route, in the finding's own sentence. One membership keeps
#: siblings consistent; this keeps the classification honest where there are
#: genuinely two answers.
_SECONDARY: dict[str, str] = {
    "off-grid": "or set the grid to the pitch the artwork actually uses",
    "no-correspondence": "or widen the match tolerance, if the board file is right",
    "unknown-enclosure": "or draw a catalogue case, if one was meant",
    "unmatched-enclosure": "or redraw the outline, if a catalogue case was meant",
    "ambiguous-pairing": "or narrow the match tolerance, if both parts belong",
}

_NEAR_MISS_SECONDARY = "or move the footprint in the artwork, if the tolerance is right"

#: Every code this table classifies, including the one routed by payload.
CODES: frozenset[str] = frozenset(
    code for prose in FAMILIES.values() for code in prose.codes
) | {"unmatched-part"}


def _near_miss(diagnostic: Diagnostic) -> bool:
    """Whether this is ``unmatched-part``'s offset shape rather than its axisless one."""
    return diagnostic.code == "unmatched-part" and any(
        key == "offset_nm" for key, _value in diagnostic.data
    )


def family_of(diagnostic: Diagnostic) -> Family:
    """The one family this finding belongs to, reading its payload where needed.

    ``unmatched-part`` is raised with an offset from a nearest hole -- a
    near miss the tolerance or the artwork could explain -- and without
    one, for a part that yields no axis at all: a board export missing
    something. A code the table does not know falls to information; the
    completeness test is what keeps that branch unreachable.
    """
    if diagnostic.code == "unmatched-part":
        return Family.SETTING if _near_miss(diagnostic) else Family.BOARD
    for family, prose in FAMILIES.items():
        if diagnostic.code in prose.codes:
            return family
    return Family.KNOWING


def register_of(diagnostic: Diagnostic) -> Register | None:
    """How gravely to state a fit finding, or ``None`` outside that family."""
    if family_of(diagnostic) is not Family.FIT:
        return None
    if diagnostic.code in _CANNOT_ASSEMBLE:
        return Register.DO_NOT_BUILD
    if diagnostic.severity is Severity.ERROR:
        return Register.WITHHELD
    return Register.INSPECT


def remedy_of(diagnostic: Diagnostic) -> Remedy | None:
    """The row that answers this finding, where one does."""
    if _near_miss(diagnostic):
        return NEAR_MISS
    return REMEDIES.get(diagnostic.code)


def secondary_of(diagnostic: Diagnostic) -> str:
    """A second honest route for this finding, or the empty string."""
    if _near_miss(diagnostic):
        return _NEAR_MISS_SECONDARY
    return _SECONDARY.get(diagnostic.code, "")
