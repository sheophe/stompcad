"""What a run's values are, where each came from, and what disagrees.

Spec decisions 6 and 7: resolution has four ranks and every value reports
its origin, because an artefact must never be quietly attributable to the
wrong settings. A leaf module by design -- it imports nothing from this
package, so ``drive`` may import it without a cycle, and nothing here
knows what a step does with a value.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar

from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.model import CaseFace

__all__ = [
    "Origin",
    "Provenance",
    "Discovery",
    "Resolved",
    "pick",
    "Artwork",
    "Enclosure",
    "Drilling",
    "BoardSettings",
    "OutputSettings",
    "Settings",
    "DEFAULTS",
]

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


def _as_flag_string(value: object) -> object:
    """An ``Enum``'s own ``.value`` -- the string a flag uses -- not its member name.

    ``str(CaseFace.BOX)`` is ``"CaseFace.BOX"`` with no custom ``__str__``
    declared; every row otherwise states the flag's own string, so this is
    the one place that has to know an enum from any other value.
    """
    return value.value if isinstance(value, Enum) else value


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
        stated = f"{_as_flag_string(self.value)}, {self.provenance.describe()}"
        if self.project is None:
            return stated
        return f"{stated} — the project says {_as_flag_string(self.project)}"


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


@dataclass(frozen=True, slots=True)
class Artwork:
    """The `a` place: the file, the layers it names, and how deep to look."""

    panel: Resolved[Path | None]
    drill_layer: Resolved[str]
    reference_layer: Resolved[str]
    form_depth: Resolved[int]

    def rows(self) -> Iterator[tuple[str, str]]:
        yield "panel", self.panel.describe()
        yield "drill layer", self.drill_layer.describe()
        yield "reference layer", self.reference_layer.describe()
        yield "form depth", self.form_depth.describe()


@dataclass(frozen=True, slots=True)
class Enclosure:
    """The `e` place: which box, which model of it, and which face is drilled."""

    case: Resolved[str | None]
    case_model: Resolved[Path | None]
    case_face: Resolved[CaseFace]
    case_margin_mm: Resolved[float]

    def rows(self) -> Iterator[tuple[str, str]]:
        yield "case", self.case.describe()
        yield "case model", self.case_model.describe()
        yield "drilled face", self.case_face.describe()
        yield "clearance margin", self.case_margin_mm.describe()


@dataclass(frozen=True, slots=True)
class Drilling:
    """The `d` place: the grid, the drills that exist, and the drawing's title."""

    grid_mm: Resolved[float]
    grid_warn_mm: Resolved[float | None]
    drill_standard: Resolved[str]
    drill_sizes: Resolved[str | None]
    no_drill_sizes: Resolved[str | None]
    title: Resolved[str]

    def rows(self) -> Iterator[tuple[str, str]]:
        yield "grid", self.grid_mm.describe()
        yield "warn over", self.grid_warn_mm.describe()
        yield "drill standard", self.drill_standard.describe()
        yield "stocked sizes", self.drill_sizes.describe()
        yield "excluded sizes", self.no_drill_sizes.describe()
        yield "drawing title", self.title.describe()


@dataclass(frozen=True, slots=True)
class BoardSettings:
    """The `b` place: the boards, what holds them to the panel, and the search."""

    boards: Resolved[tuple[Path, ...]]
    panel_reference: Resolved[str]
    match_tolerance_mm: Resolved[float | None]
    seat_pitch_max_mm: Resolved[float]
    seat_pitch_min_mm: Resolved[float]

    def rows(self) -> Iterator[tuple[str, str]]:
        yield "boards", self.boards.describe()
        yield "panel references", self.panel_reference.describe()
        yield "match tolerance", self.match_tolerance_mm.describe()
        yield "seat step, coarse", self.seat_pitch_max_mm.describe()
        yield "seat step, fine", self.seat_pitch_min_mm.describe()


@dataclass(frozen=True, slots=True)
class OutputSettings:
    """The `o` place: what to make, and where each artefact goes."""

    targets: Resolved[tuple[tuple[str, Path], ...]]

    def rows(self) -> Iterator[tuple[str, str]]:
        yield "artefacts", self.targets.describe()


@dataclass(frozen=True, slots=True)
class Settings:
    """Every resolved value, grouped by the place that owns it.

    The workbench's view. ``drive.RunOptions`` is derived from this in one
    direction only: the driver's tables key on flat field names, and a
    nested record would break ``_refuse_unhonoured`` and ``revision_for``
    at once.
    """

    artwork: Artwork
    enclosure: Enclosure
    drilling: Drilling
    boards: BoardSettings
    output: OutputSettings

    def places(self) -> Iterator[tuple[str, Iterator[tuple[str, str]]]]:
        """Each place's name and its rows, in the sidebar's own order."""
        yield "artwork", self.artwork.rows()
        yield "enclosure", self.enclosure.rows()
        yield "drilling", self.drilling.rows()
        yield "boards", self.boards.rows()
        yield "output", self.output.rows()

    @staticmethod
    def of_defaults(panel: Path) -> Settings:
        """Every value at rank four, for a panel nobody has said anything about."""
        return replace(DEFAULTS, artwork=replace(DEFAULTS.artwork, panel=_at_default(panel)))


def _at_default(value: _T) -> Resolved[_T]:
    """A value nobody supplied, discovered or declared."""
    return Resolved(value, Provenance(Origin.DEFAULT))


# ``_at_default(None)`` below still type-checks as, say, ``Resolved[str |
# None]``: mypy solves the call's type variable from the keyword's declared
# field type, not from the literal ``None`` alone, so no ``cast`` or
# ``type: ignore`` is needed for any optional row.


#: Rank four, and the one statement of it. Each value is the default the tool
#: that consumes it uses from its own command line; ``test_settings`` compares
#: them against those parsers rather than against a copy, because a default
#: that silently stops matching breaks byte identity and nothing else.
DEFAULTS = Settings(
    artwork=Artwork(
        # ``None``, not ``Path()``: an empty path stringifies to "." and is
        # therefore truthy, so a no-panel project would read as ready.
        panel=Resolved[Path | None](None, Provenance(Origin.DEFAULT)),
        drill_layer=_at_default("Drill"),
        reference_layer=_at_default("Background"),
        form_depth=_at_default(DEFAULT_FORM_DEPTH),
    ),
    enclosure=Enclosure(
        case=_at_default(None),
        case_model=_at_default(None),
        case_face=_at_default(CaseFace.BOX),
        case_margin_mm=_at_default(1.0),
    ),
    drilling=Drilling(
        grid_mm=_at_default(0.25),
        grid_warn_mm=_at_default(None),
        drill_standard=_at_default(DEFAULT_STANDARD),
        drill_sizes=_at_default(None),
        no_drill_sizes=_at_default(None),
        title=_at_default(""),
    ),
    boards=BoardSettings(
        boards=_at_default(()),
        panel_reference=_at_default(""),
        match_tolerance_mm=_at_default(None),
        seat_pitch_max_mm=_at_default(2.0),
        seat_pitch_min_mm=_at_default(0.05),
    ),
    output=OutputSettings(targets=_at_default(())),
)
