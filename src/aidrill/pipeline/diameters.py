"""Drill standards, and quantising every measured diameter onto one of them.

**Why this quantiser exists.** Measured diameters come back as 6.9998 and 7.0002
for what the designer drew as one 7 mm hole. Without normalisation every
downstream consumer sees two sizes: the Excellon file loads the same bit twice,
the hole schedule shows two tools, and a part lookup misses. An earlier version
of this tool clustered diameters *inside the Excellon writer*, which meant the
drawing and the drill file could legitimately disagree about how many hole sizes
existed. Normalisation happens here, once, before any emitter sees the data.

**Why a table of real bits, and not clustering.** Clustering answers "which of
these measurements are the same hole?" — a question about the artwork. The
question that gets a panel drilled is "which bit do I put in the chuck?", and
its answer set is fixed by a bit series nobody here gets to invent. Clustering
5.02 and 5.04 into a nominal 5.03 produces a size that exists in no drawer on
earth, and it does so silently, in the number the machinist reads. Every nominal
diameter this quantiser produces comes from a declared table, or the hole is
refused.

**Why the table is whole nanometres.** The answer set is then exact *by
construction* rather than by tolerance: a size is an integer, "is this one of
mine?" is equality, and the diameter a hole leaves here with is provably a row
of the declared table rather than a rounded measurement that resembles one. The
fractional series is what settles the unit — 1/64" is 396 875 nm exactly and
396.875 microns, which is not a whole one, so a micron model would round the
answer set itself.

**Why a registry of standards, and never one merged table.** Metric and
fractional bits are two different drawers, and overlaying them destroys the
matching semantics: 3.175 mm (1/8") and 3.2 mm are 0.025 mm apart, a tenth of
the matching tolerance, and 1/2" *is* 12.7 mm — the same physical bit, the same
integer, under two names. Merged, the choice between neighbours would be decided
by table ordering rather than by anything real, and the unique-label invariant
that keeps a hole schedule readable would be unsatisfiable by construction. A
panel is drilled with one set of bits; the operator declares which set, and
``cli.py`` is where they say so.

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
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import ClassVar

from ..formatting import format_mm
from ..model import Diagnostic, ParameterValue, RawHole, StageRun
from ..units import format_nm, nm_from_mm, scaled_nm

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
#: switching to another preferred series is editing this tuple. Millimetres,
#: because that is how a drill series is published and how the operator adopting
#: another one would write it down; they cross the unit boundary once, in
#: :func:`_metric_sizes`.
METRIC_BANDS: tuple[tuple[float, float, float], ...] = (
    (0.5, 3.0, 0.05),
    (3.0, 14.0, 0.1),
    (14.0, 25.5, 0.5),
)

#: Fractional inch: 1/64" steps from 1/64" to a full inch.
FRACTIONAL_SIXTY_FOURTHS = range(1, 65)

#: 1/64" in nanometres, and the pitch of the whole fractional series. Exact: an
#: inch is 25.4 mm by definition, so 25 400 000 nm, and 64 divides it.
_SIXTY_FOURTH_NM: int = 396_875


def _metric_sizes(bands: Iterable[tuple[float, float, float]]) -> tuple[int, ...]:
    """Every size the bands describe, ascending, in whole nanometres.

    Each band crosses the unit boundary once and is then counted in integers.
    That is what makes the count exact: ``(stop - start) // step`` on whole
    nanometres is the number of sizes the band holds, where a float quotient
    lands just below the true count as readily as on it — ``(2.9 - 0.2) / 0.1``
    is ``26.999999999999996`` — and drops the top size of a band silently, in
    the middle of a series that is still ascending and still gap-free.
    """
    sizes: list[int] = []
    for start, stop, step in bands:
        start_nm, stop_nm, step_nm = nm_from_mm(start), nm_from_mm(stop), nm_from_mm(step)
        for index in range((stop_nm - start_nm) // step_nm):
            sizes.append(start_nm + index * step_nm)
    return tuple(sizes)


def _fractional_sizes(sixty_fourths: Iterable[int]) -> tuple[int, ...]:
    """``n * 396 875`` nanometres, which is exact and divides nothing.

    1/8" is 3 175 000 and 1/2" is 12 700 000 with no rounding anywhere. In
    microns it would not be: 1/64" is 396.875 of them, and 56 of these 64 sizes
    would come out as an answer set that had itself been rounded.
    """
    return tuple(n * _SIXTY_FOURTH_NM for n in sixty_fourths)


def _whole_nanometres(name: str, value: object) -> int:
    """A length that is a plain ``int`` of nanometres, and not a float wearing one.

    ``type(value) is int`` and not ``isinstance``, because ``bool`` is a
    subclass of ``int`` in Python: ``True`` passes an ``isinstance`` guard and
    goes on to be a one-nanometre matching bound, or a one-nanometre bit, and
    neither is a number any report would make look wrong.

    Asked at the constructor, on the precedent ``model._check_nanometres`` sets
    and for its reason: the offending value still has a call site attached to it
    here. Everywhere else it is a length that never crossed ``units``, and the
    place it finally surfaces is nowhere near the place it came from.
    """
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return value


def _metric_label(size_nm: int) -> str:
    """``⌀3.20 mm``. Unique *and* truthful at 2 dp across all 183 sizes."""
    return f"⌀{format_nm(size_nm, 2)} mm"


def _fractional_label(size_nm: int) -> str:
    """``⌀1/8"`` — the fraction, because no decimal millimetre is honest.

    1/64" is 0.396875 mm, which no finite decimal-millimetre label states
    exactly; measured at 2, 3 and 4 decimals the fractional series is unique at
    every precision and truthful at none. The fraction is exact and needs no
    arithmetic of ours — the size is a whole number of nanometres and so is an
    inch, so ``Fraction`` reduces the two — and it is also what is stamped on
    the bit the machinist picks up.
    """
    return f'⌀{Fraction(size_nm, _SIXTY_FOURTH_NM * 64)}"'


@dataclass(frozen=True, slots=True)
class DrillStandard:
    """One drawer of bits: the sizes it holds and what each one is called.

    ``label`` is a function rather than a decimal precision, and that is a
    measured decision rather than a stylistic one — see :func:`_fractional_label`.
    A ``display_decimals: int`` serves metric perfectly and cannot serve
    fractional at any value.
    """

    name: str
    sizes_nm: tuple[int, ...]
    label: Callable[[int], str]

    def __post_init__(self) -> None:
        """The drawer is checked once, here, rather than at every use.

        A drawer with nothing in it drills nothing, so it is not a standard.
        Without this the emptiness would first be noticed by the matching stage,
        as an ``unknown-diameter`` error against every hole on the panel and
        nothing at all pointing at the cause.

        A size that is not a plain positive ``int`` of nanometres is not a bit,
        and it fails just as far from where it was written: ``7_000_000.0``
        constructs happily and then raises out of ``Decimal - float`` on the
        first hole quantised against it, while ``True`` gets as far as being
        offered to an operator as the nearest available size. The check is
        elementwise because a table is only as exact as its worst row — the
        invariant this standard carries is that *every* nominal it hands out is
        one of these integers.
        """
        if not self.sizes_nm:
            raise ValueError(f"the {self.name} drill standard has no sizes in it")
        for position, size in enumerate(self.sizes_nm):
            _whole_nanometres(f"the {self.name} drill standard's size[{position}]", size)
            if size <= 0:
                raise ValueError(
                    f"the {self.name} drill standard holds {size} nm at position "
                    f"{position}, and no bit is nothing across"
                )

    def select(
        self,
        include: Sequence[int] | None = None,
        exclude: Sequence[int] | None = None,
    ) -> DrillStandard:
        """A narrowed copy holding only the bits actually in the drawer.

        Narrowing belongs here rather than in the standard because the standard
        is a physical constant and the drawer is not. A copy, never an edit: the
        registry is shared by every run in the process.

        Membership is equality, with no slack anywhere in it. Both sides are
        whole nanometres that came through the same unit boundary, so "is this
        one of mine?" has an exact answer, and a lenient one would hand back a
        bit the operator did not ask for under the name of one they did. The
        matching tolerance is a different question, asked of a measurement, and
        it is :class:`SnapDiametersToDrillTable`'s.

        A requested size the standard does not have raises, rather than being
        quietly dropped. ``--drill-sizes 3.33`` is a typo, and the silent
        reading of it — a drawer with one bit missing, or none at all — makes
        every hole on the panel an ``unknown-diameter`` error with nothing
        pointing at the cause. The same goes for asking a fractional standard
        for 3.2 mm: that is a real drill, but it is not one of *these*.
        """
        sizes = self.sizes_nm
        if include is not None:
            self._reject_unknown(include, "included")
            wanted = set(include)
            sizes = tuple(s for s in sizes if s in wanted)
        if exclude is not None:
            self._reject_unknown(exclude, "excluded")
            unwanted = set(exclude)
            sizes = tuple(s for s in sizes if s not in unwanted)
        # An empty result raises from ``__post_init__``, where the same rule is
        # enforced for a hand-built standard. One rule, one place.
        return replace(self, sizes_nm=sizes)

    def _reject_unknown(self, requested: Sequence[int], verb: str) -> None:
        held = set(self.sizes_nm)
        missing = [r for r in requested if r not in held]
        if missing:
            named = ", ".join(format_nm(m) for m in missing)
            raise ValueError(
                f"{named} mm cannot be {verb}: no such size in the {self.name} drill "
                f"standard, which runs {format_nm(self.sizes_nm[0])}–"
                f"{format_nm(self.sizes_nm[-1])} mm"
            )


#: Every standard the operator may declare. A mapping proxy, because a registry
#: one run can rewrite is a registry the next run cannot trust.
DRILL_STANDARDS: Mapping[str, DrillStandard] = MappingProxyType(
    {
        "metric": DrillStandard(
            name="metric",
            sizes_nm=_metric_sizes(METRIC_BANDS),
            label=_metric_label,
        ),
        "fractional": DrillStandard(
            name="fractional",
            sizes_nm=_fractional_sizes(FRACTIONAL_SIXTY_FOURTHS),
            label=_fractional_label,
        ),
    }
)

#: What a panel is drilled with unless the operator says otherwise.
DEFAULT_STANDARD = "metric"


class SnapDiametersToDrillTable:
    """Give every hole the nominal diameter of a bit that actually exists.

    ``tolerance_nm`` is how far a measurement may sit from a table size and
    still be that size. Be clear about what it does and does not catch, because
    the honest answer is narrower than it looks: **within the series' range it
    never fires at all.** The widest gap anywhere in the metric series is the
    0.5 mm step between 14.0 and 14.5, so the furthest any measurement in
    0.5–25.0 mm can sit from a size is exactly 250 000 nm — the default
    tolerance, and the bound is inclusive. What actually protects a panel in
    that range is the *density of the table*, not this number: the nearest bit
    is always within half a step, and half a step is small.

    What the bound really catches is a measurement **outside** the series — a
    30 mm cut-out that wants a step drill or a punch, a 0.2 mm speck, a rounded
    rectangle the circle fitter mistook for a circle. Those are the cases where
    unbounded nearest-neighbour matching would turn a malformed shape into a
    plausible *wrong* drill that nothing downstream could tell from a real one.

    A second, tighter threshold — "this snapped further than a real drawing
    ought to" as a WARNING — is a genuinely different idea and is deliberately
    not this number. Tightening *this* one to catch it would make a legitimate
    14.3 mm panel an ERROR and, by the rule below, cost it the hole.

    The bound reaches ``describe`` and the diagnostic payload unchanged, under a
    key that promises whole nanometres. It is therefore neither coerced nor
    defaulted on the way in: rounding it here would truncate a real number, and
    accepting a millimetre float would launder it into a field a consumer reads
    as nanometres — which is exactly what the model's payload guard refuses. It
    is refused *here* rather than there because the payload guard fires from
    ``describe``, which the phase reaches only after quantising every hole on
    the panel: a ``TypeError`` out of the provenance record, with the argument
    that caused it three paths behind and all the work already done.

    **An unmatched measurement is not kept.** Retaining it and warning cannot
    survive the invariant this quantiser carries: if every nominal comes from
    the table, a retained 30 000 000 is a nominal that came from nowhere, and
    the drill file would define a tool for a bit that does not exist. So the
    finding is an ERROR — the run is not fit to drill — and the hole appears in
    no artifact. Everything needed to find it is in the diagnostic: the hole's
    index, what it measured, and the nearest bit there is.
    """

    name: ClassVar[str] = "snap-diameters"

    def __init__(
        self,
        standard: DrillStandard = DRILL_STANDARDS[DEFAULT_STANDARD],
        tolerance_nm: int = 250_000,
    ) -> None:
        self.standard = standard
        self.tolerance_nm = _whole_nanometres("tolerance_nm", tolerance_nm)
        # Negative is refused rather than clamped, and it is the failure that
        # says nothing at all: a bound no measurement can be inside of makes
        # every hole on the panel an ``unknown-diameter`` ERROR, so the report
        # names forty findings and none of them names the number that caused
        # them. Zero is a real bound — "this measurement is exactly a size in
        # the table" — and is left alone.
        if self.tolerance_nm < 0:
            raise ValueError(
                f"tolerance_nm cannot be a negative distance, got {tolerance_nm!r}"
            )

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
            ("tolerance_nm", self.tolerance_nm),
            ("size_count", len(self.standard.sizes_nm)),
        ]
        if self._narrowed():
            parameters.append(("sizes_nm", self.standard.sizes_nm))
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

    def quantise(self, hole: RawHole) -> tuple[int | None, tuple[Diagnostic, ...]]:
        """The table size this measurement is, or ``None`` to drop the hole.

        The measurement is scaled and never quantised. ``units.scaled_nm`` keeps
        it exact, so that "which size is nearest?" is asked of the number the
        artwork actually gave; rounding it to whole nanometres first does not
        merely lose a fraction of one, it **manufactures a tie the measurement
        did not have**. 5.0250004 mm is 5 025 000.4 nm and is nearer the
        5 050 000 entry by six tenths of a nanometre, but the rounded copy sits
        dead centre on 5 025 000 and the tie-break below — which exists to
        resolve genuine ambiguity — then resolves a fabricated one, moving the
        hole a whole drill size to 5 000 000.

        The comparison is exact on both sides, so it does not go through
        ``tolerance.within``, which is typed for two whole-nanometre lengths.
        The boundary it decides is the same one and inclusive for the same
        reason: a bound the operator typed is a number they meant.
        """
        measurement_nm = scaled_nm(hole.diameter)
        nearest_nm = self._nearest(measurement_nm)
        if abs(measurement_nm - nearest_nm) > self.tolerance_nm:
            return None, (self._unknown(hole, nearest_nm),)
        return nearest_nm, ()

    def _nearest(self, measurement_nm: Decimal) -> int:
        """The closest size in the table, ties going to the smaller bit.

        The tie-break is what stops the answer depending on the order the table
        happens to be in: 14 250 000 sits exactly between the 14.0 and 14.5 mm
        sizes, and ``min`` would otherwise return whichever came first.
        """
        return min(self.standard.sizes_nm, key=lambda size: (abs(measurement_nm - size), size))

    def _unknown(self, hole: RawHole, nearest_nm: int) -> Diagnostic:
        """Name the hole, the measurement, the closest bit — and what refused it.

        ``hole_index`` is the foreign key — the stable identity that survives a
        later stage moving the hole — and ``nearest_nm`` is there so a consumer
        can say "you drew 30.0, the biggest bit is 25.0" without re-deriving the
        search this quantiser has already done.

        The measurement and the position are quantised here and nowhere else in
        this module: a payload key ending ``_nm`` promises whole nanometres, and
        this is a figure to be printed rather than one to be compared. The
        position is the measured one — no hole has been moved, and a finding
        needs a coordinate the operator can find on the artwork.

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
        stocked = len(self.standard.sizes_nm)
        if self._narrowed():
            refused = (
                f"no size in the drawer — the {self.standard.name} standard narrowed "
                f"to {stocked} size{'' if stocked == 1 else 's'}; the nearest stocked "
                f"bit is {self.standard.label(nearest_nm)}"
            )
        else:
            refused = (
                f"no {self.standard.name} drill size — the nearest is "
                f"{self.standard.label(nearest_nm)}"
            )
        return Diagnostic.error(
            "unknown-diameter",
            f"⌀{format_mm(hole.diameter, 4)} mm at ({format_mm(hole.x)}, "
            f"{format_mm(hole.y)}) is within {format_nm(self.tolerance_nm)} mm of "
            f"{refused}; the hole has been dropped and appears in no artifact",
            location_nm=(nm_from_mm(hole.x), nm_from_mm(hole.y)),
            data=(
                ("hole_index", hole.index),
                ("diameter_nm", nm_from_mm(hole.diameter)),
                ("nearest_nm", nearest_nm),
                ("standard", self.standard.name),
                ("stocked_size_count", stocked),
                ("tolerance_nm", self.tolerance_nm),
            ),
        )
