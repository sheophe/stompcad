"""Quantise measured outlines onto Hammond 1590 backplate footprints.

Unrounded measurements use an inclusive 1.5 mm per-axis tolerance. Unique or
declared matches use catalogue dimensions while retaining ``raw``; undeclared
misses warn and stay measured, while ties or failed declarations are errors.
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
from ..units import Nanometre, format_nm, nm_from_mm, scaled_nm

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

#: Inclusive 1.5 mm per-axis matching slack. It remains below the 1.9 mm gap
#: at which a face-drawn 1590B becomes ambiguous.
DEFAULT_TOLERANCE_NM: Nanometre = Nanometre(1_500_000)

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
_Match = tuple[tuple[Nanometre, Nanometre], bool]


def normalize_part_name(name: str) -> str:
    """Strip and uppercase a part name without interpreting order-code suffixes."""
    return name.strip().upper()


class IdentifyHammondFootprint:
    """Match an outline against catalogue footprints with per-axis slack.

    A declaration must be confirmed on every path. Without one, a missing
    outline is silent and an unknown footprint warns; unresolved ties are errors.
    """

    name: ClassVar[str] = "identify-enclosure"

    def __init__(
        self,
        expected_part: str | None = None,
        tolerance_nm: Nanometre = DEFAULT_TOLERANCE_NM,
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
        """Record effective tolerance, catalogue and any normalised declaration."""
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
        """Return the nominal outline, identified footprint and findings.

        ``centre`` locates the measured outline but does not affect matching.
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
        """Return sorted matching footprints and rotation; prefer square unrotated."""
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
        self, width: Decimal, height: Decimal, width_nm: Nanometre, height_nm: Nanometre
    ) -> bool:
        """Both axes, and both are load-bearing: an outline that is right across
        and 4 mm out top to bottom is not that enclosure."""
        return self._near(width, width_nm) and self._near(height, height_nm)

    def _near(self, measured: Decimal, catalogue_nm: Nanometre) -> bool:
        """Compare an unrounded measurement to one dimension, boundary inclusive."""
        return abs(measured - catalogue_nm) <= self.tolerance_nm

    # -- diagnostics -----------------------------------------------------
    def _unknown(self, measured: ReferenceOutline) -> Diagnostic:
        """Warn that an undeclared outline matched nothing and retain its size."""
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
        """Report every tied footprint and part as ``ambiguous-enclosure`` ERROR."""
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
        """Report a declared case without an outline as an unverifiable ERROR."""
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
        """Report a declaration not singled out by zero or multiple matches.

        This is ``unmatched-enclosure`` ERROR; fitted lists remain present, even empty.
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

    def _expected_footprint(self) -> tuple[Nanometre, Nanometre] | None:
        """Return the declared part's catalogue footprint, or ``None``."""
        for footprint, parts in footprints().items():
            if self.expected_part in parts:
                return footprint
        return None

    def _expected_footprint_data(self) -> tuple[tuple[str, float | int | str], ...]:
        """Return declared footprint payload, omitting dimensions when unknown."""
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

    def _wrong(
        self, length_nm: Nanometre, width_nm: Nanometre, candidates: tuple[str, ...]
    ) -> Diagnostic:
        """Report requested and identified parts as ``wrong-enclosure`` ERROR."""
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
        """Format the whole-nanometre outline carried by the model."""
        return f"{format_nm(measured.width_nm)} × {format_nm(measured.height_nm)} mm"


def _footprint_list(footprints_nm: list[tuple[Nanometre, Nanometre]]) -> str:
    """Format catalogue dimensions without losing their 0.05 mm distinctions."""
    return ", ".join(
        f"{format_nm(length)} × {format_nm(width)}" for length, width in footprints_nm
    )


def _candidate_list(footprints_nm: list[tuple[Nanometre, Nanometre]]) -> str:
    """Every base designator sharing any of these footprints, in the same order."""
    return ", ".join(part for footprint in footprints_nm for part in footprints()[footprint])
