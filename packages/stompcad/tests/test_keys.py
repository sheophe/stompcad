"""Every key as data, so distinctness is proved rather than hoped for."""

from __future__ import annotations

from stompcad.stale import PLACE_ORDER
from stompcad.workbench import keys

__all__: list[str] = []


def test_each_place_owns_one_unique_bare_letter() -> None:
    """Decision 3: the eight initials are distinct without compromise."""
    assert len(keys.PLACE_KEYS) == 8
    assert set(keys.PLACE_KEYS.values()) == set(keys.Place)
    assert sorted(keys.PLACE_KEYS) == sorted("aebdfopr")


def test_the_three_global_verbs_claim_no_place_letter() -> None:
    """`w`, `q` and `?` are verbs precisely because no place wants them."""
    assert set(keys.GLOBAL_VERBS) & set(keys.PLACE_KEYS) == set()
    assert set(keys.GLOBAL_VERBS) == {"w", "q", "question_mark"}


def test_nothing_is_claimed_twice() -> None:
    """The whole point: one key, one meaning, wherever it is pressed."""
    assert keys.conflicts() == ()


def test_the_conflict_check_finds_a_planted_clash(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The control. A check that cannot fail proves nothing about the table."""
    monkeypatch.setitem(keys.GLOBAL_VERBS, "b", "planted")
    assert "b" in keys.conflicts()


def test_a_place_value_is_the_name_the_rest_of_the_package_uses() -> None:
    """`readiness` and `stale` name places by string; a drift here breaks both."""
    assert tuple(place.value for place in keys.CONFIGURATION) == PLACE_ORDER


def test_stepping_wraps_in_the_sidebar_s_own_order() -> None:
    """`[` and `]` are the same place change a letter makes, never a second model."""
    assert keys.neighbour(keys.Place.PROJECT, forward=True) is keys.Place.ARTWORK
    assert keys.neighbour(keys.Place.PROJECT, forward=False) is keys.Place.FINDINGS
    assert keys.neighbour(keys.Place.FINDINGS, forward=True) is keys.Place.PROJECT


def test_a_local_key_names_the_place_that_owns_it() -> None:
    """Decision 3: `Ctrl`+letter belongs to the place, never to the app."""
    assert keys.LOCAL_KEYS["ctrl+r"][0] is keys.Place.RUN
    assert keys.LOCAL_KEYS["ctrl+l"][0] is keys.Place.ARTWORK
    assert keys.LOCAL_KEYS["ctrl+f"][0] is keys.Place.ENCLOSURE


def test_the_sidebar_s_keys_take_part_in_the_distinctness_check(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The arrows are only proved distinct if ``conflicts`` reads their tables."""
    monkeypatch.setitem(keys.SIDEBAR_KEYS, "p", ("go('project')", "planted"))
    assert "p" in keys.conflicts()
    monkeypatch.setitem(keys.TO_SIDEBAR, "b", "planted")
    assert "b" in keys.conflicts()
