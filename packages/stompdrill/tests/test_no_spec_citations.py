"""No tracked text file cites a decision, or a record of one, by number.

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

#: Between a word and its number: at most one newline, so a citation wrapped
#: inside one paragraph or comment block is caught while a heading and the
#: numbered list under it stay two items; ``\s+`` cannot tell those apart.
_SEP = r"(?:[ \t\r]*\n[ \t\r]*|[ \t\r]+)"

#: ``decision 8``, ``Decisions 6, 8 and 10``, ``ruling 12a``, ``ruling R1``: a
#: draft numbers its rulings and sometimes letters them, and a letter where a
#: digit was expected is how one such citation lived here unseen.
_CITATION = re.compile(r"\b(?:decision|ruling)s?" + _SEP + r"[a-z]?\d+[a-z]?\b", re.IGNORECASE)

#: ``ticket 48``, ``Criterion 3``, ``criteria 2``, ``fix round 2``, ``F3-01``:
#: the records a draft's own process keeps. Case is free here because none of
#: these shapes is one ordinary code takes -- each word needs its number, so
#: "the ticket" and "acceptance criteria" are spared, and a falsifier's hyphen
#: is not a character an identifier can carry.
_PROCESS_WORDS = re.compile(
    r"\bF\d+-\d+\b|\b(?:ticket|criteri(?:on|a)|fix" + _SEP + r"round)" + _SEP + r"\d+\b",
    re.IGNORECASE,
)

#: ``AC2`` and ``T15``: the acceptance criteria and tasks written as bare
#: identifiers. Case matters for exactly these two, because ``ac2`` and
#: ``t15`` are shapes ordinary code takes and a citation is written the way
#: the draft wrote it. A quoted ``"T10"`` is spared because an Excellon tool
#: code is written exactly so, and two digits are required because ``T1`` is
#: a tool code and never a task.
_PROCESS_IDS = re.compile(r"\bAC\d+\b|(?<![\"'])\bT\d{2}\b")

_PATTERNS = (_CITATION, _PROCESS_WORDS, _PROCESS_IDS)

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


def _citations(body: str) -> list[tuple[int, str]]:
    """Every citation in ``body``, as the line it starts on and what matched.

    One path for the scan and for the pattern tests, so a rule proved here is
    the rule that runs. A match that is the whole of its line is data and not
    prose: an Excellon tool change is written ``T10`` alone, where a citation
    sits in a sentence beside the reason it stands in for.
    """
    searchable = _searchable(body)
    lines = searchable.split("\n")
    found = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(searchable):
            number = searchable.count("\n", 0, match.start()) + 1
            if lines[number - 1].strip() == match.group(0):
                continue
            found.append((number, match.group(0)))
    return found


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


def test_the_process_pattern_catches_the_records_of_a_draft() -> None:
    """The vocabularies beside ``decision``: falsifier, ticket, criterion, task.

    Each named a record under ``.scratch/``, which this repository ignores and
    which holds no tracked file at all, so a reader meets the same dead end a
    decision number leads to. The spared list is what a guard this broad has
    to leave alone: a drill file's tool codes, and the words without a number.
    """
    for caught in (
        "see F3-01 for the shape",
        "the f3-01 falsifier",
        "per ticket 48",
        "Ticket 25 moved it",
        "AC2 asks for this",
        "Criterion 3: one owner",
        "criteria 2 and 4",
        "fix round 2 found it",
        "the reconciliation (T15) assumes",
        "F3-03 / T08 reconciled",
    ):
        assert _citations(caught), caught
    for spared in (
        "the ticket this closes",
        "acceptance criteria",
        "ADR-0007",
        "AC",
        "T1",
        "T1C",
        '"T10"',
        "T10C0.800",
        "t15 = compute()",
        "ac2 = 3",
        "F3",
    ):
        assert not _citations(spared), spared


def test_an_excellon_tool_change_alone_on_its_line_is_no_citation() -> None:
    """``T10`` is a tool change where ``(T15)`` is a citation.

    A payload asserted in a test carries the code on a line of its own, which
    is the one shape that would fail this suite over a drill file rather than
    a draft. The rule is positional and not a list of codes, so a tool number
    this repository has never emitted is spared on the same terms.
    """
    payload = "M48\nT10C0.800\n%\nT10\nX0Y0\nM30\n"
    assert not _citations(payload), payload
    assert _citations("the task (T10) is done")


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


def test_no_tracked_text_file_cites_a_decision_by_number() -> None:
    """Each tracked text file is searched whole, with comment leaders blanked.

    Hard wrapping puts a newline between ``decision`` and its number often
    enough that reading a line at a time misses a citation outright, so the
    search spans one. ``_searchable`` blanks what a wrapped comment puts in
    the way, length for length, so the line reported is still the one the
    citation starts on, which is where a reader has to go to fix it.
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
        for number, _text in _citations(body):
            offenders.append(
                f"{path.relative_to(_ROOT)}:{number}: {lines[number - 1].strip()}"
            )
    # A listing that came back empty, or a suffix filter that admitted
    # nothing, would report no offender while reading no file.
    assert {".py", ".md", ".toml"} <= read
    # One line can carry two citations; a place is reported once.
    offenders = list(dict.fromkeys(offenders))
    assert not offenders, (
        "a number cites docs/specs/, docs/plans/ or .scratch/, all git-ignored, "
        "so no reader of this repository can resolve it. State the reason where "
        "it is needed, or link the ADR that holds it:\n" + "\n".join(offenders)
    )
