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

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SELF = Path(__file__).resolve()

#: ``decision 8``, ``Decisions 6, 8 and 10``, ``ruling 12a``.
_CITATION = re.compile(r"\b(?:decision|ruling)s?\s+\d+[a-z]?\b", re.IGNORECASE)

_TEXT = frozenset({".py", ".md", ".toml", ".cfg", ".txt", ".json", ".yaml", ".yml"})


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "citations across files are being swept; the marker goes when "
        "the last file is clean"
    ),
)
def test_no_tracked_file_cites_a_decision_by_number() -> None:
    offenders = []
    for path in _tracked():
        if path.resolve() == _SELF or path.suffix not in _TEXT or not path.is_file():
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if _CITATION.search(line):
                offenders.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "a numbered decision cites docs/specs/ or docs/plans/, both git-ignored, "
        "so no reader of this repository can resolve it. State the reason where "
        "it is needed, or link the ADR that holds it:\n" + "\n".join(offenders)
    )
