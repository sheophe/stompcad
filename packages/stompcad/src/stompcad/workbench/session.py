"""The workbench's whole state, with no Textual in it.

Which place is selected, what has been edited, what that made stale,
whether a run may start, what it is doing and what it found: every spec
rule lives here, so it is driven headless and Textual modules stay drawing
alone. Nothing here touches the filesystem or starts a run -- a caller
hands in what it read and ran, and gets back what to draw, which is what
lets one test file cover decisions 4, 5, 7, 10, 12, 14 and 17 without a
pilot.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stompmodel.diagnostics import Diagnostic

from .. import drive, stale
from ..plan import RunPlan
from ..present import Choice
from ..readiness import Blocker, Readiness, readiness
from ..settings import Discovery, Origin, Provenance, Resolved, Settings, disagreement
from .findings import Finding, classify, counted
from .keys import CONFIGURATION, SIDEBAR_ORDER, Place, neighbour

if TYPE_CHECKING:  # ``cli`` imports the application, which imports this module
    from ..cli import Resolution

__all__ = ["Locked", "Refused", "Phase", "PendingGap", "Row", "Session", "FITS"]

#: Decision 2's two labels, and the reason neither is persisted: the manifest
#: holds no hashes, so the workbench cannot know an existing artefact was made
#: from the declarations now on screen -- and must not imply it.
FOUND = "already on disk; this session has not made or verified it"
MADE = "made by this run"

#: The two blockers ``readiness`` cannot raise: both are found before a
#: ``Settings`` exists, so an edit carries them forward rather than deriving
#: them. Recomputing readiness alone would leave a refused run marked nowhere.
_STANDING = (Blocker.REFUSED_VALUE, Blocker.UNREADABLE_PROJECT)

#: The ranks the artwork's own fit may answer over: nothing said, or the last
#: thing this rule itself said. A part from the project or from the user
#: outranks a measurement, so reading the outline never overrules a person.
_INFERABLE = (Origin.DEFAULT, Origin.DISCOVERED)

#: What a row states when the outline is what answered it. Compared as well as
#: shown: it is how a withdrawal tells this rule's own answer from anybody else's.
FITS = "fits the reference outline"


class Locked(Exception):
    """An edit refused because a run holds the place. Decision 5.

    Raised rather than ignored: a refusal nobody can observe is
    indistinguishable from an edit that silently did nothing, and the guard
    is only worth having if a test can see it work.
    """


class Refused(Exception):
    """A value the tool that consumes it will not accept. Not a workbench rule.

    The message is that tool's own sentence, reaching the row that carried
    the value. Restating the rule here would give one question two answers,
    which is how byte identity drifts.
    """


class Phase(Enum):
    """What the run is doing, which is what decides who may edit what."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class PendingGap:
    """The one gap a paused run is waiting on. Never a queue -- decision 12.

    ``choice`` is the picker where the code offers one. ``None`` means the
    answering place carries a focused "Continue run" row instead, which is
    the only control a place otherwise closed to editing gains.
    """

    code: str
    step: str
    place: Place
    choice: Choice | None


@dataclass(frozen=True, slots=True)
class Row:
    """One sidebar row's three independent states, plus what to call it.

    ``reached`` is the left marker and only the five configuration places
    carry it; ``attention`` is the right marker and marks the exception;
    ``count`` is Findings' own channel and is ``None`` everywhere else.
    """

    place: Place
    label: str
    selected: bool
    reached: bool
    attention: bool
    count: int | None


class Session:
    """One project open in the workbench, and everything true about it now."""

    def __init__(
        self,
        resolution: Resolution,
        resolver: Callable[[Path], Resolution] | None = None,
        validator: Callable[[Settings, str], None] | None = None,
    ) -> None:
        self._resolver = resolver
        self._validator = validator
        self._place = Place.PROJECT
        self._phase = Phase.IDLE
        self._gap: PendingGap | None = None
        self._planned: frozenset[str] = frozenset()
        self._completed: frozenset[str] = frozenset()
        self._changed: frozenset[str] = frozenset()
        self._findings: tuple[Finding, ...] = ()
        self._written: frozenset[Path] = frozenset()
        self._exit_code = 0
        self._adopt(resolution)

    def _adopt(self, resolution: Resolution) -> None:
        """Take a resolution whole, discarding everything the old one implied.

        A new panel is a new project: its stale set, its findings and its
        written paths belong to the project that is gone. The selected place
        survives, because the user is still standing where they were.
        """
        self._settings = resolution.settings
        self._project = resolution.project
        self._notes = resolution.notes
        self._obstacle = resolution.obstacle
        self._panel_candidates = resolution.panel_candidates
        self._blockers = resolution.blockers
        self._standing = tuple(
            blocker for blocker in resolution.blockers.blockers if blocker[0] in _STANDING
        )
        self._planned = frozenset()
        self._completed = frozenset()
        self._changed = frozenset()
        self._findings = ()
        self._written = frozenset()
        self._designators: dict[int, tuple[str, ...]] = {}
        self._fits: tuple[str, ...] = ()
        self._fit_pending = False

    # -- what there is to look at -----------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def place(self) -> Place:
        return self._place

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def gap(self) -> PendingGap | None:
        return self._gap

    @property
    def notes(self) -> tuple[str, ...]:
        return self._notes

    @property
    def obstacle(self) -> str | None:
        return self._obstacle

    @property
    def panel_candidates(self) -> tuple[Path, ...]:
        return self._panel_candidates

    @property
    def fits(self) -> tuple[str, ...]:
        """Every part the artwork's outline admits; empty narrows nothing."""
        return self._fits

    @property
    def fit_pending(self) -> bool:
        """Whether a read is outstanding, so an unanswered part is not yet news."""
        return self._fit_pending

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self._findings

    @property
    def exit_code(self) -> int:
        return self._exit_code

    @property
    def designators(self) -> tuple[str, ...]:
        """Every designator any board carries, in name order, without repeats."""
        return tuple(sorted({name for names in self._designators.values() for name in names}))

    # -- moving ------------------------------------------------------------

    def go(self, place: Place) -> None:
        """Select a place. Always allowed: every place stays readable."""
        self._place = place

    def step_place(self, forward: bool) -> None:
        """``[`` and ``]``, which resolve to the same change a letter makes."""
        self._place = neighbour(self._place, forward)

    # -- changing ----------------------------------------------------------

    def may_edit(self, place: Place) -> bool:
        """Whether this place accepts an edit right now. Decisions 5 and 12."""
        if self._phase is Phase.RUNNING:
            return False
        if self._phase is Phase.PAUSED:
            return self._gap is not None and place is self._gap.place
        return True

    def set(self, place: Place, field: str, value: Any) -> None:
        """Record one value the user set, and what the project said instead.

        ``Origin.USER`` is this method's own rank: above the project and
        above an argument, because it is the most recent thing anybody said,
        which is also why this is the rank that records a disagreement.
        """
        declared = self._project.values.get(place.value, {}).get(field)
        self._replace_value(
            place,
            field,
            Resolved(value, Provenance(Origin.USER), disagreement(declared, value)),
        )

    def adopt(self, place: Place, field: str, found: Discovery[Any]) -> None:
        """Take a value the tool found, recording that it was found rather than set.

        Decision 7: the origin a row states must be the rank that supplied
        it, and a cached model is discovered however it was asked for.
        Discovery sits below the project, so it records no disagreement.
        """
        self._replace_value(
            place, field, Resolved(found.value, Provenance(Origin.DISCOVERED, found.detail))
        )

    def begin_fit(self) -> None:
        """Say a read of the artwork is outstanding. Decision 1."""
        self._fit_pending = True

    def record_fit(self, parts: Sequence[str]) -> None:
        """What the outline admits, and what that answers.

        Exactly one part answers an unanswered question; anything else
        withdraws an answer this rule gave earlier, because a fit that no
        longer holds is a wrong answer rather than an old one. Re-reading
        the same fit changes nothing, so opening a project cannot make the
        run it just finished stale.
        """
        # What the artwork says, and whether a read is still owed: true
        # regardless of the guard below, since a run holding the place shut
        # does not make the picker's narrowed list stop being what fits.
        self._fits = tuple(parts)
        self._fit_pending = False
        case = self._settings.enclosure.case
        if case.provenance.origin not in _INFERABLE or not self.may_edit(Place.ENCLOSURE):
            return
        if len(self._fits) == 1:
            if case.value == self._fits[0] and case.provenance.detail == FITS:
                return
            self.adopt(Place.ENCLOSURE, "case", Discovery(self._fits[0], FITS))
            return
        if case.provenance.detail == FITS:
            self._replace_value(
                Place.ENCLOSURE, "case", Resolved(None, Provenance(Origin.DEFAULT))
            )

    def _replace_value(self, place: Place, field: str, resolved: Resolved[Any]) -> None:
        """One value, at whatever rank supplied it, put in force.

        The field is added to the change set, which is what makes the steps
        reading it stale, and readiness is asked again. The consuming tool's
        check runs before either is touched, so a refused value invalidates
        nothing -- which is why every rank arrives through here.
        """
        if place not in CONFIGURATION:
            raise ValueError(f"{place.value} holds no values to set")
        if not self.may_edit(place):
            raise Locked(f"{place.value} does not accept an edit while a run is active")
        record = getattr(self._settings, place.value)
        previous = self._settings
        self._settings = replace(
            self._settings, **{place.value: replace(record, **{field: resolved})}
        )
        if self._validator is not None:
            try:
                self._validator(self._settings, place.value)
            except Exception as failure:  # the consuming tool's own refusal
                self._settings = previous
                raise Refused(str(failure)) from failure
        self._changed = self._changed | {field}
        self._restate(place)

    def _restate(self, place: Place) -> None:
        """Ask a standing refusal again, now the place that owns it has answered.

        That place's own checks are what refused, and ``_replace_value`` has
        just run them over the value now in force and seen them pass, so the
        refusal is spent. An unreadable project is not: editing a value does
        not make the file readable, and only adopting the project again can.
        Decision 4 needs the marker, the statement and ``may_run`` to move
        together, which is why all three read this one set.
        """
        kept = tuple(
            blocker for blocker in self._standing
            if not (blocker[0] is Blocker.REFUSED_VALUE and blocker[1] == place.value)
        )
        spent = tuple(blocker for blocker in self._standing if blocker not in kept)
        self._standing = kept
        if any(self._obstacle == blocker[2] for blocker in spent):
            self._obstacle = None
        self._blockers = Readiness(kept + readiness(self._settings).blockers)

    def adopt_panel(self, path: Path) -> None:
        """Start the project a typed path names. Decision 6's blocked start."""
        if self._resolver is None:
            raise Locked("this session cannot resolve a different panel")
        self._adopt(self._resolver(path))

    # -- what a change invalidated ----------------------------------------

    def invalidate(self, place: Place, *fields: str) -> None:
        """Mark this place's fields changed without changing them. Decision 10.

        `Ctrl+L` says the artwork on disk is not the artwork the last run
        read. Nothing the project declares has changed, so nothing is set --
        but every step reading the panel is stale, and that is the same
        statement an edit makes. Which is why a run refuses it too: this is
        the bookkeeping ``credit`` and a resume reason about.
        """
        if not self.may_edit(place):
            raise Locked(f"{place.value} does not accept an edit while a run is active")
        self._changed = self._changed | frozenset(fields)

    def stale(self) -> frozenset[str]:
        """The steps a resume would run, derived from the driver's own tables."""
        return drive.invalidated(self._changed, self._plan())

    def _plan(self) -> RunPlan:
        """The steps a run of this project would take, which its boards decide.

        Decision 4 derives the marker and the resume from one structure, so
        both ask the driver what a run over these values covers. A project
        with no boards has no dock half, and a roadmap waiting on a step it
        will never run reports it stale for ever.
        """
        return drive.plan_for(self._settings.boards.boards.value)

    def roadmap(self) -> Place | None:
        """The earliest place owning a change, or ``None`` when nothing changed."""
        name = stale.earliest_place(self._changed)
        return None if name is None else Place(name)

    def reached(self, place: Place) -> bool:
        """Whether the last run got this place's work done and it still stands.

        Derived from the same two facts a resume is: what the run credited,
        less what a change has since invalidated. There is no second thing
        to keep in step, which is decision 4's whole requirement.
        """
        if place not in CONFIGURATION:
            return False
        expected = drive.steps_of_place(place.value) & self._planned
        return bool(expected) and expected <= (self._completed - self.stale())

    # -- whether a run may start ------------------------------------------

    def ready(self) -> Readiness:
        return self._blockers

    def may_run(self) -> bool:
        """Decision 17's matrix, decision 9's unreadable project, and the read.

        A fit still outstanding is an unanswered question like any other: the
        part it is about to supply is an input the run would otherwise take
        without it.
        """
        return (
            self._obstacle is None
            and self._blockers.ready
            and not self._fit_pending
            and self._phase in (Phase.IDLE, Phase.DONE)
        )

    def statement(self) -> str:
        """The `Project` place's one line: the reassurance, or what stands in the way."""
        if self._obstacle is not None:
            return self._obstacle
        if self._phase is Phase.RUNNING:
            return "Running."
        if self._phase is Phase.PAUSED and self._gap is not None:
            return f"Waiting for you in {self._gap.place.value.capitalize()}."
        if self._blockers.ready:
            if self._fit_pending:
                return "Reading the artwork to see which enclosures it fits."
            return "Everything needed is here. Press Enter to run."
        return "; ".join(sentence for _blocker, _place, sentence in self._blockers.blockers)

    def attention(self, place: Place) -> bool:
        """Whether this place holds a gap the run cannot proceed past.

        Findings never marks: it carries a count instead, so a place marked
        here is always one a builder can do something about.
        """
        if place is Place.FINDINGS:
            return False
        blocked = {name for _blocker, name, _sentence in self._blockers.blockers}
        return place.value in blocked or place in self.finding_places()

    def finding_places(self) -> frozenset[Place]:
        """Every place holding a finding's remedy; worth-knowing findings have
        none, so they mark nothing.
        """
        return frozenset(
            finding.place for finding in self._findings if finding.place is not None
        )

    def rows(self) -> tuple[Row, ...]:
        """The sidebar, as three independent states per row."""
        count = counted(self._findings)
        return tuple(
            Row(
                place=place,
                label=place.value.capitalize(),
                selected=place is self._place,
                reached=self.reached(place),
                attention=self.attention(place),
                count=count if place is Place.FINDINGS else None,
            )
            for place in SIDEBAR_ORDER
        )

    # -- the run as an event ----------------------------------------------

    def start_run(self, resuming: bool) -> None:
        """Bind the run to the steps it will take. Decisions 5, 10 and 17.

        A resume runs the stale set and keeps the credit of what it skips; a
        first run takes every step this project's own plan holds. Which of
        the two it is depends on there being a driver to spend, which the
        application knows and this does not.
        """
        planned = (
            self.stale() if resuming else frozenset(step.key for step in self._plan().steps)
        )
        self.begin_run(planned, fresh=not resuming)

    def begin_run(self, planned: frozenset[str], fresh: bool = True) -> None:
        """A run has started over these steps; nothing is editable until it ends.

        A resume passes ``fresh=False``: the steps it skipped keep their
        credit, because that is why they were skipped, while the steps it is
        about to run lose theirs -- or the run before would answer for work
        this one has not done. A fresh run forgets everything, because a
        different plan's credit is not this plan's.
        """
        self._phase = Phase.RUNNING
        self._gap = None
        if fresh:
            self._planned = planned
            self._completed = frozenset()
        else:
            self._planned = self._planned | planned
            self._completed = self._completed - planned

    def credit(self, step: str) -> None:
        """One step completed under the values now in force.

        A change clears once every step it *invalidated* has run, not every
        step that reads it: ``grid_mm`` is read by ``quantise`` alone, so
        clearing it there would report the drill and write steps it also
        invalidated as fresh while they still hold that work.
        """
        self._completed = self._completed | {step}
        self._changed = frozenset(
            field
            for field in self._changed
            if not (drive.invalidated(frozenset({field})) & self._planned) <= self._completed
        )

    def pause(self, gap: PendingGap) -> None:
        """Stop for one gap, and go to the place that answers it. Decision 12."""
        self._phase = Phase.PAUSED
        self._gap = gap
        self._place = gap.place

    def resumed(self) -> None:
        """The answer was committed, which *is* the continuation."""
        self._phase = Phase.RUNNING
        self._gap = None

    def finish_run(self, code: int) -> None:
        """The run ended; its code is the process's until another run earns one."""
        self._phase = Phase.DONE
        self._gap = None
        self._exit_code = code

    def record_findings(self, diagnostics: Sequence[Diagnostic]) -> None:
        """What the run found, classified into a family, a remedy and a register."""
        self._findings = classify(diagnostics)

    def record_designators(self, designators: Mapping[int, tuple[str, ...]]) -> None:
        """Each board's own names, so `panel_reference` becomes a list to tick.

        Absent before a run, because they arrive with ``read boards``. That
        is why the expression is typed until a run has read a board and
        ticked afterwards -- and why the saved result is the expression
        rather than the ticks.
        """
        self._designators = dict(designators)

    def record_written(self, paths: Sequence[Path]) -> None:
        """Every artefact this session actually wrote. Never persisted -- decision 2."""
        self._written = self._written | frozenset(paths)

    def label_for(self, path: Path, exists: bool) -> str:
        """What the `Output` place says about one artefact. Decision 2.

        Three states and not two: a file this session wrote, a file that was
        already there, and a file that does not exist. The middle one is the
        reason this method exists -- it must never read as current.
        """
        if path in self._written:
            return MADE
        return FOUND if exists else "not made yet"
