"""The panel-reference filter: a left-to-right fold over comma-separated terms.

Each term is a literal, glob or inclusive integer range, optionally negated.
``admit`` starts from the empty set and applies each term's polarity in
order, so a later term overrides an earlier one -- there is no set algebra
and no default admission.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import translate

from stompcollider.errors import UsageError

__all__ = ["Term", "Filter", "parse_filter"]

_RANGE = re.compile(r"^(?P<prefix>[^()]+)\((?P<lo>-?\d+)\.\.(?P<hi>-?\d+)\)$")

#: How many values one range term may name. Unlike its neighbouring
#: constants, this figure is not measured against any gap: there is no
#: population of legitimate-huge and illegitimate-huge ranges to separate,
#: so it is a resource bound chosen as policy. A range names parts on one
#: board, where a few hundred sharing a prefix is already dense, so nothing
#: real is refused. The alternation a range compiles into grows with the
#: range and not with the expression's own length -- thirteen typed
#: characters can ask for a megabyte of pattern -- and the count is known
#: before any of it is built, so refusing costs nothing. It is a usage
#: failure like the descending range beside it, not a diagnostic.
_MAX_RANGE_VALUES = 10_000


@dataclass(frozen=True, slots=True)
class Term:
    """One parsed clause: a compiled matcher and whether it admits or removes."""

    pattern: re.Pattern[str]
    negated: bool

    def matches(self, designator: str) -> bool:
        return self.pattern.match(designator) is not None


@dataclass(frozen=True, slots=True)
class Filter:
    """An ordered sequence of terms, applied left to right by ``admit``."""

    terms: tuple[Term, ...]

    def admit(self, designators: Iterable[str]) -> frozenset[str]:
        present = tuple(designators)
        kept: set[str] = set()
        for term in self.terms:
            matched = {d for d in present if term.matches(d)}
            if term.negated:
                kept -= matched
            else:
                kept |= matched
        return frozenset(kept)


def _compile_range(prefix: str, lo_text: str, hi_text: str) -> re.Pattern[str]:
    lo, hi = int(lo_text), int(hi_text)
    if lo > hi:
        raise UsageError(f"descending range in designator filter term: {prefix}({lo}..{hi})")
    if hi - lo + 1 > _MAX_RANGE_VALUES:
        raise UsageError(
            f"range in designator filter term names {hi - lo + 1} values, more than "
            f"the {_MAX_RANGE_VALUES} one term may: {prefix}({lo}..{hi})"
        )
    alternatives = "|".join(str(n) for n in range(lo, hi + 1))
    return re.compile(f"^{re.escape(prefix)}(?:{alternatives})$")


def _compile_term(pattern: str) -> re.Pattern[str]:
    # Parentheses belong to the range production alone: the grammar gives
    # literals and globs no use for them, so any paren not forming a well
    # formed range is a malformed term rather than an unusual literal.
    if "(" in pattern or ")" in pattern:
        match = _RANGE.match(pattern)
        if match is None:
            raise UsageError(f"malformed range in designator filter term: {pattern!r}")
        return _compile_range(match["prefix"], match["lo"], match["hi"])
    return re.compile(translate(pattern))


def parse_filter(expression: str) -> Filter:
    """Parse a comma-separated filter expression, or raise ``UsageError``.

    Resolved by the CLI before any file opens, so every refusal here is a
    usage failure (exit 3), never a run-time diagnostic.
    """
    if expression.strip() == "":
        raise UsageError("empty designator filter expression")

    terms = []
    for raw in expression.split(","):
        text = raw.strip()
        if text == "":
            raise UsageError(f"empty term in designator filter: {expression!r}")
        negated = text.startswith("!")
        pattern = text[1:] if negated else text
        if pattern == "":
            raise UsageError(f"negation with no pattern in designator filter: {text!r}")
        terms.append(Term(_compile_term(pattern), negated))

    return Filter(tuple(terms))
