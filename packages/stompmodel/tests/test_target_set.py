"""The set-level write precondition, shared by every tool that emits a set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stompmodel.protocols import check_target_set, target_key


def test_two_spellings_of_one_path_share_a_key(tmp_path: Path) -> None:
    """A filesystem may hold two spellings as one file, so the key folds case
    and Unicode normalisation."""
    assert target_key(tmp_path / "Out.STP") == target_key(tmp_path / "out.stp")


def test_a_symlinked_pair_shares_a_key(tmp_path: Path) -> None:
    """Resolution, not string equality: two names joined by a link are one file.

    This is the clause a key built from the unresolved path passes silently.
    """
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    os.symlink(real, link)
    assert target_key(link) == target_key(real)


def test_two_normalisation_forms_of_one_name_are_refused(tmp_path: Path) -> None:
    """Case is only half of the fold: an NFC and an NFD spelling of one name
    are two distinct Python strings but one file on disk, so a ``casefold``-
    only key would miss this pair. Built from explicit ``\\uXXXX`` escapes --
    never a typed accented character -- so no editor or source encoding can
    normalise the collision away before the test even runs.
    """
    nfc = tmp_path / "caf\u00e9.stp"  # precomposed: e-acute as one code point
    nfd = tmp_path / "cafe\u0301.stp"  # decomposed: e plus a combining acute
    # Fixture control: a probe that can pass by finding nothing is not
    # evidence. Were these already one string there would be no collision
    # left for the fold below to catch.
    assert str(nfc) != str(nfd)

    with pytest.raises(ValueError, match="one file"):
        check_target_set([nfc, nfd])


def test_a_colliding_set_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one file"):
        check_target_set([tmp_path / "a.json", tmp_path / "A.JSON"])


def test_a_distinct_set_is_accepted(tmp_path: Path) -> None:
    """The innocent probe: a legitimate set must not be refused."""
    assert check_target_set([tmp_path / "a.json", tmp_path / "b.stp"]) is None  # type: ignore[func-returns-value]


def test_an_existing_non_regular_target_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "somewhere"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        check_target_set([directory])


def test_an_existing_regular_target_is_accepted(tmp_path: Path) -> None:
    """Overwriting a file this tool wrote before is the normal case."""
    existing = tmp_path / "a.json"
    existing.write_text("{}")
    assert check_target_set([existing]) is None  # type: ignore[func-returns-value]
