"""No tracked file cites a decision by number.

A specification is a draft: implementing it is what finds the places it was
wrong, and nothing reconciles it afterwards. So a numbered citation into one
does not merely dangle -- it points at a statement this code may have
deliberately departed from, which is worse for a reader than no comment at
all. An enforced reason belongs in an ADR, which is tracked, linkable and
amended with the work; every other reason belongs where it is needed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SELF = Path(__file__).resolve()

#: ``decision 8``, ``Decisions 6, 8 and 10``, ``ruling 12a``.
_CITATION = re.compile(r"\b(?:decision|ruling)s?\s+\d+[a-z]?\b", re.IGNORECASE)

_TEXT = frozenset({".py", ".md", ".toml", ".cfg", ".txt", ".json", ".yaml", ".yml"})

#: A citation wrapped onto a comment's next line reads ``decision\n# 99``, which
#: ``\s+`` cannot bridge because ``#`` is not whitespace. Blanking the leader in
#: place lets the pattern span it while every offset, and so every reported line
#: number, stays where it was. ``#:`` and a Markdown ``>`` are leaders too, and
#: ``#:`` is where most of the citations this guard was written for lived. A
#: list marker is deliberately not one: ``-`` and ``*`` begin ordinary prose
#: often enough to invite a false positive.
_LEADER = re.compile(r"(?<=\n)([ \t]*)((?:#+:?|>+)[ \t]*)")


def _searchable(body: str) -> str:
    """The file's text with comment leaders blanked, character for character."""
    return _LEADER.sub(lambda m: m.group(1) + " " * len(m.group(2)), body)


def _tracked() -> list[Path]:
    """Every file git tracks, so an ignored spec or plan is never scanned."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
        cwd=_ROOT,
        text=True,
    ).stdout
    return [_ROOT / name for name in listed.split("\0") if name]


def test_the_citation_pattern_catches_what_it_is_for() -> None:
    for caught in (
        "decision 8",
        "Decision 12",
        "decisions 6, 8 and 10",
        "ruling 8",
        "rulings 5",
        "per decision 3a",
    ):
        assert _CITATION.search(caught), caught
    for spared in (
        "the decision",
        "a ruling",
        "decision-making",
        "ADR-0007",
        "every decision we take",
    ):
        assert not _CITATION.search(spared), spared


def test_no_tracked_file_cites_a_decision_by_number() -> None:
    """Each tracked text file is searched whole, with comment leaders blanked.

    ``\\s+`` already matches a newline, and hard-wrapped text puts one between
    ``decision`` and its number often enough that two such citations were
    found by hand and none by reading a line at a time. ``_searchable`` blanks
    what a wrapped comment puts in the way, length for length, so the pattern
    spans a wrap and the reported line is still the one the citation starts
    on, which is where a reader has to go to fix it.
    """
    offenders = []
    for path in _tracked():
        if path.resolve() == _SELF or path.suffix not in _TEXT or not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        # ``split`` and not ``splitlines``, which also breaks on ``\r`` and
        # ``\f``, so that the text shown comes from the line the number counted.
        lines = body.split("\n")
        for match in _CITATION.finditer(_searchable(body)):
            number = body.count("\n", 0, match.start()) + 1
            offenders.append(
                f"{path.relative_to(_ROOT)}:{number}: {lines[number - 1].strip()}"
            )
    # One line can carry two citations; a place is reported once.
    offenders = list(dict.fromkeys(offenders))
    assert not offenders, (
        "a numbered decision cites docs/specs/ or docs/plans/, both git-ignored, "
        "so no reader of this repository can resolve it. State the reason where "
        "it is needed, or link the ADR that holds it:\n" + "\n".join(offenders)
    )
