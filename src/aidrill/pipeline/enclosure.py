"""Identify which catalogue enclosure the panel outline was drawn for.

The reference outline is *measured* artwork. The fixture panel reads
113.000 × 60.000 mm where Hammond's datasheet says 1590B is 112 × 61, and that
0.5 mm per side is not a drawing error the operator can see — it is what a
bounding box of a stroked path in a PDF comes to. Everything downstream then
inherits the wrong number: the drawing dimensions a panel that does not exist,
and a consumer computing edge clearance from ``reference.width`` is out by half
a millimetre on the axis where a jack barrel has least to spare.

So this stage turns "roughly 112 × 61" into a named footprint and snaps the
outline to the catalogue's whole millimetres. Three things about how it does it
were each decided the hard way:

**It snaps through** :meth:`ReferenceOutline.resized`, **never by constructing a
new outline.** ``ReferenceOutline(112.0, 61.0)`` is legal code whose ``raw``
defaults to its own dimensions — so a fresh construction quietly asserts that
the panel was *measured* at 112 × 61 and destroys the 113 × 60 the artwork
actually said. Both spellings produce an identical-looking outline, which is why
the test that covers it runs the whole pipeline and reads the emitted document.

**It never guesses.** A tie is ``ambiguous-enclosure`` and a declared part that
contradicts the artwork is ``wrong-enclosure``, both at ERROR naming every
candidate, rather than the nearest footprint or the first row. A panel drilled
for the wrong case is scrap aluminium; a refusal costs a re-run. Silence is
reserved for the one case it means something: a unique match within tolerance,
where saying so on every run would train the operator to skim past the runs that
matter.

**No match at all is only a WARNING, and the asymmetry is the argument.** A
panel that omits a reference layer reaches the end of the pipeline untouched and
exits 0 — see :meth:`apply`, which cannot assume a predecessor ran. So an ERROR
here would mean that *drawing* your outline is punished while *not* drawing it
is not, which is backwards at any severity. The principle underneath: "two
Hammond footprints fit yours" and "you declared a part your artwork
contradicts" are statements about the operator's panel, but "we have never heard
of your enclosure" is a statement about **our catalogue** — this tool holds 22
Hammond footprints and the world holds rather more. The same rule the drill
table follows: we cannot know what another builder is working in. The finding is
raised, the run continues, the outline is left exactly as it was measured, and
the operator decides.

**A 2-D outline identifies a footprint, not a part.** 112 × 61 is 1590B, 1590B2
*and* 1590BS — they differ only in height, which artwork does not carry. The
match therefore names candidates, and ``selected_part`` is filled in only from
what the operator declared.

**The catalogue holds BACKPLATE dimensions, and so must the artwork.** A 1590 is
die-cast with drafted walls -- the datasheet says "low side wall draft angle (2°
or less)" -- so the face that gets drilled is smaller than the backplate by
``2 * depth * tan(angle)`` per axis: 1.9 mm on a 1590B, 6.3 mm on a 1590V. No
tolerance can take a face-drawn outline. Matching one needs at least 2.4 mm on
the shallowest common part, while two footprints tie at 2.0 mm because the
closest pair in this catalogue is 4 mm apart -- required >= 2.4, permitted
< 2.0. So the convention is the fix, not a number, and ``_unknown``'s message
names it: the operator this catches is the one who measured *more* carefully.
``docs/adr/0003-domain-quantisers.md`` records the arithmetic.

The default tolerance of 1.5 mm is bounded by the catalogue itself, not chosen
for the fixture: two footprints can both match one outline once they are within
twice the tolerance of each other, and the closest approach in the 22 Hammond
1590 footprints is 4 mm (1590B3 116 × 77 against 1590T 120 × 80). Anything below
2 mm is therefore unambiguous everywhere, and 1.5 mm leaves room for the
fixture's 1.0 mm error with margin to spare. ``tests/test_pipeline.py`` pins
that derivation against the real catalogue so a datasheet revision that brings
two footprints closer together fails loudly instead of matching two.
"""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from ..enclosures import footprints
from ..model import (
    Diagnostic,
    DrillData,
    EnclosureMatch,
    ParameterValue,
    ReferenceOutline,
    StageRun,
)
from ..tolerance import within

__all__ = ["CATALOGUE", "normalize_part_name", "IdentifyHammondFootprint"]

#: The catalogue this stage searches, named once so the ``EnclosureMatch``
#: family and the ``StageRun`` provenance cannot drift into two spellings of
#: the same fact.
CATALOGUE: str = "Hammond 1590"


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

    ``tolerance_mm`` is the per-axis slack allowed between the measured outline
    and a catalogue footprint; ``expected_part`` is what the operator declared
    the panel to be, checked against the footprint that was actually found.

    A missing reference outline is not a finding here — the source may have had
    no reference layer, and a stage may not assume a predecessor ran — so the
    data comes back untouched.
    """

    name: ClassVar[str] = "identify-enclosure"

    def __init__(self, tolerance_mm: float = 1.5, expected_part: str | None = None) -> None:
        self.tolerance_mm = float(tolerance_mm)
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
            ("tolerance_mm", self.tolerance_mm),
            ("catalogue", CATALOGUE),
        ]
        if self.expected_part is not None:
            parameters.append(("expected_part", self.expected_part))
        return StageRun(self.name, tuple(parameters))

    def apply(self, data: DrillData) -> DrillData:
        reference = data.reference
        if reference is None:
            return data

        matches = self._matches(reference)
        if not matches:
            return data.with_diagnostics(self._unknown(reference))
        if len(matches) > 1:
            return data.with_diagnostics(self._ambiguous(reference, matches))

        (length_mm, width_mm), rotated = matches[0]
        candidates = footprints()[(length_mm, width_mm)]
        snapped = data.with_enclosure(
            EnclosureMatch(
                family=CATALOGUE,
                length_mm=length_mm,
                width_mm=width_mm,
                candidates=candidates,
                # Always explicit. The field defaults to False, so a matcher
                # that forgot to work rotation out would report every portrait
                # panel as landscape and nothing would say otherwise.
                rotated=rotated,
                selected_part=self.expected_part,
            )
        )
        # ``resized``, never ``ReferenceOutline(...)``: see the module docstring.
        # The artwork's own orientation is kept — a rotated panel stays portrait
        # — while the match records the catalogue's canonical length and width.
        if rotated:
            outline = reference.resized(float(width_mm), float(length_mm))
        else:
            outline = reference.resized(float(length_mm), float(width_mm))
        snapped = self._with_outline(snapped, outline)

        if self.expected_part is not None and self.expected_part not in candidates:
            return snapped.with_diagnostics(self._wrong(length_mm, width_mm, candidates))
        return snapped

    # -- matching --------------------------------------------------------
    def _matches(self, reference: ReferenceOutline) -> list[tuple[tuple[int, int], bool]]:
        """Every footprint the outline could be, with whether it is turned 90°.

        Both readings are tried, and the unrotated one wins when both fit. That
        only happens for a square footprint, where the two readings describe the
        same panel; calling it a rotation would put "rotated" on a drawing for a
        panel nobody turned. Sorted so the tie report is stable — the order is
        for the *message*, never for picking a winner.
        """
        found: list[tuple[tuple[int, int], bool]] = []
        for footprint in sorted(footprints()):
            length_mm, width_mm = footprint
            if self._fits(reference, length_mm, width_mm):
                found.append((footprint, False))
            elif self._fits(reference, width_mm, length_mm):
                found.append((footprint, True))
        return found

    def _fits(self, reference: ReferenceOutline, width_mm: int, height_mm: int) -> bool:
        """Both axes, and both are load-bearing: an outline that is right across
        and 4 mm out top to bottom is not that enclosure."""
        return within(reference.width, float(width_mm), self.tolerance_mm) and within(
            reference.height, float(height_mm), self.tolerance_mm
        )

    # -- diagnostics -----------------------------------------------------
    def _unknown(self, reference: ReferenceOutline) -> Diagnostic:
        """WARNING, not ERROR — the one finding here about *us* and not the panel.

        See the module docstring: a panel with no reference layer at all exits 0,
        so refusing one that has an outline we do not recognise would punish the
        operator for drawing it. The outline is left as measured, and the run
        goes on.

        The message names the backplate convention because that is the single
        most likely reason a correct panel lands here, and the operator who
        lands there is the *careful* one — they measured the face they are about
        to drill. The catalogue lists backplate dimensions, and a 1590 face is
        smaller than its backplate by the wall draft (SPEC §6.2 does the
        arithmetic: no tolerance can accept both a face-drawn outline and the
        catalogue's own closest pair of footprints). A failure that teaches the
        fix costs a re-run; one that does not costs a case.
        """
        return Diagnostic.warning(
            "unknown-enclosure",
            f"reference outline {reference.width:.3f} × {reference.height:.3f} mm "
            f"matches no {CATALOGUE} footprint within {self.tolerance_mm:g} mm; "
            f"the outline has been left as drawn. The catalogue lists backplate "
            f"dimensions, and a drilled face is smaller than its backplate because "
            f"the walls are drafted — if this outline is a face measurement, redraw "
            f"the reference layer to the backplate size",
            data=(
                ("width_mm", reference.width),
                ("height_mm", reference.height),
                ("tolerance_mm", self.tolerance_mm),
                ("catalogue", CATALOGUE),
            ),
        )

    def _ambiguous(
        self, reference: ReferenceOutline, matches: list[tuple[tuple[int, int], bool]]
    ) -> Diagnostic:
        """Name every footprint that fitted. Naming one would be the guess."""
        tied = [footprint for footprint, _ in matches]
        outlines = ", ".join(f"{length} × {width}" for length, width in tied)
        parts = ", ".join(part for footprint in tied for part in footprints()[footprint])
        return Diagnostic.error(
            "ambiguous-enclosure",
            f"reference outline {reference.width:.3f} × {reference.height:.3f} mm is "
            f"within {self.tolerance_mm:g} mm of more than one {CATALOGUE} footprint "
            f"({outlines} mm); tighten the tolerance or declare the case",
            data=(
                ("footprints", outlines),
                ("candidates", parts),
                ("tolerance_mm", self.tolerance_mm),
            ),
        )

    def _wrong(self, length_mm: int, width_mm: int, candidates: tuple[str, ...]) -> Diagnostic:
        """Both parts, always: the requested one and the one that was drawn.

        Either alone leaves the operator re-deriving the other off the artwork,
        which is the measurement this stage exists to have already made.
        """
        identified = ", ".join(candidates)
        return Diagnostic.error(
            "wrong-enclosure",
            f"panel declared as {self.expected_part}, but the outline is "
            f"{length_mm} × {width_mm} mm — {identified}",
            data=(
                ("requested_part", self.expected_part or ""),
                ("identified_parts", identified),
                ("length_mm", length_mm),
                ("width_mm", width_mm),
            ),
        )

    @staticmethod
    def _with_outline(data: DrillData, reference: ReferenceOutline) -> DrillData:
        """One place the reference is replaced, so ``resized`` cannot be bypassed
        by a second write site later."""
        return replace(data, reference=reference)
