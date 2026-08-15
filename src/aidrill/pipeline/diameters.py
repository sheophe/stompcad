"""Drill standards, and snapping every measured diameter onto one of them.

**Why this stage exists.** Measured diameters come back as 6.9998 and 7.0002 for
what the designer drew as one 7 mm hole. Without normalisation every downstream
consumer sees two sizes: the Excellon file loads the same bit twice, the hole
schedule shows two tools, and a part lookup misses. An earlier version of this
tool clustered diameters *inside the Excellon writer*, which meant the drawing
and the drill file could legitimately disagree about how many hole sizes
existed. Normalisation happens here, once, before any emitter sees the data.

**Why a table of real bits, and not clustering.** Clustering answers "which of
these measurements are the same hole?" — a question about the artwork. The
question that gets a panel drilled is "which bit do I put in the chuck?", and
its answer set is fixed by a bit series nobody here gets to invent. Clustering
5.02 and 5.04 into a nominal 5.03 produces a size that exists in no drawer on
earth, and it does so silently, in the number the machinist reads. Every nominal
diameter this stage produces comes from a declared table, or the hole is
refused.

**Why a registry of standards, and never one merged table.** Metric and
fractional bits are two different drawers, and overlaying them destroys the
matching semantics: 3.175 mm (1/8") and 3.2 mm are 0.025 mm apart, a tenth of
the matching tolerance, and 1/2" *is* 12.7 mm — the same physical bit, zero
millimetres apart, under two names. Merged, the choice between neighbours would
be decided by float ordering rather than by anything real, and the unique-label
invariant that keeps a hole schedule readable would be unsatisfiable by
construction. A panel is drilled with one set of bits; the operator declares
which set, and ``cli.py`` is where they say so.

**Why both series are generative rules rather than transcribed lists.** A rule
cannot carry a transcription typo, and it is auditable by reading five lines
instead of checking 247 values. It also puts the disagreement where it belongs:
sources genuinely differ about the metric breakpoints — ISO 235, BS 328 and
DIN 338 preferred sizes are not the same series — so the bands are *data*, and
adopting a different standard is editing a tuple rather than rewriting a stage.

**Why the widest practical union rather than a "common sizes" list.** We cannot
know another builder's needs: a talk-box pedal legitimately wants a 20 mm hole
for the mic tube. A table that is too narrow refuses real work, whereas one that
is too wide only ever offers a bit somebody has to buy. Narrowing is the
operator's job, through :meth:`DrillStandard.select`, and the narrowed set is
what ``describe`` publishes — so the drawing and the JSON state the sizes the
panel was actually quantised against, not the series they nominally came from.

Sources: the metric series follows the `BS 328 preferred sizes
<https://mechanical-engineering.com/drill-size-chart/>`_; the `fractional series
<https://workshopcalc.com/reference/drill-bit-sizes>`_ is sixty-fourths of an
inch.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType
from typing import ClassVar

from ..model import Diagnostic, DrillData, Hole, ParameterValue, StageRun
from ..tolerance import SLACK, within

__all__ = [
    "METRIC_BANDS",
    "FRACTIONAL_SIXTY_FOURTHS",
    "DrillStandard",
    "DRILL_STANDARDS",
    "DEFAULT_STANDARD",
    "SnapDiametersToDrillTable",
]

#: Metric: ``(start_mm, stop_mm, step_mm)`` bands, ``stop`` exclusive, so each
#: band runs up to — and not including — the first size of the next. Sources
#: disagree about where the pitch changes, which is exactly why this is data:
#: switching to another preferred series is editing this tuple.
METRIC_BANDS: tuple[tuple[float, float, float], ...] = (
    (0.5, 3.0, 0.05),
    (3.0, 14.0, 0.1),
    (14.0, 25.5, 0.5),
)

#: Fractional inch: 1/64" steps from 1/64" to a full inch.
FRACTIONAL_SIXTY_FOURTHS = range(1, 65)

#: Decimal places the metric bands are exact in. Every band step is a multiple
#: of 0.01, so rounding here removes binary-accumulation dust (0.8500000000000001)
#: without touching a single real size — and it is what lets the label be
#: *truthful* at 2 dp rather than merely unique.
_METRIC_DECIMALS = 2


def _metric_sizes(bands: Iterable[tuple[float, float, float]]) -> tuple[float, ...]:
    """Every size the bands describe, ascending.

    Counted with ``round`` rather than accumulated with ``while value < stop``:
    the accumulated version overshoots or stops a size early depending on which
    way the binary error of the step happens to fall, and it does so silently in
    the middle of a band.

    ``round`` and not ``int`` for the same reason one step further in. The
    quotient is a float, and it lands just below the true count as readily as on
    it — ``(2.9 - 0.2) / 0.1`` is ``26.999999999999996`` — so truncating drops
    the top size of the band and leaves a series that is still ascending, still
    gap-free, and one bit short.
    """
    sizes: list[float] = []
    for start, stop, step in bands:
        for index in range(round((stop - start) / step)):
            sizes.append(round(start + index * step, _METRIC_DECIMALS))
    return tuple(sizes)


def _fractional_sizes(sixty_fourths: Iterable[int]) -> tuple[float, ...]:
    """``n * 25.4 / 64``, which is exact: 1/8" is 3.175 and 1/2" is 12.7 with no
    rounding anywhere, because the division is by a power of two."""
    return tuple(n * 25.4 / 64 for n in sixty_fourths)


def _metric_label(size_mm: float) -> str:
    """``⌀3.20 mm``. Unique *and* truthful at 2 dp across all 183 sizes."""
    return f"⌀{size_mm:.2f} mm"


def _fractional_label(size_mm: float) -> str:
    """``⌀1/8"`` — the fraction, because no decimal millimetre is honest.

    1/64" is 0.396875 mm, which no finite decimal-millimetre label states
    exactly; measured at 2, 3 and 4 decimals the fractional series is unique at
    every precision and truthful at none. The fraction is exact, and it is also
    what is stamped on the bit the machinist picks up.
    """
    return f'⌀{Fraction(round(size_mm * 64 / 25.4), 64)}"'


@dataclass(frozen=True, slots=True)
class DrillStandard:
    """One drawer of bits: the sizes it holds and what each one is called.

    ``label`` is a function rather than a decimal precision, and that is a
    measured decision rather than a stylistic one — see :func:`_fractional_label`.
    A ``display_decimals: int`` serves metric perfectly and cannot serve
    fractional at any value.
    """

    name: str
    sizes_mm: tuple[float, ...]
    label: Callable[[float], str]

    def __post_init__(self) -> None:
        """A drawer with nothing in it drills nothing, so it is not a standard.

        Checked once, here, rather than at every use: without it the emptiness
        would first be noticed by the matching stage, as an ``unknown-diameter``
        error against every hole on the panel and nothing at all pointing at the
        cause.
        """
        if not self.sizes_mm:
            raise ValueError(f"the {self.name} drill standard has no sizes in it")

    def select(
        self,
        include: Sequence[float] | None = None,
        exclude: Sequence[float] | None = None,
    ) -> DrillStandard:
        """A narrowed copy holding only the bits actually in the drawer.

        Narrowing belongs here rather than in the standard because the standard
        is a physical constant and the drawer is not. A copy, never an edit: the
        registry is shared by every run in the process.

        A requested size the standard does not have raises, rather than being
        quietly dropped. ``--drill-sizes 3.33`` is a typo, and the silent
        reading of it — a drawer with one bit missing, or none at all — makes
        every hole on the panel an ``unknown-diameter`` error with nothing
        pointing at the cause. The same goes for asking a fractional standard
        for 3.2 mm: that is a real drill, but it is not one of *these*.
        """
        sizes = self.sizes_mm
        if include is not None:
            self._reject_unknown(include, "included")
            sizes = tuple(s for s in sizes if self._holds(include, s))
        if exclude is not None:
            self._reject_unknown(exclude, "excluded")
            sizes = tuple(s for s in sizes if not self._holds(exclude, s))
        # An empty result raises from ``__post_init__``, where the same rule is
        # enforced for a hand-built standard. One rule, one place.
        return replace(self, sizes_mm=sizes)

    def _reject_unknown(self, requested: Sequence[float], verb: str) -> None:
        missing = [r for r in requested if not any(self._same(s, r) for s in self.sizes_mm)]
        if missing:
            named = ", ".join(f"{m:g}" for m in missing)
            raise ValueError(
                f"{named} mm cannot be {verb}: no such size in the {self.name} drill "
                f"standard, which runs {self.sizes_mm[0]:g}–{self.sizes_mm[-1]:g} mm"
            )

    def _holds(self, requested: Sequence[float], size: float) -> bool:
        return any(self._same(size, r) for r in requested)

    @staticmethod
    def _same(size: float, requested: float) -> bool:
        """Two spellings of one size. Not a matching tolerance — that is the
        stage's job, and a lenient ``select`` would silently hand back a bit the
        operator did not ask for. This absorbs binary representation only."""
        return within(size, requested, SLACK)


#: Every standard the operator may declare. A mapping proxy, because a registry
#: one run can rewrite is a registry the next run cannot trust.
DRILL_STANDARDS: Mapping[str, DrillStandard] = MappingProxyType(
    {
        "metric": DrillStandard(
            name="metric",
            sizes_mm=_metric_sizes(METRIC_BANDS),
            label=_metric_label,
        ),
        "fractional": DrillStandard(
            name="fractional",
            sizes_mm=_fractional_sizes(FRACTIONAL_SIXTY_FOURTHS),
            label=_fractional_label,
        ),
    }
)

#: What a panel is drilled with unless the operator says otherwise.
DEFAULT_STANDARD = "metric"


class SnapDiametersToDrillTable:
    """Give every hole the nominal diameter of a bit that actually exists.

    ``tolerance_mm`` is how far a measurement may sit from a table size and
    still be that size. Be clear about what it does and does not catch, because
    the honest answer is narrower than it looks: **within the series' range it
    never fires at all.** The widest gap anywhere in the metric series is the
    0.5 mm step between 14.0 and 14.5, so the furthest any measurement in
    0.5–25.0 mm can sit from a size is exactly 0.25 — the default tolerance,
    which ``within`` treats as inclusive. What actually protects a panel in that
    range is the *density of the table*, not this number: the nearest bit is
    always within half a step, and half a step is small.

    What the bound really catches is a measurement **outside** the series — a
    30 mm cut-out that wants a step drill or a punch, a 0.2 mm speck, a rounded
    rectangle the circle fitter mistook for a circle. Those are the cases where
    unbounded nearest-neighbour matching would turn a malformed shape into a
    plausible *wrong* drill that nothing downstream could tell from a real one.

    A second, tighter threshold — "this snapped further than a real drawing
    ought to" as a WARNING — is a genuinely different idea and is deliberately
    not this number. Tightening *this* one to catch it would make a legitimate
    14.3 mm panel an ERROR and, by the rule below, cost it the hole.

    **An unmatched measurement is not kept.** Retaining it and warning cannot
    survive the invariant this stage carries: if every nominal comes from the
    table, a retained 30.0 is a nominal that came from nowhere, and the drill
    file would define a tool for a bit that does not exist. So the finding is an
    ERROR — the run is not fit to drill — and the hole appears in no artifact.
    Everything needed to find it is in the diagnostic: the hole's index, what it
    measured, and the nearest bit there is.
    """

    name: ClassVar[str] = "snap-diameters"

    def __init__(
        self,
        standard: DrillStandard = DRILL_STANDARDS[DEFAULT_STANDARD],
        tolerance_mm: float = 0.25,
    ) -> None:
        self.standard = standard
        self.tolerance_mm = float(tolerance_mm)

    def describe(self) -> StageRun:
        """Always the name and the count; the sizes only when they are news.

        A standard is a physical constant addressable by name, and a consumer
        that cannot expand ``"metric"`` into 183 sizes cannot interpret them
        either — so writing all 183 into every record buys nothing and costs
        90 % of the machine-readable document. ``size_count`` goes with the name
        as a cheap integrity check: it catches the one thing the name alone
        cannot say, which is that this run's idea of "metric" and the reader's
        are different versions of the same word.

        The narrowed drawer is the opposite case. It is run-specific, a consumer
        computing "the nearest available size" gets it wrong without the actual
        set, and it is *small* — so the case where the record genuinely must
        stand alone is exactly the case where writing it is cheap.

        The test is equality against the registry rather than a flag set by
        ``select``, because the question is not "was this narrowed?" but "can a
        reader rebuild this table from the name?". A hand-built standard under a
        name the registry does not hold answers no, and gets its sizes written
        out too.
        """
        parameters: list[tuple[str, ParameterValue]] = [
            ("standard", self.standard.name),
            ("tolerance_mm", self.tolerance_mm),
            ("size_count", len(self.standard.sizes_mm)),
        ]
        if self._narrowed():
            parameters.append(("sizes_mm", self.standard.sizes_mm))
        return StageRun(self.name, tuple(parameters))

    def _narrowed(self) -> bool:
        """Is this drawer something other than the registry's table of that name?

        One predicate asked in two places, because two spellings of it would
        eventually answer differently: ``describe`` decides by it whether the
        sizes have to be written out, and ``_unknown`` decides by it whom a
        refusal names. Both are asking "can a reader rebuild this table from the
        name?", never "was ``select`` called?" — which is why a hand-built
        standard under a name the registry does not hold answers yes.
        """
        return self.standard != DRILL_STANDARDS.get(self.standard.name)

    def apply(self, data: DrillData) -> DrillData:
        kept: list[Hole] = []
        diagnostics: list[Diagnostic] = []

        for hole in data.holes:
            nearest = self._nearest(hole.diameter)
            if not within(nearest, hole.diameter, self.tolerance_mm):
                diagnostics.append(self._unknown(hole, nearest))
                continue
            kept.append(hole.with_diameter(nearest))

        return data.with_holes(kept).with_diagnostics(*diagnostics)

    def _nearest(self, measured: float) -> float:
        """The closest size in the table, ties going to the smaller bit.

        The tie-break is what stops the answer depending on the order the table
        happens to be in: 6.35 sits exactly between the 6.3 and 6.4 metric
        sizes, and ``min`` would otherwise return whichever came first.
        """
        return min(self.standard.sizes_mm, key=lambda size: (abs(size - measured), size))

    def _unknown(self, hole: Hole, nearest: float) -> Diagnostic:
        """Name the hole, the measurement, the closest bit — and what refused it.

        ``hole_index`` is the foreign key — the stable identity that survives a
        later stage moving the hole — and ``nearest_mm`` is there so a consumer
        can say "you drew 30.0, the biggest bit is 25.0" without re-deriving the
        search this stage has already done.

        Which table refused the hole is the difference between a finding an
        operator can act on and one that misdirects them. 5.0 mm *is* a metric
        size; on a run narrowed to a 7 mm bit, blaming "no metric drill size"
        sends them to check the series — the one thing that is right — and says
        nothing about the flag they typed. So the narrowed case names the drawer
        and how few sizes are in it, and the untouched case keeps naming the
        standard, because inventing a drawer nobody declared misdirects just as
        badly in the other direction.

        ``stocked_size_count`` goes out either way, and is a count rather than a
        flag: it is the quantity the message states, so the console line, the
        NOTES block and the JSON stay three renderings of one finding instead of
        three computations. Present on both branches, so nothing has to branch
        on a key's absence to render it.
        """
        stocked = len(self.standard.sizes_mm)
        if self._narrowed():
            refused = (
                f"no size in the drawer — the {self.standard.name} standard narrowed "
                f"to {stocked} size{'' if stocked == 1 else 's'}; the nearest stocked "
                f"bit is {self.standard.label(nearest)}"
            )
        else:
            refused = (
                f"no {self.standard.name} drill size — the nearest is "
                f"{self.standard.label(nearest)}"
            )
        return Diagnostic.error(
            "unknown-diameter",
            f"⌀{hole.diameter:.4f} mm at ({hole.x:.3f}, {hole.y:.3f}) is within "
            f"{self.tolerance_mm:g} mm of {refused}; the hole has been dropped "
            f"and appears in no artifact",
            location=(hole.x, hole.y),
            data=(
                ("hole_index", hole.index),
                ("diameter_mm", hole.diameter),
                ("nearest_mm", nearest),
                ("standard", self.standard.name),
                ("stocked_size_count", stocked),
                ("tolerance_mm", self.tolerance_mm),
            ),
        )
