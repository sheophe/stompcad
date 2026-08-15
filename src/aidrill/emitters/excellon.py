"""Excellon drill-file emitter (SPEC §7).

This module serialises. That is all it does.

It does **not** round positions, cluster diameters, drop duplicates or assign
tool numbers of its own. Every one of those is a pipeline responsibility, and the
one time this file took them on it produced drill files like::

    T1C5.000
    T2C7.000
    T3C7.000

— the same 7 mm bit loaded twice, two drilling passes, because a measured 6.9998
and a measured 7.0000 were clustered *here* rather than upstream. Tool numbers
come from :meth:`DrillData.tools`, which is also what the drawing's hole schedule
uses, so the two cannot disagree. See ``tests/test_excellon.py`` for the
regression that pins this.

Nor does it order anything. Holes are written in the order they arrive, grouped
under their tool; the sequence is whatever ``pipeline.SortHoles`` left behind,
exactly as in the JSON and the drawing. This file once carried its own copy of
``SortHoles``' reading-order key and applied it unconditionally, which meant a
custom sort key reached the sheet but not the drill file, and the drawing's
balloon numbers no longer matched the order the machine drilled in.

The only transforms permitted are frame translation — delegated to
:meth:`DrillData.with_origin`, never hand-rolled — and unit conversion, via
:attr:`Units.per_mm`, at the moment of formatting.

Serialising faithfully is not the same as serialising truthfully, and the same
three lines came back a second way. ``tools()`` is keyed on the *float* nominal;
this file prints the table through ``format_mm(d, decimals)``. Two nominals
closer together than the print resolution are two tools to the model and one
token on the page, so the emitter dutifully wrote both::

    aidrill tests/fixtures/tar.ai --diameter-tolerance 0.0001 --emit excellon=a.drl
    T1C5.000
    T2C7.000
    T3C7.000

— byte for byte the defect above, arrived at without any clustering at all. The
fix is not to cluster (that would re-import the original sin) and not to widen
the precision behind the operator's back. It is to notice that the *output
format* cannot represent the distinction the data carries, and refuse.

That check lives here and nowhere upstream, deliberately. Whether two nominals
collide depends on ``units`` and ``decimals``, which no stage knows: a pipeline
warning would be false when only JSON and the drawing are being written — both
of which represent 6.9998 and 7.0000 perfectly well — and insufficient when
Excellon is, because the operator can fix it by raising ``decimals``. So the
emitter checks injectivity of its own rendered tokens, after unit conversion,
and raises. ``--diameters none`` therefore cannot always emit Excellon; that is
correct. It is a debug mode preserving measured distinctions a three-decimal
drill format sometimes cannot express.

The same argument covers coordinates. SPEC §7 says a lower-left origin keeps
every coordinate positive, but that is a promise about the reframed *output*: a
hole outside the reference outline reframes to a negative X and the file still
parses, so the machine drives off the fixture with nothing having complained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable, Mapping

from ..errors import EmitterError
from ..formatting import format_mm
from ..model import DrillData, Hole, Origin, Units
from .base import register_emitter

__all__ = ["ExcellonOptions", "ExcellonEmitter"]


@dataclass(frozen=True, slots=True)
class ExcellonOptions:
    """Output options for :class:`ExcellonEmitter`.

    ``origin``
        ``LOWER_LEFT`` (the default) is what drilling equipment expects, because
        it keeps every coordinate positive. It needs a reference outline to know
        where the lower-left corner is; without one the emitter raises rather
        than guessing.
    ``units``
        Millimetres or inches. Inch conversion happens here, at the last moment.
    ``decimals``
        Digits after the point for both coordinates and tool diameters.
    ``title``
        Text for the ``;DRILL file for …`` comment. Falls back to the source path.
    """

    origin: Origin = Origin.LOWER_LEFT
    units: Units = Units.MILLIMETRES
    decimals: int = 3
    title: str = ""


_UNIT_HEADER = {Units.MILLIMETRES: "METRIC,TZ", Units.INCHES: "INCH,TZ"}
_UNIT_WORD = {Units.MILLIMETRES: "metric", Units.INCHES: "inch"}


@register_emitter
class ExcellonEmitter:
    """Emit ``DrillData`` as an Excellon (FMAT,2) drill file."""

    name: ClassVar[str] = "excellon"
    media_type: ClassVar[str] = "text/x-excellon"
    extension: ClassVar[str] = ".drl"

    def __init__(self, options: ExcellonOptions | None = None) -> None:
        self.options = options if options is not None else ExcellonOptions()

    # -- public ----------------------------------------------------------
    def emit(self, data: DrillData) -> str:
        framed = self._reframe(data)
        tools = framed.tools()
        tokens = self._tool_tokens(tools)
        self._reject_negative_coordinates(framed)

        lines: list[str] = [
            "M48",
            f";DRILL file for {self._title(framed)}",
            f";FORMAT={{-:-/ absolute / {_UNIT_WORD[self.options.units]} / decimal}}",
            "FMAT,2",
            _UNIT_HEADER[self.options.units],
        ]
        # One definition per nominal diameter, numbered by the model. Not by us.
        lines += [f"T{number}C{tokens[diameter]}" for diameter, number in tools.items()]
        lines += ["%", "G90", "G05"]

        for diameter, number in tools.items():
            holes = [h for h in framed.holes if h.diameter == diameter]
            if not holes:  # pragma: no cover - tools() is derived from the holes
                continue
            lines.append(f"T{number}")
            lines += self._coordinates(holes)

        lines += ["T0", "M30"]
        return "\n".join(lines) + "\n"

    # -- internals -------------------------------------------------------
    def _reframe(self, data: DrillData) -> DrillData:
        """Translate into the requested frame using the shared model transform."""
        if self.options.origin is Origin.LOWER_LEFT and data.reference is None:
            raise EmitterError(
                "excellon: a lower-left origin requires a reference outline, and there "
                "is none — pass origin=Origin.CENTRE or supply a reference layer"
            )
        try:
            return data.with_origin(self.options.origin)
        except ValueError as exc:  # unknown origin, or a reference lost in flight
            raise EmitterError(f"excellon: {exc}") from exc

    def _tool_tokens(self, tools: Mapping[float, int]) -> dict[float, str]:
        """Render each nominal, and refuse if the rendering is not injective.

        Built *after* unit conversion, because that is where the resolution
        actually is: 3.02 and 3.03 mm are two unmistakable tools in millimetres
        and one ``0.119`` at three decimals in inches. Comparing the millimetre
        values — or the floats themselves, which is what ``tools()`` does — would
        pass this file and still write the same bit twice.

        Nothing is merged, rounded or renumbered here. The emitter has no
        standing to decide two nominals are really one; that is the pipeline's
        call, and taking it back is the bug ADR-0001 exists to prevent. The only
        thing this can do about a distinction it cannot print is decline to print
        it.
        """
        seen: dict[str, float] = {}
        tokens: dict[float, str] = {}
        for diameter in tools:
            token = self._value(diameter)
            collided = seen.get(token)
            if collided is not None:
                raise EmitterError(
                    f"excellon: nominal diameters {collided!r} and {diameter!r} mm both "
                    f"print as C{token} at {self.options.decimals} decimal places in "
                    f"{_UNIT_WORD[self.options.units]}, so the drill file would load the "
                    f"same tool twice — SPEC §7 allows one tool per nominal diameter. "
                    f"Raise the precision so the two sizes are distinguishable, or "
                    f"normalise them into a single nominal in the pipeline."
                )
            seen[token] = diameter
            tokens[diameter] = token
        return tokens

    def _reject_negative_coordinates(self, data: DrillData) -> None:
        """Check the promise LOWER_LEFT makes, against the coordinates as written.

        Only for LOWER_LEFT: CENTRE is the canonical frame and half of every
        panel is at a negative coordinate in it. Checked on the rendered token
        rather than the float so that a hole a ten-thousandth of a millimetre
        outside the outline — which prints ``0.000`` and drills exactly where it
        should — is not reported as off the panel.

        Holes are checked in pipeline order, so the index named is the first
        offender the operator will look for, not the first one that happened to
        fall under the lowest-numbered tool.
        """
        if self.options.origin is not Origin.LOWER_LEFT:
            return
        for hole in data.holes:
            x, y = self._value(hole.x), self._value(hole.y)
            if x.startswith("-") or y.startswith("-"):
                raise EmitterError(
                    f"excellon: hole {hole.index} reframes to X{x}Y{y}, a negative "
                    f"coordinate — a lower-left origin promises every coordinate is "
                    f"positive, so this hole lies outside the reference outline. Check "
                    f"the reference layer covers the whole panel, or emit with "
                    f"origin=Origin.CENTRE."
                )

    def _title(self, data: DrillData) -> str:
        return self.options.title or data.source.path or "untitled"

    def _coordinates(self, holes: Iterable[Hole]) -> list[str]:
        """Holes in the order they arrive. Sequence is ``SortHoles``' decision."""
        return [f"X{self._value(h.x)}Y{self._value(h.y)}" for h in holes]

    def _value(self, millimetres: float) -> str:
        """Format one length: convert units, then fix the width. No rounding of
        the underlying data — this is presentation only. Negative zero is
        normalised away by the shared formatter, the same one the drawing's
        schedule uses, so the two artifacts cannot print one hole two ways."""
        return format_mm(
            millimetres * self.options.units.per_mm, self.options.decimals
        )
