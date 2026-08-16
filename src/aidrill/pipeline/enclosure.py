"""Quantise the reference outline onto the Hammond 1590 catalogue.

The reference outline is *measured* artwork. The fixture panel reads
113.000 × 60.000 mm where Hammond's drawing says 1590B is 112.400 × 60.500, and
that half-millimetre per side is not a drawing error the operator can see — it is
what a bounding box of a stroked path in a PDF comes to. Everything downstream
then inherits the wrong number: the drawing dimensions a panel that does not
exist, and a consumer computing edge clearance from ``reference.width_nm`` is out
by half a millimetre on the axis where a jack barrel has least to spare.

So this quantiser turns "roughly 112 × 61" into a named footprint and returns
the catalogue's own dimensions. Eight things about how it does it were each
decided the hard way:

**The answer set is the catalogue, or the measurement itself.** A panel that
matches a footprint comes back as that footprint's own nanometres, exactly,
because those are a number Hammond publishes rather than a number we computed.
The catalogue is held in nanometres end to end — ``footprints()`` is keyed in
them — so nothing here converts a unit, and there is no factor of a million to
apply twice or forget. A panel that matches nothing still comes back — quantised
to whole nanometres and otherwise untouched — because ``unknown-enclosure`` is a
WARNING, the run goes on, and every artifact it writes needs a frame. Returning
nothing there would leave the drawing with no panel to dimension and the Excellon
emitter no corner to translate to, on a panel whose only fault is not being one
of the 26 footprints this catalogue holds.

**The measurement is compared without ever being rounded.** ``scaled_nm``
scales it into a ``Decimal`` and stops; only the *comparison* against each
integer candidate happens. Quantising first manufactures ties the measurement
did not have — 113.9000004 mm is four tenths of a nanometre outside a 1.5 mm
tolerance around 1590B's 112.4 mm, and rounding it to whole nanometres first puts
it exactly on the boundary, inside. The catalogue is non-uniform, so there is
nothing to divide by and nothing else to round.

**It snaps through** :meth:`ReferenceOutline.resized`, **never by constructing a
new outline.** ``ReferenceOutline(112_400_000, 60_500_000)`` is legal code whose
``raw`` defaults to its own dimensions — so a fresh construction quietly asserts
that the panel was *measured* at 112.4 × 60.5 and destroys the 113 × 60 the
artwork actually said. The measurement handed in is put on ``raw`` once, here, and every
answer below is that outline resized.

**It never guesses.** An unresolved tie is ``ambiguous-enclosure`` and a declared
part that contradicts the artwork is ``wrong-enclosure``, both at ERROR naming
every candidate, rather than the nearest footprint or the first row. The one
thing that may pick between two footprints is the operator's own declaration,
which is knowledge and not arithmetic. A panel drilled for the wrong case is
scrap aluminium; a refusal costs a re-run. Silence is reserved for the one case
it means something: a unique match within tolerance, where saying so on every
run would train the operator to skim past the runs that matter.

**No match at all is only a WARNING — when nothing was declared — and the
asymmetry is the argument.** A panel that omits a reference layer comes back
untouched and clean, because the source has already reported the absence and a
quantiser may not assume more than it was handed. So an ERROR here would mean
that *drawing* your outline is punished while *not* drawing it is not, which is
backwards at any severity. The principle underneath: "two Hammond footprints fit
yours" and "you declared a part your artwork contradicts" are statements about
the operator's panel, but "we have never heard of your enclosure" is a statement
about **our catalogue** — this tool holds 26 Hammond footprints and the world
holds rather more. The same rule the drill table follows: we cannot know what
another builder is working in. The finding is raised, the run continues, the
outline keeps the size it was drawn at, and the operator decides.

**A declared case is checked on every outcome, and that is what makes it worth
declaring.** ``expected_part`` is compared on all four, not only on a unique
match: the three ways identification can fail — no reference outline, no
footprint, a tie — must each end at the assertion rather than walk past it. The
likely combination is otherwise also the worst one: a declared case, an outline
nothing recognised, ``unknown-enclosure`` at WARNING, and a drill file written
for a panel the operator had just told us they did not believe in. ``--case`` is
the only assertion the command line can make about the panel's size, and an
assertion that holds on some paths is not one. So whenever a case is declared,
every path ends in a confirmed match or an ERROR, and a tie is resolved when the
declared part's own footprint is one of the tied ones — the operator's
declaration is the outside knowledge the catalogue lacks, which is exactly what
breaks a tie without guessing. Those three ERRORs are also why the enclosure is
the first thing quantised: an ERROR withholds every artifact, and finding it
first means no hole was quantised for a run that will write nothing.

**Three ERROR codes, because they ask for three different actions.** A consumer
routes on ``code``, so a key that needs its payload inspected to tell two
findings apart is not a key. ``wrong-enclosure`` is the only one that *identifies*
the panel: a single footprint fits, it is not the declared part, and the message
can name both. ``unmatched-enclosure`` says the declared part was not matched —
either nothing fitted or several things did and none of them was yours — and it
is deliberately not ``wrong-enclosure``, because with nothing identified the
accusation would be unfounded: by the backplate convention below, the most likely
panel here is the declared case measured across its drilled face. Sending that
operator to change ``--case`` would be sending them away from the fix.
``unverifiable-enclosure`` is the third action again — there is no outline at
all, so nothing can be compared and the reference layer is what has to change.
None of the three reuses ``unknown-enclosure``: that code is a WARNING about our
catalogue on an undeclared run, and one key at two severities meaning two things
is a key a consumer cannot act on.

**A 2-D outline identifies a footprint, not a part.** 112.40 × 60.50 is 1590B
*and* 1590B2 — they differ only in height, which artwork does not carry. The
match therefore names candidates, and ``selected_part`` is filled in only from
what the operator declared.

**Four footprint pairs cannot be told apart from artwork, and that is reported
rather than resolved.** The catalogue holds Hammond's 0.05 mm figures, so parts
that shared an outline while both were rounded to whole millimetres no longer do:
1590BS is 112.00 × 60.50 against 1590B's 112.40 × 60.50, and 1590LLB, 1590KK and
1590D each sit within half a millimetre of a neighbour the same way. No tolerance
separates a 0.10 mm pair while still admitting artwork measured a millimetre off,
which is what the fixture is, so a panel near one of these four gets
``ambiguous-enclosure`` and needs a ``--case``. That is the honest answer: the
enclosures genuinely differ, and rounding the key back to whole millimetres to
avoid saying so would be this tool deciding on the operator's behalf that a
112.00 backplate is a 112.40 one.

**The catalogue holds BACKPLATE dimensions, and so must the artwork.** A 1590 is
die-cast with drafted walls -- the datasheet says "low side wall draft angle (2°
or less)" -- so the face that gets drilled is smaller than the backplate by
``2 * depth * tan(angle)`` per axis: 1.9 mm on a 1590B, 6.3 mm on a 1590V. No
tolerance can take a face-drawn outline, and on a 1590B the reason is exact
rather than approximate: its face measures about 110.5 × 58.6, which is 1.9 mm
from its own 112.40 × 60.50 *and* 1.9 mm from 1590BS's 112.00 × 60.50 on the
tighter axis. Both footprints are therefore admitted at the very same tolerance
the face needs, so widening does not identify the panel — it only turns a refusal
into a tie between two real enclosures. The convention is the fix, not a number,
and ``_unknown``'s message names it: the operator this catches is the one who
measured *more* carefully. ``docs/adr/0002-domain-quantisers.md`` records the
arithmetic.

The default tolerance of 1.5 mm is bounded from both sides, not chosen for the
fixture. Below, it must absorb the error in measured artwork: the fixture is
1.000 mm from one candidate footprint and 0.600 mm from the other. Above, it must
stay under the wall draft, or a face-drawn panel would start matching — 1.9 mm on
a 1590B — and it must not tie footprints that are *not* one of the four above;
the closest such pair is 4 mm apart (1590B3 116 × 77 against 1590T 120 × 80), so
a fifth tie becomes reachable at 2.0 mm. ``tests/test_enclosure.py`` pins both
bounds against the real catalogue, and names the four inherent pairs, so a
revision that changes which panels need a declared case fails loudly instead of
changing the answer in silence.
"""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from ..enclosures import footprints
from ..model import (
    Diagnostic,
    EnclosureMatch,
    ParameterValue,
    RawOutline,
    ReferenceOutline,
    StageRun,
)
from ..units import format_nm, nm_from_mm, scaled_nm

__all__ = [
    "CATALOGUE",
    "DEFAULT_TOLERANCE_NM",
    "normalize_part_name",
    "IdentifyHammondFootprint",
]

#: The catalogue this quantiser searches, named once so the ``EnclosureMatch``
#: family and the ``StageRun`` provenance cannot drift into two spellings of
#: the same fact.
CATALOGUE: str = "Hammond 1590"

#: 1.5 mm per axis. Derived from the catalogue's own closest pair rather than
#: from any panel — see the module docstring, and the test that recomputes the
#: bound from the shipped table on every run.
DEFAULT_TOLERANCE_NM: int = 1_500_000

#: The one piece of advice every "nothing fitted" message has to carry, written
#: once for the same reason ``CATALOGUE`` is: two findings say it — an
#: unrecognised outline and a declaration nothing could confirm — and an
#: operator who read one wording on Tuesday and the other on Wednesday would
#: reasonably think they were two different problems.
_BACKPLATE_ADVICE: str = (
    "the catalogue lists backplate dimensions, and a drilled face is smaller "
    "than its backplate because the walls are drafted — if this outline is a "
    "face measurement, redraw the reference layer to the backplate size"
)

#: One footprint that fitted, and whether the panel is that footprint turned 90°.
_Match = tuple[tuple[int, int], bool]


def normalize_part_name(name: str) -> str:
    """Put an operator-typed part number into catalogue form.

    Case and surrounding whitespace only. That is the whole contract, and the
    restraint is deliberate: the obvious extension is to collapse an order code
    such as ``1590BBBK`` onto its base designator, which needs the datasheet's
    suffix grammar — colour, flange, watertight — whose ``1590W`` and flange
    interactions have already produced one wrong answer in this project. A
    collapse that lands on the wrong base part is silent and drills the wrong
    panel; a name this function leaves alone is reported as ``wrong-enclosure``
    naming both parts, which the operator can read and correct.

    Written here rather than borrowed from ``tools/extract_1590.py``: that
    module is an unshipped generator, its collapse is private, and a contract
    the runtime depends on must be owned where it is used.
    """
    return name.strip().upper()


class IdentifyHammondFootprint:
    """Match the reference outline against the Hammond 1590 catalogue.

    ``expected_part`` is what the operator declared the panel to be, and every
    outcome is checked against it. ``tolerance_nm`` is the per-axis slack
    allowed between the measured outline and a catalogue footprint; the default
    is bounded by the catalogue and must not be widened to take a face-drawn
    panel, which is the module docstring's last two paragraphs.

    With nothing declared, a missing reference outline is not a finding here —
    the source may have had no reference layer, and it has already raised a
    WARNING naming the frame its positions are in — so the answer is three
    empties. With a case declared it is an ERROR, because the declaration is
    then the one thing this quantiser was asked to check and it cannot be
    checked at all.
    """

    name: ClassVar[str] = "identify-enclosure"

    def __init__(
        self, expected_part: str | None = None, tolerance_nm: int = DEFAULT_TOLERANCE_NM
    ) -> None:
        # Checked once, at construction, on the precedent every length in the
        # model sets and for its reason: a float tolerance is a length that
        # never crossed ``units``, and left alone it surfaces three paths later
        # as the payload guard firing inside a diagnostic nobody was watching.
        # ``type(...) is not int`` and not ``isinstance``, because ``bool`` is
        # an ``int`` in Python and ``True`` is a one-nanometre tolerance that
        # matches nothing on earth.
        if type(tolerance_nm) is not int:
            raise TypeError(
                f"tolerance_nm must be a whole number of nanometres, not {tolerance_nm!r}"
            )
        # A negative slack is refused for the reason a float is, one step on: no
        # measurement is inside it, so every panel on earth becomes
        # ``unknown-enclosure`` — a WARNING, so the run goes on and dimensions
        # the drawing to the outline as measured, with nothing anywhere saying
        # that the catalogue was never really searched. Zero is a real bound: an
        # outline that *is* a catalogue footprint, to the nanometre.
        if tolerance_nm < 0:
            raise ValueError(
                f"tolerance_nm cannot be a negative distance, got {tolerance_nm!r}"
            )
        self.tolerance_nm = tolerance_nm
        # Normalised once, at construction, so the value compared against the
        # candidates, the value recorded in ``selected_part`` and the value
        # ``describe`` publishes are one value rather than three chances to
        # differ. A blank declaration is no declaration: an empty ``--case``
        # must not become a part number that nothing can ever match.
        resolved = normalize_part_name(expected_part) if expected_part is not None else ""
        self.expected_part: str | None = resolved or None

    def describe(self) -> StageRun:
        """Effective values: the resolved part name, not the string as typed.

        ``expected_part`` is omitted entirely when nothing was declared rather
        than recorded as empty — ``StageRun.get`` cannot tell an absent key from
        a null one, and a consumer that found the key would believe a case had
        been declared.
        """
        parameters: list[tuple[str, ParameterValue]] = [
            ("tolerance_nm", self.tolerance_nm),
            ("catalogue", CATALOGUE),
        ]
        if self.expected_part is not None:
            parameters.append(("expected_part", self.expected_part))
        return StageRun(self.name, tuple(parameters))

    def quantise(
        self, outline: RawOutline | None, centre: tuple[float, float]
    ) -> tuple[ReferenceOutline | None, EnclosureMatch | None, tuple[Diagnostic, ...]]:
        """The outline as the domain holds it, what it was identified as, findings.

        ``centre`` is where the outline sat on the page. It comes in separately
        because it is a fact about the *read* and not a dimension of the
        outline — two identical panels drawn at different places on one artboard
        measure the same — and this is the only place in the program positioned
        to put the two together.
        """
        if outline is None:
            # The source has already said so, with a WARNING of its own naming
            # the frame the holes are in; a second finding would report one
            # absence twice. A declaration cannot be let past, though, because
            # there is nothing here to check it against and silence would read
            # exactly like a confirmed one.
            if self.expected_part is None:
                return (None, None, ())
            return (None, None, (self._unverifiable(),))

        # The measurement, quantised and kept: ``raw`` is the ``RawOutline`` the
        # source handed over, so what follows can only ever *resize* this and
        # can never overwrite what the artwork said.
        measured = ReferenceOutline(
            width_nm=nm_from_mm(outline.width),
            height_nm=nm_from_mm(outline.height),
            centre_x_nm=nm_from_mm(centre[0]),
            centre_y_nm=nm_from_mm(centre[1]),
            raw=outline,
        )

        matches = self._matches(outline)
        if self.expected_part is not None:
            # A part belongs to exactly one footprint, so this filter yields one
            # match or none — which is why a declaration always ends a tie, one
            # way or the other, and why the ambiguous report below is only ever
            # reached by a run that declared nothing.
            declared = [
                match for match in matches if self.expected_part in footprints()[match[0]]
            ]
            if declared:
                matches = declared
            elif len(matches) != 1:
                # Nothing fitted, or several did and none was the declared part.
                # A single fit falls through instead, so that the panel is still
                # identified and ``wrong-enclosure`` can name what was drawn.
                return (measured, None, (self._unmatched(measured, matches),))

        if not matches:
            return (measured, None, (self._unknown(measured),))
        if len(matches) > 1:
            return (measured, None, (self._ambiguous(measured, matches),))

        (length_nm, width_nm), rotated = matches[0]
        candidates = footprints()[(length_nm, width_nm)]
        match = EnclosureMatch(
            family=CATALOGUE,
            length_nm=length_nm,
            width_nm=width_nm,
            candidates=candidates,
            # Always explicit. The field defaults to False, so a matcher that
            # forgot to work rotation out would report every portrait panel as
            # landscape and nothing would say otherwise.
            rotated=rotated,
            selected_part=self.expected_part,
        )
        # ``resized``, never ``ReferenceOutline(...)``: see the module docstring.
        # The artwork's own orientation is kept — a rotated panel stays portrait
        # — while the match records the catalogue's canonical length and width.
        if rotated:
            snapped = measured.resized(width_nm, length_nm)
        else:
            snapped = measured.resized(length_nm, width_nm)

        if self.expected_part is not None and self.expected_part not in candidates:
            return (snapped, match, (self._wrong(length_nm, width_nm, candidates),))
        return (snapped, match, ())

    # -- matching --------------------------------------------------------
    def _matches(self, outline: RawOutline) -> list[_Match]:
        """Every footprint the outline could be, with whether it is turned 90°.

        Both readings are tried, and the unrotated one wins when both fit. That
        only happens for a square footprint, where the two readings describe the
        same panel; calling it a rotation would put "rotated" on a drawing for a
        panel nobody turned. Sorted so the tie report is stable — the order is
        for the *message*, never for picking a winner.
        """
        width, height = scaled_nm(outline.width), scaled_nm(outline.height)
        found: list[_Match] = []
        for footprint in sorted(footprints()):
            length_nm, width_nm = footprint
            if self._fits(width, height, length_nm, width_nm):
                found.append((footprint, False))
            elif self._fits(width, height, width_nm, length_nm):
                found.append((footprint, True))
        return found

    def _fits(
        self, width: Decimal, height: Decimal, width_nm: int, height_nm: int
    ) -> bool:
        """Both axes, and both are load-bearing: an outline that is right across
        and 4 mm out top to bottom is not that enclosure."""
        return self._near(width, width_nm) and self._near(height, height_nm)

    def _near(self, measured: Decimal, catalogue_nm: int) -> bool:
        """One axis, exactly, against one catalogue dimension.

        The catalogue side needs no conversion — ``footprints()`` is keyed in
        nanometres — so the only two numbers here are a measurement and a
        constant, in one unit.

        The measurement arrives as a ``Decimal`` and stays one: quantising it to
        whole nanometres before the comparison would manufacture a tie it did
        not have and could pull a panel four tenths of a nanometre outside the
        tolerance to just inside it. That is also why this does not go through
        ``tolerance.within``, whose domain is the whole nanometres everything
        downstream is made of. The boundary decision is `within`'s all the same
        and is spelled to agree with it: a tolerance an operator typed is a
        number they meant, so exactly on it is inside it.
        """
        return abs(measured - catalogue_nm) <= self.tolerance_nm

    # -- diagnostics -----------------------------------------------------
    def _unknown(self, measured: ReferenceOutline) -> Diagnostic:
        """WARNING, not ERROR — the one finding here about *us* and not the panel.

        See the module docstring: a panel with no reference layer at all exits 0,
        so refusing one that has an outline we do not recognise would punish the
        operator for drawing it. The outline keeps the size it was drawn at, and
        the run goes on.

        The message names the backplate convention because that is the single
        most likely reason a correct panel lands here, and the operator who
        lands there is the *careful* one — they measured the face they are about
        to drill. The catalogue lists backplate dimensions, and a 1590 face is
        smaller than its backplate by the wall draft — on a 1590B by the same
        1.9 mm that separates it from 1590BS, so the tolerance that would reach
        the face reaches both parts at once and identifies neither. A failure
        that teaches the fix costs a re-run; one that does not costs a case.
        """
        return Diagnostic.warning(
            "unknown-enclosure",
            f"reference outline {self._measured(measured)} "
            f"matches no {CATALOGUE} footprint within "
            f"{format_nm(self.tolerance_nm)} mm; "
            f"the outline has been left as drawn; {_BACKPLATE_ADVICE}",
            data=(
                ("width_nm", measured.width_nm),
                ("height_nm", measured.height_nm),
                ("tolerance_nm", self.tolerance_nm),
                ("catalogue", CATALOGUE),
            ),
        )

    def _ambiguous(self, measured: ReferenceOutline, matches: list[_Match]) -> Diagnostic:
        """Name every footprint that fitted, and every part on them.

        Naming one would be the guess. Naming none of the *parts* would be
        nearly as unhelpful: the message's advice is "declare the case", and the
        case is a part number, so a finding that withheld the two or three
        candidates would send the operator back to the datasheet to look up what
        it had already computed. That advice used to be for a tie an operator had
        to widen the tolerance to reach; now four catalogue footprints are within
        tolerance of a neighbour at the shipped default, so this is the ordinary
        answer for a panel near one of them — including this project's own
        fixture — and it has to carry the fix like ``_unmatched`` does.
        """
        tied = [footprint for footprint, _ in matches]
        return Diagnostic.error(
            "ambiguous-enclosure",
            f"reference outline {self._measured(measured)} is within "
            f"{format_nm(self.tolerance_nm)} mm of more than one {CATALOGUE} "
            f"footprint ({_footprint_list(tied)} mm — {_candidate_list(tied)}); "
            f"tighten the tolerance or declare the case",
            data=(
                ("footprints", _footprint_list(tied)),
                ("candidates", _candidate_list(tied)),
                ("tolerance_nm", self.tolerance_nm),
            ),
        )

    def _unverifiable(self) -> Diagnostic:
        """A case was declared and there is no outline to check it against.

        ERROR rather than the silence an undeclared run gets for the same
        missing layer, and the difference is the declaration and nothing else:
        an operator who said nothing is owed a usable run, while one who claimed
        the panel is a 1590B is owed the check they asked for. Passing silently
        would be indistinguishable from having made it.

        The declared part's catalogue footprint travels with the finding so a
        consumer can say what the panel ought to measure without going back to
        the catalogue this quantiser has already read.
        """
        return Diagnostic.error(
            "unverifiable-enclosure",
            f"panel declared as {self.expected_part}{self._expected_size()}, but the "
            f"artwork has no reference outline to check that against; draw the "
            f"enclosure outline on the reference layer, to its backplate dimensions",
            data=(("requested_part", self.expected_part or ""),)
            + self._expected_footprint_data()
            + (("catalogue", CATALOGUE),),
        )

    def _unmatched(self, measured: ReferenceOutline, matches: list[_Match]) -> Diagnostic:
        """A case was declared and the outline does not single that part out.

        Two ways to arrive, one finding: nothing fitted, or several footprints
        fitted and none of them was the declared part. Both leave the panel
        unidentified, which is why this is not ``wrong-enclosure`` — that code
        asserts we know what *was* drawn, and here we do not. It is not
        ``unknown-enclosure`` either: that one is a WARNING about the limits of
        our catalogue on a run that claimed nothing.

        ``footprints`` and ``candidates`` are always present and empty when
        nothing fitted, so the payload has one shape however the confirmation
        failed. The backplate advice rides along on the empty case because the
        careful operator — the one who measured the face they are about to drill
        — is the likeliest person to be reading this having declared the *right*
        part.
        """
        fitted = [footprint for footprint, _ in matches]
        if fitted:
            detail = (
                f"the reference outline {self._measured(measured)} is within "
                f"{format_nm(self.tolerance_nm)} mm of {_footprint_list(fitted)} mm "
                f"instead ({_candidate_list(fitted)})"
            )
        else:
            detail = (
                f"the reference outline {self._measured(measured)} matches no "
                f"{CATALOGUE} footprint within {format_nm(self.tolerance_nm)} mm; "
                f"{_BACKPLATE_ADVICE}"
            )
        return Diagnostic.error(
            "unmatched-enclosure",
            f"panel declared as {self.expected_part}{self._expected_size()}, but {detail}",
            data=(("requested_part", self.expected_part or ""),)
            + self._expected_footprint_data()
            + (
                ("width_nm", measured.width_nm),
                ("height_nm", measured.height_nm),
                ("tolerance_nm", self.tolerance_nm),
                ("catalogue", CATALOGUE),
                ("footprints", _footprint_list(fitted)),
                ("candidates", _candidate_list(fitted)),
            ),
        )

    def _expected_footprint(self) -> tuple[int, int] | None:
        """The declared part's own catalogue footprint, or ``None``.

        ``None`` is reachable only from a library caller: ``cli.parse_case``
        refuses a part number no catalogue holds before the file is opened. It
        is still an answer this has to have, because inventing a plausible size
        for a part nobody stocks is exactly the guess this quantiser refuses
        everywhere else.
        """
        for footprint, parts in footprints().items():
            if self.expected_part in parts:
                return footprint
        return None

    def _expected_footprint_data(self) -> tuple[tuple[str, float | int | str], ...]:
        """The declared footprint as payload, omitted entirely when unknown.

        Absent rather than zero or empty: ``Diagnostic.get`` answers ``None`` for
        a key that was never written, which is the truth, where a 0 × 0 would be
        a size a consumer could print on a machinist's sheet.
        """
        footprint = self._expected_footprint()
        if footprint is None:
            return ()
        return (
            ("expected_length_nm", footprint[0]),
            ("expected_width_nm", footprint[1]),
        )

    def _expected_size(self) -> str:
        """`` (112.400 × 60.500 mm)`` for a catalogue part, nothing for anything else."""
        footprint = self._expected_footprint()
        if footprint is None:
            return ""
        return f" ({_footprint_list([footprint])} mm)"

    def _wrong(self, length_nm: int, width_nm: int, candidates: tuple[str, ...]) -> Diagnostic:
        """Both parts, always: the requested one and the one that was drawn.

        Either alone leaves the operator re-deriving the other off the artwork,
        which is the measurement this quantiser exists to have already made.
        """
        identified = ", ".join(candidates)
        return Diagnostic.error(
            "wrong-enclosure",
            f"panel declared as {self.expected_part}, but the outline is "
            f"{_footprint_list([(length_nm, width_nm)])} mm — {identified}",
            data=(
                ("requested_part", self.expected_part or ""),
                ("identified_parts", identified),
                ("length_nm", length_nm),
                ("width_nm", width_nm),
            ),
        )

    @staticmethod
    def _measured(measured: ReferenceOutline) -> str:
        """``113.000 × 60.000 mm``, printed from the value the model holds.

        Not from ``raw``: the two agree to three decimals, and printing the one
        the outline actually carries is what keeps the sentence and the payload
        beside it two renderings of a single number.
        """
        return f"{format_nm(measured.width_nm)} × {format_nm(measured.height_nm)} mm"


def _footprint_list(footprints_nm: list[tuple[int, int]]) -> str:
    """``116.000 × 77.000, 120.000 × 80.000`` — the catalogue's own dimensions.

    Through `format_nm`, like every other length this program prints, and not as
    bare integers: the catalogue carries Hammond's 0.05 mm figures, so a 1590B is
    112.400 × 60.500 and printing it as ``112 × 61`` would round a physical
    constant on its way to the operator — and round it to the very whole
    millimetres that made 1590B and 1590BS look like one enclosure. The decimals
    are also the point of the message when two footprints tie: 112.000 × 60.500
    against 112.400 × 60.500 says why nothing could choose between them, where
    two identical ``112 × 61``s would read as a bug in the tool.
    """
    return ", ".join(
        f"{format_nm(length)} × {format_nm(width)}" for length, width in footprints_nm
    )


def _candidate_list(footprints_nm: list[tuple[int, int]]) -> str:
    """Every base designator sharing any of these footprints, in the same order."""
    return ", ".join(part for footprint in footprints_nm for part in footprints()[footprint])
