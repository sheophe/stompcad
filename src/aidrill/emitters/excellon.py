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
:meth:`DrillData.with_origin`, never hand-rolled — and the nanometre-to-
millimetre rendering of :func:`units.format_nm`, at the moment of formatting.
Every length reaching here is a whole number of nanometres, so the translation is
exact and the rendering is the only place a value is ever shortened: half the
outline added on the way in and the same half subtracted by a reader lands back
on the number the pipeline chose, which is what lets this file and the sheet
beside it describe one panel in two frames without rounding between them.

The file is always metric. The grid is quoted in millimetres, the catalogue is
metric, and a professional machine takes a metric tool table, so there is no
frame in which the ``INCH,TZ`` spelling was anyone's answer. The one operator who
does think in inches asks for it with ``--drill-standard fractional``, which is a
*drill table* and not a unit: the console and the sheet then print ⌀13/64" from
the standard's own label while this file writes the size the machine drills,
``T1C5.159``.

Three invariants are therefore checked rather than assumed, because ``emit``
serialises whatever ``DrillData`` a library consumer hands it — the CLI's own
gate on ``worst_severity`` protects only the CLI. The data must carry no ERROR,
the tool table must stay injective *as written*, and ``LOWER_LEFT`` must yield no
negative coordinate. Declining to write a file is permitted; repairing one is
not — see ``docs/adr/0001-pipeline-and-emitter-adapters.md``.

Excellon is the format where each of those matters most, because it renders no
diagnostics at all. Every other artifact this project writes carries its findings
with it: the drawing has a NOTES block, the JSON document has ``diagnostics``.
A drill file has nothing, so an incomplete or nonsensical one does not read as
damaged — it reads as a drill file for a different panel, and it reads that way
to a machinist about to put it into a machine.

The header therefore also states which frame the coordinates are in. It declared
``absolute``, ``metric`` and ``decimal`` while saying nothing about where zero
was, so the same hole was ``X16.500Y48.000`` here and ``-40.00, 18.00`` on the
sheet beside it — every number different, by exactly half the outline, with
neither document explaining the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar

from ..errors import EmitterError
from ..model import DrillData, Hole, Origin, Severity
from ..units import format_nm
from .base import register_emitter

__all__ = ["ExcellonOptions", "ExcellonEmitter"]

#: Decimals at which two nominals are named apart in the refusal below. A
#: nanometre is 0.000001 mm, so six places is the finest distinction the model
#: can hold: two diameters that print alike at the file's own precision are
#: always distinguishable here, and the operator never has to re-derive by how
#: much they differ.
_NANOMETRE_DECIMALS = 6


@dataclass(frozen=True, slots=True)
class ExcellonOptions:
    """Output options for :class:`ExcellonEmitter`.

    ``origin``
        ``LOWER_LEFT`` (the default) is what drilling equipment expects, because
        it keeps every coordinate positive. It needs a reference outline to know
        where the lower-left corner is; without one the emitter raises rather
        than guessing.
    ``decimals``
        Digits after the point for both coordinates and tool diameters.
    ``title``
        Text for the ``;DRILL file for …`` comment. Falls back to the source path.
    """

    origin: Origin = Origin.LOWER_LEFT
    decimals: int = 3
    title: str = ""


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
        self._reject_errors(data)
        framed, origin_comment = self._reframe(data)
        tools = framed.tools()
        tokens = self._tool_tokens(tools)
        self._reject_negative_coordinates(framed)

        lines: list[str] = [
            "M48",
            f";DRILL file for {self._title(framed)}",
            ";FORMAT={-:-/ absolute / metric / decimal}",
            "FMAT,2",
            "METRIC,TZ",
            origin_comment,
        ]
        # One definition per nominal diameter, numbered by the model. Not by us.
        lines += [f"T{number}C{tokens[diameter_nm]}" for diameter_nm, number in tools.items()]
        lines += ["%", "G90", "G05"]

        for diameter_nm, number in tools.items():
            holes = [h for h in framed.holes if h.diameter_nm == diameter_nm]
            if not holes:  # pragma: no cover - tools() is derived from the holes
                continue
            lines.append(f"T{number}")
            lines += self._coordinates(holes)

        lines += ["T0", "M30"]
        return "\n".join(lines) + "\n"

    # -- internals -------------------------------------------------------
    def _reject_errors(self, data: DrillData) -> None:
        """Refuse data a stage has already declared broken.

        ``SnapDiametersToDrillTable`` implements an unmatched diameter by
        recording an ERROR *and dropping the hole*, so error-bearing data is
        routinely data with a hole missing from it. The CLI knows this and
        writes no artifact at all when anything reached ERROR; a library
        consumer driving the pipeline itself has no such gate, and the file it
        would get here is the one failure this project is organised around —
        not a broken drill file, but a well-formed drill file for a panel that
        is one hole short. Nothing in the format can say otherwise.

        The codes are named because the caller would otherwise have to walk the
        diagnostics to find out which finding stopped the file, and because
        ``code`` is the stable key: a consumer that wants to act on this — retry
        with a wider drill table, say — can match on what it reads here. Each is
        named once, in the order the stages found them; a panel with nine holes
        off one table would otherwise repeat one code nine times and say nothing.
        """
        errors = data.of_severity(Severity.ERROR)
        if not errors:
            return
        codes = ", ".join(dict.fromkeys(d.code for d in errors))
        raise EmitterError(
            f"excellon: the drill data carries {len(errors)} error diagnostic"
            f"{'' if len(errors) == 1 else 's'} ({codes}), and a stage that reports "
            f"an error may already have dropped a hole — an Excellon file renders no "
            f"diagnostics, so the result would look like a complete drill file for a "
            f"panel it does not describe; resolve the errors, or emit the json format, "
            f"which can carry them"
        )

    def _reframe(self, data: DrillData) -> tuple[DrillData, str]:
        """Translate into the requested frame, and say in one breath what it is.

        The header's frame comment is built here rather than beside the other
        header lines because this is the one place that knows both what was
        asked for and what the shift came to. A file stating a frame it was not
        written in would be worse than the silence it replaces, and two places
        deciding the frame is exactly how that happens.

        Frame translation itself is delegated to the shared model transform;
        ``with_origin`` is also the authority on which origins exist, so an
        origin neither branch below describes never reaches the header — it
        raises three lines further down instead.

        The stated half floors, because ``with_origin``'s does: an outline of an
        odd number of nanometres has no exact half, and a comment quoting the
        true half would name a shift the coordinates under it were not moved by.
        A test pins the two together at a precision fine enough to tell them
        apart, since at the three decimals this file usually writes half a
        nanometre disappears.
        """
        if self.options.origin is Origin.LOWER_LEFT:
            if data.reference is None:
                raise EmitterError(
                    "excellon: a lower-left origin requires a reference outline, and there "
                    "is none — pass origin=Origin.CENTRE or supply a reference layer"
                )
            frame = (
                f"lower-left corner of the reference outline, "
                f"X{self._value(data.reference.width_nm // 2)} "
                f"Y{self._value(data.reference.height_nm // 2)} from its centre"
            )
        else:
            frame = "centre of the reference outline, the canonical frame"
        try:
            return data.with_origin(self.options.origin), f";ORIGIN={frame}"
        except ValueError as exc:  # unknown origin, or a reference lost in flight
            raise EmitterError(f"excellon: {exc}") from exc

    def _tool_tokens(self, tools: Mapping[int, int]) -> dict[int, str]:
        """Render each nominal once, and refuse a clash.

        The precision the caller asked for is where the resolution actually is,
        not the unit: 6.9998 and 7.0000 mm are two unmistakable nominals to the
        model — 200 nanometres apart, and no stage merged them — and one
        ``C7.000`` at three decimals. Merging the two is the pipeline's call,
        never this file's; all an emitter may do about a distinction it cannot
        print is decline to.

        Both nominals are named at nanometre precision, because at the file's
        own precision they are by definition the same string, and a refusal that
        quoted them there would say a size collides with itself.
        """
        seen: dict[str, int] = {}
        tokens: dict[int, str] = {}
        for diameter_nm in tools:
            token = self._value(diameter_nm)
            if token in seen:
                raise EmitterError(
                    f"excellon: nominal diameters "
                    f"{format_nm(seen[token], _NANOMETRE_DECIMALS)} and "
                    f"{format_nm(diameter_nm, _NANOMETRE_DECIMALS)} mm both print as "
                    f"C{token} at {self.options.decimals} decimals, so the file would "
                    f"load the same tool twice — raise the precision, or normalise "
                    f"them upstream"
                )
            seen[token] = diameter_nm
            tokens[diameter_nm] = token
        return tokens

    def _reject_negative_coordinates(self, data: DrillData) -> None:
        """Check the promise ``LOWER_LEFT`` makes, against what will be written.

        Read from the rendered token rather than the position, so a hole a
        fraction of a print unit outside the outline — which prints ``0.000``
        and drills exactly where it should — is not reported as off the panel.
        Holes are checked in pipeline order, so the index named is the first
        offender.
        """
        if self.options.origin is not Origin.LOWER_LEFT:
            return
        for hole in data.holes:
            x, y = self._value(hole.x_nm), self._value(hole.y_nm)
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
        return [f"X{self._value(h.x_nm)}Y{self._value(h.y_nm)}" for h in holes]

    def _value(self, nanometres: int) -> str:
        """Format one length: nanometres in, millimetres out, at the asked width.

        No rounding of the underlying data — this is presentation only, and the
        integer it reads is the one the pipeline stored. Negative zero is
        normalised away by the shared converter, the same one the drawing's
        schedule prints through, so the two artifacts cannot print one hole two
        ways.
        """
        return format_nm(nanometres, self.options.decimals)
