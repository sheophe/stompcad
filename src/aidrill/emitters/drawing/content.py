"""Facts the sheet states, independent of any backend that renders it.

Both drawing emitters state the hole schedule, tool summary, notes, and title
block claims from these functions, so two sheets of one panel cannot disagree
about what the panel is. Text-fitting helpers live here for the same reason:
a truncation rule is a fact about the sheet, not about SVG or PDF specifically.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...model import Diagnostic, DrillData, EnclosureMatch, Hole, Severity
from ...pipeline import DRILL_STANDARDS
from ...units import Nanometre, format_nm

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the checker
    from .layout import Layout

__all__ = [
    "CHAR_RATIO",
    "DUP_CODE",
    "PayloadValue",
    "SNAP_STAGE",
    "GRID_PARAMETER",
    "POSITION_DECIMALS",
    "FOOTPRINT_DECIMALS",
    "DIAMETER_STAGE",
    "STANDARD_PARAMETER",
    "TITLE_BLOCK_COLUMNS",
    "TITLE_LABEL_FONT",
    "TITLE_VALUE_FONT",
    "TITLE_CELL_PADDING",
    "ABSENT",
    "capacity",
    "fits",
    "allot",
    "fit_font",
    "ScheduleRow",
    "ToolLine",
    "Note",
    "SheetText",
    "TitleField",
    "schedule_rows",
    "tool_summary",
    "note_lines",
    "title_cell_width",
    "title_fields",
    "grid_value",
    "grid_note",
    "millimetre_label",
    "diameter_label",
    "enclosure_note",
    "candidate_list",
    "designator",
    "flagged_holes",
    "is_flagged",
]

#: Conservative glyph-advance estimate, as a fraction of the font size. Used to
#: truncate strings to their box. Deliberately wider than a real sans face so
#: nothing is clipped by the border.
CHAR_RATIO = 0.62

DUP_CODE = "duplicate-hole"

#: One value out of a ``Diagnostic.data`` payload, spelled here so the two
#: functions that pass one around agree with the model rather than with each
#: other. Kept as wide as the model declares it: narrowing is what would drop a
#: ring in silence — see :func:`flagged_holes`.
PayloadValue = float | int | str | tuple[int, ...]

#: The ``StageRun`` name the title block's grid is read from, and the parameter
#: within it. Names the *record*, not the class: the emitter reads provenance and
#: has no import of, or opinion about, which stage wrote it.
SNAP_STAGE = "snap"
GRID_PARAMETER = "grid_nm"

#: How many decimals of a millimetre a *position* — a schedule cell, a dimension
#: label, an overall size — is printed to. Three, and not a matter of taste:
#: ``SnapPositions.MICRON_NM`` floors the grid at a micron precisely because the
#: drill file and this sheet both print three decimals, so two grid points the
#: model holds apart cannot come out as one number on the sheet a machinist
#: reads. Printing two here would give that floor away and let 18.000 and 18.001
#: — two coordinates in the drill file — read as one on the drawing.
#:
#: A diameter is not on this list: how a bit is spelled belongs to the drill
#: standard that chose it (see :func:`diameter_label`), and a fractional bit has
#: no honest decimal spelling at any precision.
POSITION_DECIMALS = 3

#: The catalogue footprint's precision, which is Hammond's own: the per-part
#: drawings publish 0.05 mm and the 1590B sheet prints ``112.40 [4.425]``. This
#: is the number the operator orders the box by, so it is printed the way the
#: datasheet they will check it against prints it.
FOOTPRINT_DECIMALS = 2

#: The same idiom for the schedule's diameter spelling: the ``StageRun`` name
#: the drill standard is read from, and the parameter within it. The standard
#: itself is looked up by name in ``DRILL_STANDARDS``, so the record stays a
#: name rather than 183 sizes.
DIAMETER_STAGE = "snap-diameters"
STANDARD_PARAMETER = "standard"

#: The ISO 7200 block's field grid and the sizes its cells are lettered at.
#: They live here because the cell a value is truncated to and the recommended
#: character count that truncates it are one decision about the same value.
TITLE_BLOCK_COLUMNS = 3
TITLE_LABEL_FONT = 1.8
TITLE_VALUE_FONT = 2.6
TITLE_CELL_PADDING = 1.5

#: Shown for a field ``aidrill`` has no source for. An em dash says the field
#: exists and is empty; a blank cell reads as one that failed to render.
ABSENT = "—"


def capacity(width: float, size: float) -> int:
    """Return the character capacity used by :func:`fits` at this size."""
    if width <= 0 or size <= 0:
        return 0
    return max(1, int(width / (CHAR_RATIO * size)))


def fits(text: str, size: float, width: float) -> str:
    """Truncate ``text`` so its estimated extent stays inside ``width``."""
    if width <= 0:
        return ""
    limit = capacity(width, size)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def allot(count: int, room: int) -> tuple[int, int]:
    """Allot visible items and leftovers, reserving an omission-marker line."""
    if count <= room:
        return count, 0
    shown = max(0, room - 1)
    return shown, count - shown


def fit_font(text: str, width: float, largest: float, smallest: float) -> float:
    if not text or width <= 0:
        return largest
    return max(smallest, min(largest, width / (CHAR_RATIO * len(text))))


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    """One line of the hole schedule, already formatted."""

    number: int
    x: str
    y: str
    diameter: str
    tool: str
    flagged: bool


@dataclass(frozen=True, slots=True)
class ToolLine:
    """One line of the tool summary: the sheet's copy of the drill file's table."""

    tool: str
    diameter: str
    quantity: int


@dataclass(frozen=True, slots=True)
class Note:
    """One numbered note, carrying the severity that colours it."""

    severity: Severity
    text: str


@dataclass(frozen=True, slots=True)
class SheetText:
    """The words an emitter's options contribute, separated from the emitter
    that supplied them."""

    title: str = ""
    drawing_no: str = ""
    company: str = "ARTIFACT INSTRUMENTS"
    issue_date: str = ""
    approved_by: str = ""
    creator: str = ""


@dataclass(frozen=True, slots=True)
class TitleField:
    """One ISO 7200 data field: its label, its value, and what the table says.

    ``limit`` is the recommended character count of Tables 1-3, or zero where
    the table recommends none; ``mandatory`` is the tables' own column.
    """

    name: str
    value: str
    limit: int
    mandatory: bool


def schedule_rows(data: DrillData) -> tuple[ScheduleRow, ...]:
    """Format every hole's schedule line, in the model's own hole order."""
    tools = data.tools()
    label = diameter_label(data)
    flagged = flagged_holes(data.diagnostics)
    return tuple(
        ScheduleRow(
            number=hole.index,
            x=format_nm(hole.x_nm, POSITION_DECIMALS),
            y=format_nm(hole.y_nm, POSITION_DECIMALS),
            diameter=label(hole.diameter_nm),
            tool=f"T{tools[hole.diameter_nm]}",
            flagged=is_flagged(hole, flagged),
        )
        for hole in data.holes
    )


def tool_summary(data: DrillData) -> tuple[ToolLine, ...]:
    """Format the tool table, ascending by size as ``DrillData.tools`` orders it."""
    counts = data.tool_counts()
    label = diameter_label(data)
    return tuple(
        ToolLine(tool=f"T{number}", diameter=label(diameter), quantity=counts[diameter])
        for diameter, number in data.tools().items()
    )


def note_lines(data: DrillData) -> tuple[Note, ...]:
    """Number every diagnostic, or state that none were raised."""
    notes = []
    for index, diagnostic in enumerate(data.diagnostics, start=1):
        prefix = {
            Severity.WARNING: "WARNING  ",
            Severity.ERROR: "ERROR  ",
        }.get(diagnostic.severity, "")
        notes.append(Note(diagnostic.severity, f"{index}. {prefix}{diagnostic.message}"))
    if not notes:
        notes.append(Note(Severity.INFO, "1. No diagnostics were raised for this panel."))
    return tuple(notes)


def title_cell_width(layout: Layout) -> float:
    """One field cell's width, which the rules and the truncation both read."""
    x0, _, x1, _ = layout.title_block
    return (x1 - x0) / TITLE_BLOCK_COLUMNS


def _capped(value: str, limit: int) -> str:
    """Hold a value to its table's recommended length; ``0`` means none given."""
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def title_fields(data: DrillData, text: SheetText, layout: Layout) -> tuple[TitleField, ...]:
    """The title block's fields, per ISO 7200 Tables 1-3.

    Every mandatory field appears whether or not a value is known, because a
    missing mandatory field and an empty one are different claims. Date of
    issue, approval person and creator are the three ``aidrill`` has no source
    for: it reads artwork, not an organisation, and reading a clock would make
    two runs over one panel disagree.
    """
    room = capacity(title_cell_width(layout) - 2 * TITLE_CELL_PADDING, TITLE_VALUE_FONT)
    source = data.source
    stated: tuple[tuple[str, str, int, bool], ...] = (
        ("LEGAL OWNER", text.company or ABSENT, 0, True),
        ("TITLE", text.title or "PANEL DRILL DRAWING", 25, True),
        ("IDENT NO", text.drawing_no or ABSENT, 16, True),
        ("DOC TYPE", "DRILL DRAWING", 30, True),
        ("DATE OF ISSUE", text.issue_date or ABSENT, 10, True),
        # Table 1's count is for the sheet number alone; this cell carries the
        # number and the total, which is the pair a reader checks a set against.
        ("SHEET", "1 / 1", 0, True),
        ("APPROVED", text.approved_by or ABSENT, 20, True),
        ("CREATOR", text.creator or ABSENT, 20, True),
        ("PAPER SIZE", layout.sheet.name, 4, False),
        ("SCALE", layout.scale_label, 0, False),
        ("UNITS", "mm", 0, False),
        ("HOLES", str(len(data.holes)), 0, False),
        ("ENCLOSURE", enclosure_note(data, room), 0, False),
        ("GRID", grid_value(data), 0, False),
        ("PROJECTION", "THIRD ANGLE — DO NOT SCALE", 0, False),
        ("SOURCE", source.path or ABSENT, 0, False),
        ("DRILL LAYER", source.drill_layer or ABSENT, 0, False),
        ("REFERENCE LAYER", source.reference_layer or ABSENT, 0, False),
    )
    return tuple(
        TitleField(name, _capped(value, limit), limit, mandatory)
        for name, value, limit, mandatory in stated
    )


def grid_note(data: DrillData) -> str:
    """State the recorded effective grid, or explicitly that none was recorded."""
    return f"GRID {grid_value(data)}"


def grid_value(data: DrillData) -> str:
    """The same fact as a title-block cell's value, under its own label."""
    run = data.last_run(SNAP_STAGE)
    grid_nm = None if run is None else run.get(GRID_PARAMETER)
    # ``StageRun`` payloads are deliberately generic. The model holds an ``_nm``
    # key to whole nanometres at construction — which is what rules out the
    # ``True`` that would otherwise have stamped the sheet "GRID 0.000 mm" — but
    # it admits a *tuple* of them, since one parameter in the pipeline is a table
    # of sizes. A table is not a pitch, and neither is a pitch of nothing, so
    # both get the same answer as no record at all. ``type(...) is int`` rather
    # than ``isinstance`` on the precedent the model sets.
    if type(grid_nm) is not int or grid_nm <= 0:
        return "NOT RECORDED"
    return f"{format_nm(Nanometre(grid_nm))} mm"


def millimetre_label(diameter_nm: Nanometre) -> str:
    """Format the ``⌀7.00 mm`` fallback used without a recorded standard."""
    return f"⌀{format_nm(diameter_nm, 2)} mm"


def diameter_label(data: DrillData) -> Callable[[Nanometre], str]:
    """Use the recorded drill standard's labels, falling back to millimetres."""
    run = data.last_run(DIAMETER_STAGE)
    name = None if run is None else run.get(STANDARD_PARAMETER)
    # ``StageRun`` payloads are generic, so a value that is not a name cannot
    # name a standard. This guard is for the type checker rather than for the
    # output — every ``ParameterValue`` is hashable, so ``get`` would return
    # ``None`` for a non-name anyway — and it is kept because the alternative is
    # a lookup whose key type is unchecked. Unlike ``grid_note``'s guard, which
    # is load-bearing: a tuple of pitches really would print there.
    if not isinstance(name, str):
        return millimetre_label
    standard = DRILL_STANDARDS.get(name)
    if standard is None:
        return millimetre_label
    return standard.label


def enclosure_note(data: DrillData, capacity: int) -> str:
    """State catalogue footprint, rotation and selected part or ordered candidates.

    Missing matches are explicit; candidate truncation reports the omitted count.
    """
    match = data.enclosure
    if match is None:
        return "ENCLOSURE NOT IDENTIFIED"
    size = (
        f"{format_nm(match.length_nm, FOOTPRINT_DECIMALS)} × "
        f"{format_nm(match.width_nm, FOOTPRINT_DECIMALS)} mm"
    )
    if match.rotated:
        size += " ROTATED"
    head = f"{match.family.upper()}  {size}  "
    if match.selected_part is not None:
        return head + f"PART {match.selected_part}"
    designators = [designator(part, match) for part in match.candidates]
    room = capacity - len(head) - len("CANDIDATES ")
    return head + "CANDIDATES " + candidate_list(designators, room)


def candidate_list(designators: Sequence[str], room: int) -> str:
    """Fit ordered candidates, ending with a counted ``+N MORE`` marker."""
    text = " / ".join(designators)
    for keep in range(len(designators), 0, -1):
        text = " / ".join(designators[:keep])
        if keep < len(designators):
            text += f" / +{len(designators) - keep} MORE"
        if len(text) <= room:
            break
    return text


def designator(part: str, match: EnclosureMatch) -> str:
    """Elide the family prefix only when a non-empty designator remains."""
    words = match.family.split()
    # A family of no words leaves ``series`` empty, which the test below then
    # answers correctly on its own: every string starts with "" and every
    # non-empty one differs from it, so the part comes back whole. No separate
    # guard for it, because a branch no input can distinguish is a branch no
    # test can pin.
    series = words[-1] if words else ""
    if part.startswith(series) and part != series:
        return part[len(series):]
    return part


def flagged_holes(diagnostics: Sequence[Diagnostic]) -> frozenset[PayloadValue]:
    """Return stable survivor identities named by ``duplicate-hole`` findings."""
    return frozenset(
        index
        for d in diagnostics
        if d.code == DUP_CODE and (index := d.get("hole_index")) is not None
    )


def is_flagged(hole: Hole, flagged: frozenset[PayloadValue]) -> bool:
    """Use stable identity, never geometry, to decide whether to draw a ring."""
    return hole.index in flagged
