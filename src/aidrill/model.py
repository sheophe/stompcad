"""Canonical data model for aidrill.

Everything here is an immutable value object. Transforms return new instances;
nothing is mutated in place. This is what lets the pipeline be a plain left fold
and lets stages be tested in isolation.

Canonical frame, used by every stage and by every emitter's *input*:

    whole nanometres, Y up, origin at the centre of the reference outline.

There are two kinds of length here and the suffix is what tells them apart.

A **nominal** length — where a hole will actually be drilled, what a tool table
lists, what an artifact prints — is an ``int`` and carries an ``_nm`` suffix, so
a unit mistake is visible at the call site rather than three stages downstream.
It is never a float: a float is a quantity two artifacts can round differently,
and two artifacts describing the same panel and disagreeing is the expensive
failure here.

A **measurement** — what the artwork said, on ``RawHole`` and ``RawOutline`` —
is a ``float`` millimetre and carries no suffix, because quantisation has not
happened to it yet and naming it in nanometres would be the very lie
``_check_payload_lengths`` exists to catch one level down. A measurement is
consumed by exactly one thing: the quantisation phase, which turns it into the
nominal values above. Everything after that reads it only to print it.

The two guards therefore run in opposite directions, and both are at
construction: ``_check_nanometres`` refuses anything but a plain ``int``,
``_check_millimetres`` anything but a finite ``float``.

Emitters that need a different frame or different units convert on output, via
``DrillData.with_origin`` and ``units.mm_from_nm``. No stage ever sees inches.

``Diagnostic.data`` and ``StageRun.parameters`` are the one open corner of all
this: a stage records what it has to record, under keys nothing here knows in
advance. So in a payload the ``_nm`` suffix carries the whole contract, and it
is enforced at construction — a key ending ``_nm`` holds whole nanometres, in a
tuple as well as on its own, while every other key is free to hold the float
that a ratio or an angle genuinely is.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import total_ordering

from .units import mm_from_nm, nm_from_mm

__all__ = [
    "Severity",
    "Origin",
    "Units",
    "RawHole",
    "Hole",
    "RawOutline",
    "ReferenceOutline",
    "EnclosureMatch",
    "Diagnostic",
    "SourceInfo",
    "ParameterValue",
    "StageRun",
    "RawDrillData",
    "DrillData",
]


#: What a stage may record about itself in a ``StageRun``. One member wider than
#: ``Diagnostic.data``: a diameter table is a list of numbers, and flattening it
#: into a string would make the drawing parse its own provenance back out again.
#:
#: ``float`` stays in the union for the values that genuinely are one — a ratio,
#: an angle, a fraction — and *not* for lengths. A length is named with an
#: ``_nm`` suffix and ``_check_payload_lengths`` holds it to that at
#: construction, so the type here stays as wide as the ``Stage`` protocol needs
#: while the one class of value two artifacts could round differently does not.
ParameterValue = float | int | str | bool | tuple[float, ...]


@total_ordering
class Severity(Enum):
    """How much a diagnostic should worry the operator.

    Ordered, because ``worst_severity`` is a ``max`` over the findings and the
    CLI reads its exit code off that. ``__lt__`` on its own was enough for
    ``max`` and left the rest of the protocol broken: ``severity >=
    Severity.WARNING`` — the obvious way to ask "is this worth stopping for?" —
    raised ``TypeError``, and comparing against anything that is not a severity
    raised ``ValueError`` out of ``index``, which reports a lookup miss as
    though the comparison had been attempted. Hence ``total_ordering`` for the
    other three operators and ``NotImplemented`` for the mixed pair, which is
    what lets Python raise the ``TypeError`` an unorderable comparison earns.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        order = (Severity.INFO, Severity.WARNING, Severity.ERROR)
        return order.index(self) < order.index(other)


class Origin(Enum):
    """Where (0, 0) sits for an emitted artifact.

    CENTRE is the canonical internal frame. LOWER_LEFT is what most drilling
    equipment expects, because it keeps every coordinate positive.
    """

    CENTRE = "centre"
    LOWER_LEFT = "lower-left"


class Units(Enum):
    MILLIMETRES = "metric"
    INCHES = "inch"

    @property
    def per_mm(self) -> float:
        """Multiplier to convert a millimetre value into these units."""
        return 1.0 if self is Units.MILLIMETRES else 1.0 / 25.4


def _check_nanometres(owner: str, **lengths: object) -> None:
    """Refuse anything but a plain ``int`` for a length.

    Checked once, at construction, rather than at every use — the precedent
    ``DrillStandard.__post_init__`` sets, and for the same reason: a float that
    slipped in is only ever noticed at the far end, as a drill file reading
    ``X6.999999999`` with nothing left to say where the value came from. Here
    the offending value still has a call site attached to it.

    ``type(value) is int`` and not ``isinstance``, because ``bool`` is a
    subclass of ``int`` in Python: a ``True`` that reached a coordinate passes
    an ``isinstance`` guard and goes on to be drilled one nanometre from the
    origin, a position no report would make look wrong.

    Refused rather than rounded, and this is the point of the module boundary: a
    caller holding a float holds a length that never crossed ``units``, and
    rounding it here would put the conversion in two places — which is how two
    artifacts come to disagree about one hole.
    """
    for name, value in lengths.items():
        if type(value) is not int:
            raise TypeError(
                f"{owner}.{name} must be a whole number of nanometres, not {value!r}"
            )


def _check_millimetres(owner: str, **lengths: object) -> None:
    """Refuse anything but a finite ``float`` for a measurement.

    Not symmetry for its own sake. ``raw`` is *printed*: the JSON emitter
    serialises it and the drawing quotes what the artwork measured, so a value
    that reaches a millimetre field without ever crossing ``units`` is not
    merely mistyped — it is a number a machinist reads. 40 mm arriving as the
    40 000 000 nanometres it also is puts a 40 000 000.000 mm residual on the
    sheet, with nothing in the figure to look wrong.

    ``type(value) is float`` and not ``isinstance``, for the mirror image of the
    reason ``_check_nanometres`` writes ``type(value) is int``: a plain ``int``
    is a perfectly good ``float`` argument everywhere else in Python, which is
    exactly what makes it invisible here, and ``bool`` is an ``int`` besides.
    An ``int`` in a millimetre field is a length that never crossed a unit
    boundary, and refusing it is the whole point.

    ``math.isfinite``, because a NaN is a ``float`` and would satisfy a type
    check alone. It then propagates in silence: every comparison against it is
    ``False``, so a NaN measurement is neither inside a tolerance nor outside
    one, and the stage that would have reported it simply does not.
    """
    for name, value in lengths.items():
        if type(value) is not float or not math.isfinite(value):
            raise TypeError(
                f"{owner}.{name} must be a finite number of millimetres, not {value!r}"
            )


def _check_payload_lengths(owner: str, items: Iterable[tuple[str, object]]) -> None:
    """Hold a generic key/value payload to the ``_nm`` suffix in its keys.

    ``Diagnostic.data`` and ``StageRun.parameters`` are open on purpose — a
    stage records what it has to record, and neither this module nor the
    ``Stage`` protocol can know in advance what that is. That openness is
    precisely why the key has to be held to its word: it is the only thing
    telling a consumer what the number means, and a millimetre float under
    ``moved_nm`` prints as a plausible number in the CLI report, the drawing's
    NOTES block and the JSON alike, all three quoting each other.

    The distance ``SnapPositions`` reports is the case this exists for. It comes
    out of ``math.hypot`` as a float, and dropping that into ``moved_nm``
    without quantising it is a mistake no artifact would show.

    Everything not named as a length is left alone, because a ratio or an angle
    is a genuine float and refusing it would push a stage into spelling a real
    number as a string. Tuples are checked elementwise: the one tuple-valued
    parameter in the pipeline is a table of diameters, and a scalar-only check
    would leave every size in it the only unexamined length in the model.
    """
    for key, value in items:
        if not key.endswith("_nm"):
            continue
        if isinstance(value, tuple):
            for position, element in enumerate(value):
                _check_nanometres(owner, **{f"{key}[{position}]": element})
        else:
            _check_nanometres(owner, **{key: value})


@dataclass(frozen=True, slots=True)
class RawHole:
    """One circle as the artwork measured it, in millimetres, before quantising.

    Kept for provenance so a drawing can show "0.000 (raw -39.991)" and so a
    residual can always be recomputed rather than remembered.

    ``index`` is the source's traversal-order identity, and it lives here rather
    than only on ``Hole`` because identity belongs with the measurement: the
    measurement is the one thing about a hole that never moves, so a diagnostic
    holding a raw circle can still say which hole it is about.
    """

    x: float
    y: float
    diameter: float
    index: int

    def __post_init__(self) -> None:
        _check_millimetres("RawHole", x=self.x, y=self.y, diameter=self.diameter)


@dataclass(frozen=True, slots=True)
class Hole:
    """One drilled hole in the canonical frame.

    ``index`` is the hole's stable identity. It is required — a shared default
    would put every hole back under one ambiguous name, which is the whole thing
    this field exists to remove.
    """

    x_nm: int
    y_nm: int
    diameter_nm: int
    raw: RawHole
    index: int

    def __post_init__(self) -> None:
        _check_nanometres(
            "Hole", x_nm=self.x_nm, y_nm=self.y_nm, diameter_nm=self.diameter_nm
        )

    @classmethod
    def from_measurement(cls, x_nm: int, y_nm: int, diameter_nm: int, index: int) -> Hole:
        """Build a hole whose nominal values are still its measured values.

        ``index`` is the hole's stable identity, assigned once by the source in
        traversal order and preserved by every transform. It exists because a
        diagnostic needs a referent that survives later stages: keying on
        position went stale the moment a stage moved the hole, and keying on
        geometry cannot work because two coincident circles — precisely the
        duplicate case — are measured identically.

        The nominal values are nanometres and the measurement is millimetres, so
        the one ``index`` argument fills both fields and the three lengths are
        converted on the way into ``raw``.
        """
        return cls(
            x_nm=x_nm,
            y_nm=y_nm,
            diameter_nm=diameter_nm,
            raw=RawHole(
                mm_from_nm(x_nm), mm_from_nm(y_nm), mm_from_nm(diameter_nm), index
            ),
            index=index,
        )

    def moved_to(self, x_nm: int, y_nm: int) -> Hole:
        return replace(self, x_nm=x_nm, y_nm=y_nm)

    def with_diameter(self, diameter_nm: int) -> Hole:
        return replace(self, diameter_nm=diameter_nm)

    def translated(self, dx_nm: int, dy_nm: int) -> Hole:
        """Move the hole, exactly.

        Integers are what make "exactly" true: a thousand shifts one way and a
        thousand back land on the value they started from, where the same walk
        in millimetres does not. This is what the Excellon emitter's lower-left
        frame rides on: it is the one caller of ``DrillData.with_origin``, and
        it moves every hole by half the outline while the drawing dimensions the
        same panel from the centre frame it was handed. Two frames, one set of
        positions, and no rounding between them to disagree about.

        The deltas are guarded here and not left to the constructor, because the
        addition happens first and normalises the mistake away: ``True + 0`` is
        ``1``, so ``__post_init__`` would be handed a perfectly good nanometre
        and the hole would sit one nanometre from where it started with nothing
        left to say a boolean was ever passed. A guard on a field cannot see
        what the arithmetic has already absorbed.
        """
        _check_nanometres("Hole.translated", dx_nm=dx_nm, dy_nm=dy_nm)
        return replace(self, x_nm=self.x_nm + dx_nm, y_nm=self.y_nm + dy_nm)

    @property
    def residual_nm(self) -> tuple[int, int, int]:
        """(dx, dy, ddia) between nominal and measured, in nanometres.

        Positive means the nominal value is the larger. Suffixed like every
        other length here, because a caller printing this as millimetres would
        be six decimal places out with nothing on the sheet to notice.

        The subtraction crosses a unit, and it is the measurement that is
        quantised to meet the nominal value rather than the other way about:
        this is a printed figure, and the un-quantised measurement stays on
        ``raw`` for anyone who wants it.
        """
        return (
            self.x_nm - nm_from_mm(self.raw.x),
            self.y_nm - nm_from_mm(self.raw.y),
            self.diameter_nm - nm_from_mm(self.raw.diameter),
        )


@dataclass(frozen=True, slots=True)
class RawOutline:
    """The outline as measured off the artwork, in millimetres, before snapping.

    ``RawHole`` to ``ReferenceOutline``'s ``Hole``: same reason, one level up.
    It carries no identity of its own, because there is only ever one of these
    per document.
    """

    width: float
    height: float

    def __post_init__(self) -> None:
        _check_millimetres("RawOutline", width=self.width, height=self.height)


#: Constructor sentinel for ``ReferenceOutline.raw`` meaning "nobody has snapped
#: this, so its nominal size *is* the measurement". It is not a value any outline
#: keeps: ``__post_init__`` replaces it with the instance's own dimensions, and
#: the identity test means a caller who really does pass ``RawOutline(0.0, 0.0)``
#: gets it back. A ``None`` default would have been the obvious spelling and the
#: wrong one — every reader of ``raw`` would then have to decide what an absent
#: measurement means, which is the ambiguity the field was added to remove.
_MEASUREMENT_IS_NOMINAL = RawOutline(0.0, 0.0)


@dataclass(frozen=True, slots=True)
class ReferenceOutline:
    """The panel outline that establishes the coordinate frame.

    ``centre_x_nm``/``centre_y_nm`` are in *source* space — the page frame,
    measured from its lower-left corner — and exist only so the document can
    report the point everything else was centred on. Nanometres and not the
    points the PDF is written in, and the suffix is doing real work on these
    two: they are the pair most tempting to carry over as read, they are in the
    published document, and 72/25.4 is the difference between a page centre and
    nonsense. Everything downstream works in the canonical frame, where this
    outline is centred on the origin.

    ``raw`` is the as-measured size, kept for the same reason ``Hole.raw`` is:
    a stage snaps the outline to a catalogue enclosure, and the fixture panel
    measures 113.000 × 60.000 mm where the Hammond datasheet says 112 × 61. That
    snap rewrites a real measurement, and without ``raw`` nothing downstream
    could tell a 113 that was measured from a 113 that was snapped to — nor
    could a drawing quote what the artwork actually said. ``processing`` cannot
    stand in for it: a ``StageRun`` records a stage's configuration, not a
    result that depends on the data it was handed.
    """

    width_nm: int
    height_nm: int
    centre_x_nm: int = 0
    centre_y_nm: int = 0
    raw: RawOutline = _MEASUREMENT_IS_NOMINAL

    def __post_init__(self) -> None:
        _check_nanometres(
            "ReferenceOutline",
            width_nm=self.width_nm,
            height_nm=self.height_nm,
            centre_x_nm=self.centre_x_nm,
            centre_y_nm=self.centre_y_nm,
        )
        if self.width_nm <= 0 or self.height_nm <= 0:
            raise ValueError(
                f"reference outline must be positive, got {self.width_nm}x{self.height_nm}"
            )
        if self.raw is _MEASUREMENT_IS_NOMINAL:
            object.__setattr__(
                self,
                "raw",
                RawOutline(mm_from_nm(self.width_nm), mm_from_nm(self.height_nm)),
            )

    @classmethod
    def from_measurement(
        cls, width_nm: int, height_nm: int, centre_x_nm: int = 0, centre_y_nm: int = 0
    ) -> ReferenceOutline:
        """Build an outline whose nominal size is still its measured size.

        Mirrors ``Hole.from_measurement``, down to converting the two lengths on
        the way into ``raw``: the measurement is recorded once, where it is still
        known, rather than being reconstructed later from a nominal size that a
        snap may already have moved.
        """
        return cls(
            width_nm=width_nm,
            height_nm=height_nm,
            centre_x_nm=centre_x_nm,
            centre_y_nm=centre_y_nm,
            raw=RawOutline(mm_from_nm(width_nm), mm_from_nm(height_nm)),
        )

    def resized(self, width_nm: int, height_nm: int) -> ReferenceOutline:
        """New nominal dimensions, same measurement, same source-space centre.

        ``raw`` is deliberately *not* carried forward from the previous nominal
        size: that would read identically after one snap and be wrong after two,
        and nothing forbids a second one.
        """
        return replace(self, width_nm=width_nm, height_nm=height_nm)


@dataclass(frozen=True, slots=True)
class EnclosureMatch:
    """Which catalogue enclosure the panel outline was drawn for.

    Derived, not read off the file: a stage compares the reference outline
    against a catalogue and records what it found. That is why this is neither
    ``SourceInfo`` — which says where the bytes came from, and would be lying if
    it carried a conclusion reached three stages later — nor a ``StageRun``,
    which records what a stage was *configured* to do. Leaving the current
    enclosure in the execution log would send the drawing and every downstream
    consumer hunting through a generic key/value history for a domain fact,
    which is the very inference ``processing`` was introduced to stop.

    **A 2-D outline identifies a footprint, never a part.** Hammond's 1590
    parts collapse into markedly fewer distinct length × width footprints,
    because many differ only in height: 112 × 61 is 1590B, 1590B2 *and* 1590BS;
    120 × 94 is 1590BB, 1590BB2, 1590BBS and 1590C. So ``candidates`` is a tuple
    of every base designator sharing the footprint, and ``selected_part`` — the
    one part the panel is actually for — starts as ``None`` and can only ever be
    filled in by the operator. Nothing here may infer it from geometry; the
    artwork simply does not contain it.

    An *empty* ``candidates`` has no meaning and must never be constructed: the
    answer to "no footprint matched" is ``DrillData.enclosure is None``, not a
    match naming nothing. A stage that cannot identify the outline reports
    ``unknown-enclosure`` and leaves the field unset.

    ``length_nm``/``width_nm`` are the catalogue's own dimensions, carried in
    the model's unit like every other length here. They stay in the catalogue's
    orientation even when ``rotated`` is set: a portrait panel is the same
    enclosure turned 90°, not a second footprint, and transposing them here
    would make it unfindable in the datasheet it came from.

    No check is made that ``selected_part`` is among ``candidates``. A panel
    declared as one case and drawn to another is an operator error that must
    reach the report as a diagnostic naming both; raising here would abort the
    run instead, with nothing to render.
    """

    family: str
    length_nm: int
    width_nm: int
    candidates: tuple[str, ...]
    rotated: bool = False
    selected_part: str | None = None

    def __post_init__(self) -> None:
        """Guard the two lengths, coerce ``candidates``, and refuse a bare string.

        The dimensions are guarded here for the same reason every other length
        in this module is: this is a *derived* value, built by a stage out of a
        catalogue and handed straight to ``DrillData.enclosure``, from which the
        drawing prints a footprint and the JSON serialises one. A float that
        reached this far would be two artifacts' worth of rounding under a name
        that promises nanometres.

        The coercion is the same one ``StageRun`` and ``Diagnostic`` do, for the
        same reason: a match holding a list is unhashable and compares unequal
        to the identical match built from a tuple, so a document read back from
        JSON — where every sequence arrives as a list — would differ from the
        one it was written from while printing identically.

        The guard is *not* shared with them, and the asymmetry is structural
        rather than incidental. Their payloads are tuples of pairs, so a string
        fed in where a sequence belongs fails on unpacking and the mistake
        reports itself. ``candidates`` is a flat ``tuple[str, ...]``, where
        ``tuple("1590B")`` yields five single-character designators that satisfy
        the declared type, compare and hash cleanly, and would go on to print a
        candidate list of "1", "5", "9", "0", "B" on a machinist's sheet without
        ever failing. This is the one place the type annotation cannot catch a
        type error, so it is caught here.
        """
        _check_nanometres(
            "EnclosureMatch", length_nm=self.length_nm, width_nm=self.width_nm
        )
        # The ignore is the point restated: mypy is right that a declared
        # tuple[str, ...] is never a str, and this guard exists for the callers
        # it cannot see — JSON, a REPL, a downstream tool.
        if isinstance(self.candidates, str):  # type: ignore[unreachable]
            raise TypeError("candidates must be a sequence of designators, not a single string")
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A finding. Stages append these; emitters render them.

    ``code`` is the stable machine key — tests and downstream tools match on it,
    never on ``message``.
    """

    severity: Severity
    code: str
    message: str
    location_nm: tuple[int, int] | None = None
    data: tuple[tuple[str, float | int | str], ...] = ()

    def __post_init__(self) -> None:
        """Coerce the position and the payload to tuples, then guard the lengths.

        ``location_nm`` is a point in the canonical frame and is guarded like
        any other position: a stage reporting where a hole ended up has the
        millimetres it printed in the message right there to hand, and handing
        them over here instead would put a finding somewhere the artifacts do
        not agree it is. ``None`` stays legal — a finding about the panel as a
        whole has no coordinate to give.

        The coercion is the same one ``StageRun`` and ``EnclosureMatch`` do, and
        it reaches three sequences because a finding read back from JSON arrives
        with a list in every one of them: the location, the payload, and each
        key/value pair inside the payload. A finding holding any of those prints
        exactly like the one the pipeline produced, compares unequal to it, and
        is unhashable beside it — so the obvious way to reconstruct a document
        from the emitted JSON would yield findings a consumer could neither
        compare nor put in a set, for reasons visible nowhere in the output.

        It runs before the guard, as in ``StageRun``, so that the guard reads
        the payload in the shape the object will keep. The two orders happen to
        agree on what they refuse here — a finding's payload values are scalars,
        so no coercion changes what ``_check_payload_lengths`` looks at — but
        checking first would leave the coercion as the only step that reads the
        caller's argument, and a payload handed over as a generator would be
        consumed by the guard and stored empty.

        Normalising here rather than in the three convenience constructors is
        the same choice one level up: they are not the only way a finding is
        built, and a coercion living there leaves ``dataclasses.replace`` and a
        consumer's direct construction as ways in that skip it.
        """
        if self.location_nm is not None:
            x_nm, y_nm = self.location_nm
            object.__setattr__(self, "location_nm", (x_nm, y_nm))
            _check_nanometres("Diagnostic", location_x_nm=x_nm, location_y_nm=y_nm)
        object.__setattr__(self, "data", tuple((key, value) for key, value in self.data))
        _check_payload_lengths("Diagnostic.data", self.data)

    @classmethod
    def warning(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.WARNING, code, message, location_nm, data)

    @classmethod
    def info(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.INFO, code, message, location_nm, data)

    @classmethod
    def error(cls, code, message, location_nm=None, data=()) -> Diagnostic:
        return cls(Severity.ERROR, code, message, location_nm, data)

    def get(self, key: str, default=None):
        """Read one payload value. Emitters use this instead of re-deriving.

        ``data`` exists so that a consumer can act on a finding without
        recomputing the predicate that produced it. The drawing emitter needs to
        know *which* hole a ``duplicate-hole`` refers to; recomputing that from
        positions meant re-implementing Deduplicate's rule, badly.
        """
        for k, v in self.data:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Where the data came from, for title blocks and file headers."""

    path: str = ""
    drill_layer: str = ""
    reference_layer: str = ""
    layers_found: tuple[str, ...] = ()
    producer: str = "aidrill"


@dataclass(frozen=True, slots=True)
class StageRun:
    """What one stage was configured to do, recorded once it has done it.

    Deliberately generic — a name and a key/value payload, the same idiom as
    ``Diagnostic.data`` — rather than one record class per stage. A closed union
    of record types would have to grow a member for every new stage, which is
    precisely the extensibility ``Stage`` exists to protect: ``Pipeline`` records
    what the abstraction hands it and knows nothing about grids or diameters.

    ``parameters`` holds *effective* values, not raw constructor arguments: the
    drawing needs the grid numerically, so recording ``None`` for a threshold
    that resolved to 0.0625 would defeat the point of recording it at all.
    """

    name: str
    parameters: tuple[tuple[str, ParameterValue], ...] = ()

    def __post_init__(self) -> None:
        """Coerce the payload to tuples, then hold its lengths to their names.

        The coercion is not defensive tidying: a record holding a list is
        unhashable and compares unequal to the identical record built from
        tuples, so a document read back from JSON — where every sequence arrives
        as a list, the pairs and a diameter table alike — would differ from the
        one it was written from while printing identically.

        It runs before the guard so that a diameter table arriving from JSON is
        checked as the tuple it has just become, rather than slipping past a
        check that only knows what to do with one.
        """
        object.__setattr__(
            self,
            "parameters",
            tuple(
                # Same shape of ignore as ``EnclosureMatch``: ParameterValue
                # never includes list, and a document read back from JSON is
                # exactly where one arrives anyway.
                (key, tuple(value) if isinstance(value, list) else value)  # type: ignore[unreachable]
                for key, value in self.parameters
            ),
        )
        _check_payload_lengths("StageRun.parameters", self.parameters)

    def get(self, key: str, default=None):
        """Read one parameter. Mirrors ``Diagnostic.get`` so there is one idiom.

        A key a stage did not report is simply absent — the drawing asks for the
        grid and gets ``None`` from a run that never had one, rather than a
        plausible-looking default it would then print on a machinist's sheet.
        """
        for k, v in self.parameters:
            if k == key:
                return v
        return default


@dataclass(frozen=True, slots=True)
class RawDrillData:
    """Everything a source read, in millimetres, with nothing quantised yet.

    This is what a ``Source`` returns and what the quantisation phase consumes.
    It is a separate type from ``DrillData`` rather than a mode of it because
    the difference is not a flag: nothing here has a nominal value, so there is
    no tool table to build, no row to group and no frame to translate — the only
    thing that can legitimately be done with one of these is quantise it.

    ``reference`` is ``None`` when the reference layer held no non-circular
    path. The source has nothing to centre on then, so it reports page-relative
    positions and a WARNING rather than inventing an outline, and ``centre`` is
    ``(0.0, 0.0)``.

    ``centre`` sits here and not on ``RawOutline`` because it is a fact about
    where the outline sat on the page, not a dimension of the outline: two
    panels of identical size drawn at different places on one artboard have the
    same ``RawOutline`` and are not the same read.
    """

    source: SourceInfo
    reference: RawOutline | None
    centre: tuple[float, float]
    holes: tuple[RawHole, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Guard the centre, elementwise.

        It is the one raw length not held by a value type of its own, and it is
        also the widest-blast-radius one: it is the point every hole's position
        is measured from, so an int nanometre here displaces the whole canonical
        frame by six orders of magnitude rather than spoiling one field on one
        hole, and a ``True`` puts the origin a nanometre from the page corner —
        a panel no report would make look wrong.

        Elementwise for the reason ``_check_payload_lengths`` checks a tuple
        that way: a scalar-only check would leave both coordinates the only
        unexamined lengths in the model.
        """
        x, y = self.centre
        _check_millimetres("RawDrillData", centre_x=x, centre_y=y)


@dataclass(frozen=True, slots=True)
class DrillData:
    """The single object that travels the whole pipeline."""

    holes: tuple[Hole, ...] = ()
    reference: ReferenceOutline | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    source: SourceInfo = field(default_factory=SourceInfo)
    processing: tuple[StageRun, ...] = ()
    enclosure: EnclosureMatch | None = None

    # -- transforms ------------------------------------------------------
    def with_holes(self, holes: Iterable[Hole]) -> DrillData:
        return replace(self, holes=tuple(holes))

    def with_diagnostics(self, *diagnostics: Diagnostic) -> DrillData:
        if not diagnostics:
            return self
        return replace(self, diagnostics=self.diagnostics + tuple(diagnostics))

    def with_processing(self, *runs: StageRun) -> DrillData:
        """Append the record of a stage that has just run.

        Appended, never replaced: a stage may legitimately run twice — the CLI
        chooses the order, and nothing forbids two snaps — and the history is
        what happened, not a set of what was configured.
        """
        if not runs:
            return self
        return replace(self, processing=self.processing + tuple(runs))

    def with_enclosure(self, match: EnclosureMatch) -> DrillData:
        """Record which enclosure the panel was identified as being drawn for.

        Replaced, never appended — the mirror image of ``with_processing``.
        ``processing`` is history and a stage may legitimately run twice;
        ``enclosure`` is current state, and a consumer asking which enclosure
        this panel is must get one answer rather than a list to pick from.
        """
        return replace(self, enclosure=match)

    def with_origin(self, origin: Origin) -> DrillData:
        """Translate every hole into the requested frame.

        The canonical frame is CENTRE. LOWER_LEFT needs a reference outline to
        know where the lower-left corner is; without one there is no defensible
        answer, so this raises rather than guessing.

        An outline of an odd number of nanometres has no exact half, and the
        shift floors rather than introducing the first float into the model:
        half a nanometre is five decimal places below what any artifact prints,
        where a float coordinate is a quantity the drill file and the drawing
        could round differently. Every catalogue footprint is a whole number of
        millimetres, so after a snap the half is exact anyway.
        """
        if origin is Origin.CENTRE:
            return self
        if origin is Origin.LOWER_LEFT:
            if self.reference is None:
                raise ValueError("lower-left origin requires a reference outline")
            dx_nm = self.reference.width_nm // 2
            dy_nm = self.reference.height_nm // 2
            return self.with_holes(h.translated(dx_nm, dy_nm) for h in self.holes)
        raise ValueError(f"unknown origin {origin!r}")

    # -- derived ---------------------------------------------------------
    def tools(self) -> Mapping[int, int]:
        """Ordered {nominal diameter: 1-based tool number}, ascending by size.

        This lives on the model rather than in the Excellon emitter so that the
        drawing's hole schedule and the drill file's tool table cannot disagree.
        """
        return {d: i for i, d in enumerate(sorted({h.diameter_nm for h in self.holes}), start=1)}

    def tool_counts(self) -> Mapping[int, int]:
        """{nominal diameter: how many holes use it}, ascending by size.

        Beside tools() for the same reason tools() is here at all: the drawing's
        QTY column, the JSON summary and the CLI report must be one computation.
        """
        counts: dict[int, int] = {d: 0 for d in self.tools()}
        for hole in self.holes:
            counts[hole.diameter_nm] += 1
        return counts

    def rows(self) -> list[tuple[int, list[Hole]]]:
        """Holes grouped by Y, rows from the top down, each row left to right.

        Both orderings are contracts rather than incidental output, because both
        are read as ordering by a caller that cannot see this code:

        * **Rows descend.** The drawing stacks one chain dimension per row and
          builds the stack outwards from the bottom row, dropping the rows it
          has no room for. Ascending, the rows that silently lost their
          dimension would be the ones at the *bottom* of the panel rather than
          the top — the same sheet, dimensioning a different half of the work.
        * **A row runs left to right**, which is the direction a chain dimension
          is read and the order its segment lengths are subtractions in. Handed
          the holes in artwork order, a chain would double back on itself.

        Grouping is by exact equality, and there is no slack because there is
        nothing left for one to absorb. A slack absorbs rounding error, and
        every Y reaching here has been quantised: holes on one row are exact
        multiples of the same grid and therefore the identical integer. Where
        two integers differ they differ because the holes do — and no slack
        narrow enough to be safe would help anyway, since the smallest bucket
        wider than a nanometre is a micron, and a micron is already
        cross-artifact: 18.000 against 18.001 is two coordinates in the drill
        file and one row on the drawing.
        """
        buckets: dict[int, list[Hole]] = {}
        for hole in self.holes:
            buckets.setdefault(hole.y_nm, []).append(hole)
        return [
            (y_nm, sorted(hs, key=lambda h: h.x_nm))
            for y_nm, hs in sorted(buckets.items(), reverse=True)
        ]

    def last_run(self, stage_name: str) -> StageRun | None:
        """The most recent record for ``stage_name``, or ``None`` if it never ran.

        The drawing's title block must state the grid these holes were actually
        snapped to. It was told a second copy through its own options instead,
        so data snapped at 0.5 could be stamped 0.25 on the sheet a machinist
        reads. ``None`` — no such stage ran — is a real answer here, and the
        caller must render it as "not snapped", never as a default value.
        """
        for run in reversed(self.processing):
            if run.name == stage_name:
                return run
        return None

    def of_severity(self, severity: Severity) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is severity)

    @property
    def worst_severity(self) -> Severity | None:
        return max((d.severity for d in self.diagnostics), default=None)
