"""Read back a metric Excellon FMAT,2 file, from the format's own grammar.

Nine statement kinds and explicit decimals -- everything that makes general
Excellon parsing hard is unreachable from ``_coordinates``. It raises on any
statement it does not model, so an emitter that grew one fails loudly rather
than passing by omission, and it asserts the header rather than assuming it.
"""

from __future__ import annotations

import re

from .facts import RecoveredCircle, RecoveredPanel, nm_from_decimal

__all__ = ["read_excellon"]

_TOOL_DEF = re.compile(r"^T(\d+)C(-?\d*\.?\d+)$")
_TOOL_SEL = re.compile(r"^T(\d+)$")
_HIT = re.compile(r"^X(-?\d*\.?\d+)Y(-?\d*\.?\d+)$")

#: Body statements that carry no geometry. Absolute mode, drill mode, end.
_INERT = frozenset({"G90", "G05", "M30"})

#: Header statements that are not a comment and not a tool definition.
_HEADER = frozenset({"FMAT,2", "METRIC,TZ"})


def read_excellon(text: str) -> RecoveredPanel:
    """Tools by number, hits in file order, and the header's comments."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "M48":
        raise ValueError("not an Excellon file: no M48 header")
    if "%" not in lines:
        raise ValueError("no header terminator: the file states no body")
    end = lines.index("%")
    header, body = lines[1:end], lines[end + 1 :]

    if "METRIC,TZ" not in header:
        raise ValueError(f"unsupported units or zero suppression: {header}")
    tools = {int(m[1]): nm_from_decimal(m[2]) for line in header if (m := _TOOL_DEF.match(line))}
    for line in header:
        if not (line.startswith(";") or line in _HEADER or _TOOL_DEF.match(line)):
            raise ValueError(f"unhandled Excellon header statement: {line}")

    circles: list[RecoveredCircle] = []
    selected: int | None = None
    for line in body:
        if match := _TOOL_SEL.match(line):
            selected = int(match[1]) or None  # T0 unloads the tool
        elif match := _HIT.match(line):
            if selected is None:
                raise ValueError(f"coordinate with no tool selected: {line}")
            circles.append(
                RecoveredCircle(
                    x_nm=nm_from_decimal(match[1]),
                    y_nm=nm_from_decimal(match[2]),
                    diameter_nm=tools[selected],
                    number=len(circles) + 1,
                    tool=selected,
                )
            )
        elif line not in _INERT:
            raise ValueError(f"unhandled Excellon statement: {line}")

    comments = tuple(line[1:] for line in header if line.startswith(";"))
    return RecoveredPanel(circles=tuple(circles), comments=comments)
