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

Two invariants are therefore checked rather than assumed, because ``emit``
serialises whatever ``DrillData`` a library consumer hands it: the tool table
must stay injective *as written*, and ``LOWER_LEFT`` must yield no negative
coordinate. Declining to write a file is permitted; repairing one is not — see
``docs/adr/0001-pipeline-and-emitter-adapters.md``.
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
        """Render each nominal once, *after* unit conversion, and refuse a clash.

        Conversion is where the resolution actually is: 3.02 and 3.03 mm are two
        unmistakable tools in millimetres and one ``0.119`` at three decimals in
        inches. Merging the two is the pipeline's call, never this file's; all
        an emitter may do about a distinction it cannot print is decline to.
        """
        seen: dict[str, float] = {}
        tokens: dict[float, str] = {}
        for diameter in tools:
            token = self._value(diameter)
            if token in seen:
                raise EmitterError(
                    f"excellon: nominal diameters {seen[token]!r} and {diameter!r} mm "
                    f"both print as C{token} at {self.options.decimals} decimals in "
                    f"{_UNIT_WORD[self.options.units]}, so the file would load the "
                    f"same tool twice — raise the precision, or normalise them upstream"
                )
            seen[token] = diameter
            tokens[diameter] = token
        return tokens

    def _reject_negative_coordinates(self, data: DrillData) -> None:
        """Check the promise ``LOWER_LEFT`` makes, against what will be written.

        Read from the rendered token rather than the float, so a hole a fraction
        of a print unit outside the outline — which prints ``0.000`` and drills
        exactly where it should — is not reported as off the panel. Holes are
        checked in pipeline order, so the index named is the first offender.
        """
        if self.options.origin is not Origin.LOWER_LEFT:
            return
        for hole in data.holes:
            x, y = self._value(hole.x), self._value(hole.y)
            if x.startswith("-") or y.startswith("-"):
                raise EmitterError(
                    f"excellon: hole {hole.index} reframes to X{x}Y{y}, a negative "
                    f"coordinate — a lower-left origin promises every coordinate is "
                    f"positive, so this hole lies outside the reference outline; check "
                    f"the reference layer, or emit with origin=Origin.CENTRE"
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
