"""Position quantisation: which grid point is this hole nearest?

A drawn hole centre comes back as −39.9906 when the designer meant −40. The
panel is manufactured on a grid, so the quantisation phase resolves that here,
once, and every emitter downstream sees the same numbers.

**The answer set is the grid, and the answer is exact by construction.** What
comes out is ``k * grid_nm`` for a whole ``k`` — not a measurement that has been
rounded, but one of the positions the panel can actually be drilled at. The only
question asked here is which of them is nearest.

**Nothing is rounded before that question is asked.** The measurement is scaled
to nanometres exactly, through `units.scaled_nm`, and only the quotient is
rounded. Quantising the measurement first would cost a full grid pitch on
0.1250004 mm: it becomes 125 000 nm, an exact tie the measurement never had, and
the tie-break then resolves a fabricated ambiguity instead of a real one.
`scaled_nm`'s own docstring has the arithmetic.

The raw measurement is never lost: ``Hole.raw`` keeps it, so a drawing can show
"−40.000 (raw −39.9906)" and any residual can be recomputed rather than
remembered.

**Snapping answers; it does not judge — the judging is a separate stage.** A
hole exactly halfway between two grid points gets one of them from ``round``'s
parity rule, which is deterministic and carries no information about what the
designer meant. The hole is snapped either way, because the position is not
wrong and there is nothing here to withhold. But artwork drawn on 0.5 mm and run
at ``--grid 1.0`` puts *every* hole on a midpoint, and the tool used to drill it
without a word. `ReviewGridTies` is the finding that says so, and it lives in
this module because "tied" is a fact about the pitch and there must be exactly
one definition of it — while being a ``Stage`` rather than a second method on
the quantiser, for a reason its own docstring gives: the verdict has to be about
the holes the emitters receive, and that is not the set the quantiser sees.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN
from typing import ClassVar

from ..formatting import format_mm
from ..model import Diagnostic, DrillData, Hole, RawHole, StageRun
from ..tolerance import within
from ..units import format_nm, nm_from_mm, scaled_nm

__all__ = ["SnapPositions", "ReviewGridTies"]

#: The key ``SnapPositions`` records its effective pitch under, and the key
#: `ReviewGridTies` reads it back from. Spelled once, because the two are one
#: conversation: a reader looking under a name the writer stopped using would
#: find no pitch and silently review nothing.
_GRID_PARAMETER: str = "grid_nm"

#: The finest grid a drilled panel can be described on. The drill file and the
#: drawing both print three decimals of a millimetre, so below a micron the
#: rendering stops being injective: two grid points the model holds apart can
#: come out as one coordinate on the sheet a machinist reads. (Not every
#: sub-micron pair collides — a finer grid merely *admits* collisions, which is
#: enough, because nothing here can tell which panel is about to be drawn.)
MICRON_NM: int = 1_000


class SnapPositions:
    """Snap a measured hole centre onto the nearest point of a declared grid.

    ``warn_over_nm`` defaults to a quarter of the pitch: a hole that has to move
    further than that was probably not drawn on the grid at all, which is worth
    telling the operator about.

    **The grid is a whole number of microns.** The floor is the constant above;
    the quantisation to whole microns on top of it is what keeps every pitch
    even, so a midpoint is an integer and can be tested for by exact equality
    rather than by a band somebody has to choose. A pitch below the floor is
    clamped rather than refused — the operator asked for finer positioning than
    an artifact can render, and giving them the finest that renders is a better
    answer than refusing to drill the panel. There is no way to switch snapping
    off: a hole has to be drilled somewhere, and "wherever the artwork said" is
    a position no bit ever lands on twice.

    Both numbers are checked once, in the constructor, on the precedent
    ``DrillStandard.__post_init__`` sets and for its reason: the alternative is
    noticing at every use, or — as happened here — not noticing at all. A pitch
    in whole nanometres cannot *be* ``nan`` or ``inf``, but an annotation is not
    a check, and the two of them are what the guard is for. ``--grid=nan`` got
    past a ``grid <= 0`` gate, because every comparison against NaN is False,
    and ``round(x / nan)`` then raised ``ValueError`` out of the phase —
    uncaught, so the process exited **1**, the code the CLI reserves for
    "warnings present" and a wrapper reads as a run worth trusting. ``inf`` did
    not even raise: ``round(x / inf) * inf`` is ``0 * inf``, so every hole
    snapped to ``nan`` and a drill file was written with ``XnanYnan`` in it.
    Both values are floats, and so is every other way of arriving here without
    crossing ``units``, which is why the guard now asks the question the rest of
    the model asks: is this a plain ``int``? ``type(x) is int`` and not
    ``isinstance``, because ``bool`` is an ``int`` in Python and ``True`` is a
    one-nanometre grid no report would make look wrong.

    A negative or NaN ``warn_over_nm`` fails the other way, reporting every hole
    on the panel as off-grid including the ones that did not move.
    """

    name: ClassVar[str] = "snap"

    def __init__(self, grid_nm: int, warn_over_nm: int | None = None) -> None:
        self.requested_grid_nm = _whole("grid_nm", grid_nm)
        self.grid_nm = max(self.requested_grid_nm, MICRON_NM)
        # Only the pitch that is actually coarse enough to be used is held to
        # whole microns: a clamped one is not the pitch anything is snapped to,
        # and refusing 500 nm for not being a whole micron would refuse it for
        # the wrong reason and with the wrong remedy.
        if self.grid_nm % MICRON_NM:
            raise ValueError(
                f"grid must be a whole number of microns, got {grid_nm} nm"
            )
        self.diagnostics = () if self.grid_nm == self.requested_grid_nm else (self._clamped(),)
        # Only an explicitly given threshold is checked: the default is derived
        # from a grid that has already been vetted.
        self.warn_over_nm = (
            self.grid_nm // 4 if warn_over_nm is None else _threshold(warn_over_nm)
        )

    def describe(self) -> StageRun:
        """Report the pitch the holes were really snapped to, and the threshold.

        Both are *effective* values. The grid is the clamped one, because the
        drawing's title block reads the pitch from here and a sheet stamping a
        pitch the holes were never snapped to is exactly the disagreement
        ``processing`` exists to prevent. ``warn_over_nm`` is reported resolved:
        ``SnapPositions(250_000)`` was constructed with ``None`` there but
        behaves as 62 500, and a record of ``None`` would tell a reader nothing
        about what happened to the data.

        The pitch is not only provenance: `ReviewGridTies` reads it back out of
        this record rather than being handed a second copy, so the two names
        come from `_GRID_PARAMETER` instead of being spelled twice.
        """
        return StageRun(
            self.name,
            ((_GRID_PARAMETER, self.grid_nm), ("warn_over_nm", self.warn_over_nm)),
        )

    def quantise(self, hole: RawHole) -> tuple[tuple[int, int], tuple[Diagnostic, ...]]:
        """The nearest grid point to one measured centre, and what it cost.

        The distance moved is compared **squared**, against the squared
        threshold, so the comparison never leaves the integers: ``math.hypot``
        would answer in floating point, and a float under an ``_nm`` key is the
        very thing ``_check_payload_lengths`` refuses. ``moved_nm`` is therefore
        reported as ``math.isqrt`` of that sum — the whole nanometres of the
        Euclidean distance, floored, which is five decimal places below anything
        an artifact prints.

        The residual is measured against ``nm_from_mm`` of the measurement and
        not against the float, so that it is the same subtraction
        ``Hole.residual_nm`` publishes and the two can never disagree by a
        rounding. Quantising the measurement is right here and wrong two lines
        up, and the inversion is the point: "which answer is nearest" must never
        see a rounded input, while "how far did this hole move" is a figure to
        print, in the unit everything else is printed in.
        """
        x_nm, y_nm = self._snap(hole.x), self._snap(hole.y)
        dx_nm, dy_nm = x_nm - nm_from_mm(hole.x), y_nm - nm_from_mm(hole.y)
        distance_sq = dx_nm * dx_nm + dy_nm * dy_nm

        # One tolerance idiom for the whole pipeline: a move of exactly
        # ``warn_over_nm`` is within it and stays quiet, slack included. Squares
        # are monotone in a non-negative distance, so sitting on the boundary
        # here is sitting on the same boundary the operator typed.
        if within(distance_sq, 0, self.warn_over_nm * self.warn_over_nm):
            return (x_nm, y_nm), ()
        return (x_nm, y_nm), (self._off_grid(hole, x_nm, y_nm, math.isqrt(distance_sq)),)

    def _clamped(self) -> Diagnostic:
        """Say which pitch was asked for and which one was used.

        Raised once, in the constructor, and kept on ``diagnostics`` rather than
        returned from `quantise`: this is a finding about the configuration, not
        about a hole, so returning it per hole would repeat it for every circle
        on the panel and lose it entirely on a panel with no circles at all —
        the run where the operator most needs to be told what their grid did.

        The requested pitch is printed to six decimals because three cannot tell
        the two apart, which is the whole argument for the floor: a pitch that
        renders identically to the one actually used would name nothing.
        """
        return Diagnostic.warning(
            "grid-too-fine",
            f"grid {format_nm(self.requested_grid_nm, 6)} mm is below the "
            f"{format_nm(self.grid_nm)} mm floor and was snapped to it: below a "
            f"micron the drill file and the drawing cannot print two grid points "
            f"apart",
            data=(
                ("requested_grid_nm", self.requested_grid_nm),
                ("grid_nm", self.grid_nm),
            ),
        )

    def _off_grid(self, hole: RawHole, x_nm: int, y_nm: int, moved_nm: int) -> Diagnostic:
        """Name the hole, both of its coordinates and the pitch that moved it.

        This was the one hole-level diagnostic with no ``data`` at all, and it
        is the worst place in the pipeline for that gap: this is the step that
        *moves* coordinates, so a consumer keying on position — the only thing
        the finding offered — is keying on the number this step has just
        changed. The drawing rings the holes named by ``hole_index`` and could
        therefore ring no off-grid hole at all, while the CLI report and the
        JSON both carried the finding.

        The message states both coordinates and says which is which, because one
        diagnostic here honestly spans two moments: the message opens where the
        hole was drawn, ``location_nm`` holds where it now is, and a reader given
        only one of them cannot tell which they have. ``moved_nm`` travels as
        well as being printed so that nobody has to recompute a distance from
        two rounded pairs.
        """
        return Diagnostic.warning(
            "off-grid",
            f"hole {hole.index} drawn at "
            f"({format_mm(hole.x, 4)}, {format_mm(hole.y, 4)}) moved "
            f"{format_nm(moved_nm, 4)} mm to "
            f"({format_nm(x_nm, 4)}, {format_nm(y_nm, 4)}) snapping to a "
            f"{format_nm(self.grid_nm)} mm grid",
            location_nm=(x_nm, y_nm),
            data=(
                ("hole_index", hole.index),
                ("moved_nm", moved_nm),
                ("grid_nm", self.grid_nm),
            ),
        )

    def _snap(self, mm: float) -> int:
        """The nearest grid point to one measured millimetre value.

        Ties go half-to-**even**, and this is deliberately not the unit
        boundary's away-from-zero rule. The question here is which grid point a
        hole should *move to*, and a consistent bias walks a whole panel one way
        where a parity rule does not. ``units``' docstring has the other half of
        the argument; do not unify the two.

        Only the quotient is rounded. The measurement reaches the division
        exactly, so the answer is the nearest multiple of the pitch to what the
        artwork said, and not to a copy of it that a rounding has already moved.
        """
        quotient = scaled_nm(mm) / self.grid_nm
        return int(quotient.to_integral_value(rounding=ROUND_HALF_EVEN)) * self.grid_nm


class ReviewGridTies:
    """Say so when a hole was placed by the tie-break rather than by the artwork.

    A hole exactly halfway between two grid points is snapped by ``round``'s
    parity rule, which is deterministic and carries no information about what
    the designer meant. **One is enough.** A single deliberate half-offset hole
    is the case an operator would most like named, and the whole panel tied is
    the mistake this exists for — artwork on 0.5 mm run at ``--grid 1.0``. There
    is no proportion in between to argue about, and therefore no denominator.

    **A ``Stage``, and it must run after ``Deduplicate``.** Tie status is read
    off ``Hole.raw``, while ``Deduplicate`` groups on the nominal ``(x_nm, y_nm,
    diameter_nm)`` — so two *different* measurements can snap onto one nominal
    hole, be duplicates of each other, and disagree about whether they tied. At
    a 250 000 nm pitch a hole measured at 0.000 and one measured at 0.125 both
    finish at 0, and ``Deduplicate`` keeps the first of them the source reached,
    so the verdict follows that survivor: drawn ``(tied, on-grid)`` the panel is
    reported ambiguous and drawn ``(on-grid, tied)`` it is quiet. **That
    dependence on order is deliberate and is the answer, not a residual to be
    engineered away.** The surviving hole is the one that will be drilled, and
    its measurement is the only provenance any artifact carries. Reviewed
    *before* dedupe the finding would be order-free and useless instead:
    ``tied_indices`` would name identities the emitters never receive, and a
    review of the artifacts that names a hole appearing in none of them is not a
    useful review of the artifacts. So the review is asked of the holes the
    emitters receive, which is what makes it a stage the caller can place rather
    than a second method on the quantiser.

    **The pitch is read back, never handed in.** ``SnapPositions`` already
    reports the effective grid, and a second copy given to this stage could be a
    pitch nothing was snapped to — the disagreement ``processing`` exists to
    prevent, and the one the drawing's title block was already caught making.

    That read is not a stage asserting what ran before it (LSP). ``last_run``
    answers ``None`` for "no such stage ran", its docstring requires a caller to
    render that rather than substitute a default, and the rendering here is the
    honest one: nothing snapped these holes, so no pitch defines a midpoint, so
    there is no tie to find and the data comes back untouched. The stage is
    correct in a pipeline with no ``snap`` in it, which is the whole of what LSP
    asks.
    """

    name: ClassVar[str] = "review-grid-ties"

    def describe(self) -> StageRun:
        """No parameters: everything this stage uses, it reads off the data.

        Recording the pitch here would be the obvious thing and the wrong one —
        ``snap`` already reports it, and one number in two records is two
        numbers the moment either moves. The record still earns its place, for
        ``Deduplicate``'s reason: it is how a consumer knows the review happened
        at all, which an empty diagnostics list cannot tell them apart from a
        panel that simply had no ties.
        """
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        grid_nm = self._pitch(data)
        if grid_nm is None:
            return data
        tied = tuple(hole.index for hole in data.holes if _is_tied(hole, grid_nm))
        return data.with_diagnostics(*((_ambiguous(tied, grid_nm),) if tied else ()))

    def _pitch(self, data: DrillData) -> int | None:
        """The pitch these holes were really snapped to, or ``None`` for none.

        A ``_nm`` key in a ``StageRun`` payload is already held to a whole
        ``int`` where it is constructed, so the only question left is whether a
        pitch is there to read: no ``snap`` in the pipeline, or a record that
        did not report one.
        """
        run = data.last_run(SnapPositions.name)
        pitch = None if run is None else run.get(_GRID_PARAMETER)
        return pitch if isinstance(pitch, int) else None


def _is_tied(hole: Hole, grid_nm: int) -> bool:
    """Did this hole land exactly between two grid points on either axis?

    **Per axis, and never the scalar distance.** ``moved_nm`` is the Euclidean
    distance the off-grid finding reports, and it equals half a pitch only when
    one axis moved half a pitch and the other did not move at all. A hole tied
    on *both* axes — the most obvious shape of "drawn on the wrong grid" — is
    1.41 half-pitches from where it was drawn, so a scalar rule scores it as
    ordinary and fails hardest on the case this finding exists for.

    **``or``, not ``and``.** A tie on either axis already proves the declared
    pitch is not the one the artwork was drawn on. ``and`` would require every
    tied hole to be offset diagonally, and would read a row of pots at constant
    Y — offset in X alone, the common case — as evidence that nothing is wrong.
    A hole on-grid in both axes is consistent with the declared grid *and* with
    the finer one it may have been drawn on, so it is **not** evidence either
    way and ``or`` correctly declines to count it: the predicate flags positive
    evidence and abstains on ambiguity.

    **The residual, not the measurement**, and that is what makes the exactness
    below true of artwork rather than only of a fixture. A circle drawn at a
    0.375 mm offset comes off the page as 0.3749999999999999, because the PDF
    operands, the CTM, the Bézier centroid and the frame subtraction are all
    binary float before anything decimal happens, so an exact test on the
    measurement would never fire and this would be dead code on every real
    panel. ``Hole.residual_nm`` is measured against ``nm_from_mm`` of that
    measurement, so the nanometre boundary supplies a ±0.5 nm window implicitly
    — inherited from a boundary the codebase already has rather than a constant
    anybody chose.
    """
    dx_nm, dy_nm, _ = hole.residual_nm
    return _axis_tied(dx_nm, grid_nm) or _axis_tied(dy_nm, grid_nm)


def _axis_tied(moved_nm: int, grid_nm: int) -> bool:
    """Half a pitch, in whole nanometres, whichever way the hole went.

    ``abs`` and not a signed comparison: on a centre-origin panel half the
    residuals are negative, and a spelling that only recognised the positive
    ones would drop half the evidence with nothing to show for it.

    **Exact equality, and no ``Decimal``.** A pitch that reaches here is a whole
    number of microns and therefore even, so half of it is a whole nanometre a
    residual can land on. That is guaranteed rather than lucky —
    ``SnapPositions`` refuses a 1 001 nm grid, so no such pitch is ever
    recorded — and it means there is no parity to handle and no band for anybody
    to choose. An odd pitch would have had a half-nanometre midpoint no residual
    could equal, and the finding would have been silent on every panel run at
    one.
    """
    return 2 * abs(moved_nm) == grid_nm


def _ambiguous(tied: tuple[int, ...], grid_nm: int) -> Diagnostic:
    """Name the holes a rule placed, and the pitch to reconsider.

    One finding about the panel, so there is no ``hole_index`` and no
    ``location_nm``. A singular index is the payload of a hole-level finding:
    the drawing rings whatever it names, so an arbitrary member of a tied set
    would be put where the cause belongs and the operator would go and inspect a
    hole no more at fault than the rest. ``tied_indices`` carries the whole set
    instead, for a consumer that wants per-hole behaviour. It does not end
    ``_nm`` and must not — it is a list of identities, not of lengths.

    **There is no denominator, deliberately.** Nothing here decides by
    proportion, so a hole count would be context rather than evidence, and a
    number in a finding that contradicts the artifact beside it is worse than no
    number at all.

    The sentence points at the declared grid, because that is the thing the
    operator can change. The positions are not wrong: each is a legitimate
    answer to a question with two equally good answers, so there is nothing to
    fix in the artwork and nothing to fix in the artifacts.
    """
    return Diagnostic.warning(
        "grid-ambiguous",
        f"{len(tied)} hole(s) sat exactly halfway between two "
        f"{format_nm(grid_nm)} mm grid points and were placed by the "
        f"tie-break rather than by the artwork: the declared grid is "
        f"probably not the one the panel was drawn on",
        data=(("tied_indices", tied),),
    )


def _whole(name: str, value: int) -> int:
    """A length that is a plain ``int`` of nanometres, and not a float wearing one.

    ``type(value) is int`` and not ``isinstance``: ``bool`` is a subclass of
    ``int``, and ``SnapPositions(True)`` is a one-nanometre grid rather than a
    mistake anything downstream could notice.
    """
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return value


def _threshold(value: int) -> int:
    """A warning distance: whole nanometres, and not one no hole can be inside of."""
    number = _whole("warn_over_nm", value)
    if number < 0:
        raise ValueError(f"warn_over_nm cannot be a negative distance, got {value!r}")
    return number
