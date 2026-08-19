"""Serialise pipeline results as metric Excellon FMAT,2.

Tool numbers and hole order come from ``DrillData``. Only model frame translation
and final numeric formatting occur here. Because Excellon cannot carry findings,
ERROR data, colliding rendered tools and negative lower-left coordinates are rejected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar

from stompmodel.units import Nanometre, format_nm

from ..errors import EmitterError
from ..model import DrillData, Hole, Origin, Severity
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
    """Excellon origin, decimal precision and optional title.

    ``LOWER_LEFT`` requires a reference outline; title falls back to source path.
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
        self._reject_unrouted(data)
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
        """Refuse ERROR-bearing data, naming distinct diagnostic codes in order."""
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

    def _reject_unrouted(self, data: DrillData) -> None:
        """Refuse data no ``RouteHoles`` ever numbered, on every origin.

        ``numbered()`` already raises for this; without a direct call the
        check only happened to run under ``LOWER_LEFT``, whose negative-
        coordinate scan is the only other place it is invoked.
        """
        data.numbered()

    def _reframe(self, data: DrillData) -> tuple[DrillData, str]:
        """Use ``with_origin`` and return a header describing the effective frame.

        Lower-left translation requires an outline and floors odd half-nanometres.
        """
        if self.options.origin is Origin.LOWER_LEFT:
            if data.reference is None:
                raise EmitterError(
                    "excellon: a lower-left origin requires a reference outline, and there "
                    "is none — pass origin=Origin.CENTRE or supply a reference layer"
                )
            frame = (
                f"lower-left corner of the reference outline, "
                f"X{self._value(Nanometre(data.reference.width_nm // 2))} "
                f"Y{self._value(Nanometre(data.reference.height_nm // 2))} from its centre"
            )
        else:
            frame = "centre of the reference outline, the canonical frame"
        try:
            return data.with_origin(self.options.origin), f";ORIGIN={frame}"
        except ValueError as exc:  # unknown origin, or a reference lost in flight
            raise EmitterError(f"excellon: {exc}") from exc

    def _tool_tokens(self, tools: Mapping[Nanometre, int]) -> dict[Nanometre, str]:
        """Render each nominal once, refusing collisions at requested precision."""
        seen: dict[str, Nanometre] = {}
        tokens: dict[Nanometre, str] = {}
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
        """Reject the first rendered negative coordinate under ``LOWER_LEFT``."""
        if self.options.origin is not Origin.LOWER_LEFT:
            return
        for number, hole in data.numbered():
            x, y = self._value(hole.x_nm), self._value(hole.y_nm)
            if x.startswith("-") or y.startswith("-"):
                raise EmitterError(
                    f"excellon: hole {number} reframes to X{x}Y{y}, a negative "
                    f"coordinate — a lower-left origin promises every coordinate is "
                    f"positive, so this hole lies outside the reference outline; check "
                    f"the reference layer, or emit with origin=Origin.CENTRE"
                )

    def _title(self, data: DrillData) -> str:
        return self.options.title or data.source.path or "untitled"

    def _coordinates(self, holes: Iterable[Hole]) -> list[str]:
        """Holes in the order they arrive. Sequence is ``RouteHoles``' decision."""
        return [f"X{self._value(h.x_nm)}Y{self._value(h.y_nm)}" for h in holes]

    def _value(self, nanometres: Nanometre) -> str:
        """Format nanometres as millimetres at the requested decimal precision."""
        return format_nm(nanometres, self.options.decimals)
