"""No tracked text file cites a decision by number.

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

#: ``decision 8``, ``Decisions 6, 8 and 10``, ``ruling 12a``, ``ruling R1``: a
#: draft numbers its rulings and sometimes letters them, and a letter where a
#: digit was expected is how one such citation lived here unseen. These two
#: words only -- ``ticket 35``, ``AC2`` and the rest name records of the same
#: drafts, and whether those are citations to remove is not settled here. The
#: separator carries at most one newline, so a citation wrapped inside one
#: paragraph or comment block is caught while a heading and the numbered list
#: under it stay two items; ``\s+`` cannot tell those apart.
_CITATION = re.compile(
    r"\b(?:decision|ruling)s?(?:[ \t\r]*\n[ \t\r]*|[ \t\r]+)[a-z]?\d+[a-z]?\b",
    re.IGNORECASE,
)

#: What is read, by extension and never by sniffing content: a reason lives in
#: prose or in configuration. Everything else tracked here is an empty typing
#: marker, a binary fixture, a lockfile, a licence, a measurement table, two
#: ignore lists or one shell script, and the only prose among them is that
#: script's header, which cites an ADR as this repository asks. Extensions and
#: not content, so a tracked binary is never decoded to search it.
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
        "ruling R1",
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


def test_a_citation_wrapped_onto_the_next_line_is_still_found() -> None:
    """Every shape a wrapped citation takes, through the blanking that bridges it.

    A comment leader is not whitespace, so four of these five escape a
    pattern reading the raw text: the citations this guard was written for
    lived in ``#:`` blocks, where hard wrapping is what put the number on
    its own line. ``_searchable`` replaced by the identity function fails
    this, which no other test here notices.
    """
    for wrapped in (
        "see decision 4 for the reason",
        "# a reason, per decision\n# 4 of the draft",
        "#: a reason, per decision\n#: 4 of the draft",
        "a reason, per decision\n4 of the draft",
        "> a reason, per decision\n> 4 of the draft",
    ):
        assert _CITATION.search(_searchable(wrapped)), wrapped


def test_a_heading_and_the_numbered_list_below_it_are_no_citation() -> None:
    """A blank line puts the number in another item, so ``## Decision`` then ``1.`` is spared.

    Blanking the heading's own leader is what brings its text up against
    the list under it, and every ADR has that heading. One opening it with
    a numbered list, or with a paragraph starting on a digit, would
    otherwise be told it cites a git-ignored draft.
    """
    heading = "the context above\n\n## Decision\n\n1. the first clause\n"
    assert not _CITATION.search(_searchable(heading)), heading


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
    read = set()
    for path in _tracked():
        if path.resolve() == _SELF or path.suffix not in _TEXT or not path.is_file():
            continue
        read.add(path.suffix)
        body = path.read_text(encoding="utf-8")
        # ``split`` and not ``splitlines``, which also breaks on ``\r`` and
        # ``\f``, so that the text shown comes from the line the number counted.
        lines = body.split("\n")
        for match in _CITATION.finditer(_searchable(body)):
            number = body.count("\n", 0, match.start()) + 1
            offenders.append(
                f"{path.relative_to(_ROOT)}:{number}: {lines[number - 1].strip()}"
            )
    # A listing that came back empty, or a suffix filter that admitted
    # nothing, would report no offender while reading no file.
    assert {".py", ".md", ".toml"} <= read
    # One line can carry two citations; a place is reported once.
    offenders = list(dict.fromkeys(offenders))
    assert not offenders, (
        "a numbered decision cites docs/specs/ or docs/plans/, both git-ignored, "
        "so no reader of this repository can resolve it. State the reason where "
        "it is needed, or link the ADR that holds it:\n" + "\n".join(offenders)
    )
