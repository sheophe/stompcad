"""The Hammond model harness: opt-in, cache lookup, and skip behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.hammond import MODELS, cache_dir, model_path


def test_the_catalogue_covers_the_models_the_kernel_tests_use():
    assert set(MODELS) == {"1590BB", "1590B", "1590A", "1590Y"}


def test_each_model_records_the_measurements_tests_assert_against():
    bb = MODELS["1590BB"]

    assert bb.footprint_mm == (119.5, 94.0)
    assert bb.box_plate_mm == 2.25
    assert bb.lid_plate_mm == 2.0


def test_the_probe_points_are_distinct_places_on_the_face():
    """Four probes that all landed in one spot would test one thing four times."""
    from tests.hammond import BB_PROBES

    assert len(set(BB_PROBES.values())) == len(BB_PROBES)


def test_the_boss_probe_lies_inside_the_play_area_rectangle():
    """It must separate THROUGH_BOSS from OFF_FACE, so it cannot be off the face."""
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["boss"]
    assert abs(x) < 55.33 and abs(y) < 42.58


def test_the_boss_probe_lies_within_a_boss_disc():
    from tests.hammond import BB_PROBES

    x, y = BB_PROBES["boss"]
    assert ((x - 54.75) ** 2 + (y - 42.0) ** 2) ** 0.5 < 5.17


def test_the_two_models_have_different_footprints():
    """One model cannot show that the axis was derived rather than hard-coded."""
    assert MODELS["1590BB"].footprint_mm != MODELS["1590B"].footprint_mm


def test_every_model_matches_the_shipped_catalogue():
    """The harness must not drift from stompdrill's own enclosure dimensions."""
    from stompdrill.enclosures import HAMMOND_1590

    catalogue = {e.part: e for e in HAMMOND_1590}
    for part, model in MODELS.items():
        entry = catalogue[part]
        assert model.footprint_mm == (
            entry.length_nm / 1_000_000,
            entry.width_nm / 1_000_000,
        )
        assert model.height_mm == entry.height_nm / 1_000_000


def test_model_path_returns_none_when_the_cache_is_empty(tmp_path, monkeypatch):
    from tests import hammond

    monkeypatch.setattr(hammond, "cache_dir", lambda: tmp_path)

    assert model_path("1590BB") is None


def test_model_path_returns_the_file_when_the_cache_holds_it(tmp_path, monkeypatch):
    from tests import hammond

    monkeypatch.setattr(hammond, "cache_dir", lambda: tmp_path)
    (tmp_path / "1590BB.stp").write_bytes(b"ISO-10303-21;\n")

    assert model_path("1590BB") == tmp_path / "1590BB.stp"


def test_model_path_rejects_a_designator_outside_the_catalogue():
    with pytest.raises(ValueError):
        model_path("1590ZZ")


def test_the_cache_directory_is_the_one_the_fetch_script_writes(monkeypatch):
    """Harness and helper must not disagree about where models live.

    Compared against the helper's own function, not a re-typed literal: a
    literal can only match today's value, not prove the two can never diverge.
    """
    from tools import fetch_case_model

    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    assert cache_dir is fetch_case_model.cache_dir
    assert cache_dir() == fetch_case_model.cache_dir() == Path.home() / ".cache" / "stompcad" / "cases"


def test_the_cache_directory_honours_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert cache_dir() == tmp_path / "stompcad" / "cases"


@pytest.mark.hammond
def test_a_hammond_marked_test_is_skipped_without_the_flag():
    """Runs only under --hammond; its presence proves the marker is registered."""
    assert True
