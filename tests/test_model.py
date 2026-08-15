"""Tests for :mod:`aidrill.model` — specifically the outline's provenance.

``Hole`` has kept its as-measured values apart from its nominal ones since the
snapping stage existed. ``ReferenceOutline`` did not, and a later stage snaps
the outline to a Hammond catalogue size: the fixture panel measures
113.000 × 60.000 mm and the datasheet says 112 × 61, so the snap rewrites a real
measurement. Before ``raw`` existed there was nowhere left holding what the
artwork actually said, and no way to tell a 113 that was measured from a 113
that was snapped from something else.

These tests therefore assert on both halves at once. Asserting only that
``resized`` reports the new size would stay green under an implementation that
overwrites ``raw`` with it, which is the exact bug the field exists to prevent.
"""

from __future__ import annotations

import dataclasses

import pytest

from aidrill.model import RawOutline, ReferenceOutline

# --------------------------------------------------------------------------
# provenance survives a resize
# --------------------------------------------------------------------------


def test_snapping_the_outline_does_not_destroy_what_was_measured():
    outline = ReferenceOutline.from_measurement(113.0, 60.0)
    snapped = outline.resized(112.0, 61.0)
    assert (snapped.width, snapped.height) == (112.0, 61.0)
    assert (snapped.raw.width, snapped.raw.height) == (113.0, 60.0)


def test_resizing_twice_still_reports_the_original_measurement():
    """Provenance is the *measurement*, not the previous nominal value.

    Carrying forward "what it was before this resize" would look identical
    after one snap and be wrong after two — and nothing forbids a second one.
    """
    outline = ReferenceOutline.from_measurement(113.0, 60.0)
    twice = outline.resized(112.0, 61.0).resized(120.0, 94.0)
    assert (twice.width, twice.height) == (120.0, 94.0)
    assert (twice.raw.width, twice.raw.height) == (113.0, 60.0)


def test_resizing_returns_a_new_outline_and_leaves_the_original_alone():
    outline = ReferenceOutline.from_measurement(113.0, 60.0)
    snapped = outline.resized(112.0, 61.0)
    assert snapped is not outline
    assert (outline.width, outline.height) == (113.0, 60.0)
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)


def test_resizing_keeps_the_source_space_centre():
    """The snap changes the size, not where the outline was found on the page."""
    outline = ReferenceOutline.from_measurement(113.0, 60.0, centre_x=297.6, centre_y=421.0)
    snapped = outline.resized(112.0, 61.0)
    assert (snapped.centre_x, snapped.centre_y) == (297.6, 421.0)


def test_resizing_still_refuses_a_non_positive_size():
    """The guard is on the value, not on the constructor a caller happened to use."""
    outline = ReferenceOutline.from_measurement(113.0, 60.0)
    with pytest.raises(ValueError):
        outline.resized(0.0, 61.0)
    with pytest.raises(ValueError):
        outline.resized(112.0, -61.0)


# --------------------------------------------------------------------------
# what ``raw`` holds
# --------------------------------------------------------------------------


def test_from_measurement_records_the_measurement_it_was_given():
    outline = ReferenceOutline.from_measurement(113.0, 60.0, centre_x=297.6, centre_y=421.0)
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)
    assert (outline.width, outline.height) == (113.0, 60.0)
    assert (outline.centre_x, outline.centre_y) == (297.6, 421.0)


def test_a_plainly_constructed_outline_is_its_own_measurement():
    """Two-argument construction predates this field and must keep working.

    An outline nobody has snapped *is* as-measured, so ``raw`` mirroring its own
    dimensions is the truthful answer — and it means no call site has to decide
    whether provenance is known, which is what a ``None`` here would have cost.
    """
    outline = ReferenceOutline(113.0, 60.0)
    assert outline.raw == RawOutline(113.0, 60.0)


def test_an_explicit_raw_is_never_replaced_by_the_nominal_values():
    outline = ReferenceOutline(112.0, 61.0, raw=RawOutline(113.0, 60.0))
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)


def test_raw_is_never_none():
    """The field exists to remove an ambiguity; ``None`` would reintroduce it."""
    assert ReferenceOutline(113.0, 60.0).raw is not None
    assert ReferenceOutline.from_measurement(113.0, 60.0).raw is not None


# --------------------------------------------------------------------------
# value-object mechanics, the same as RawHole's
# --------------------------------------------------------------------------


def test_raw_outline_is_frozen_and_slotted():
    raw = RawOutline(113.0, 60.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        raw.width = 112.0  # type: ignore[misc]
    assert not hasattr(raw, "__dict__")


def test_raw_outline_compares_by_value():
    assert RawOutline(113.0, 60.0) == RawOutline(113.0, 60.0)
    assert RawOutline(113.0, 60.0) != RawOutline(60.0, 113.0)


def test_outlines_differing_only_in_provenance_are_not_equal():
    """A snapped 112 × 61 and a measured one describe different panels.

    This is the only test pinning ``raw`` into equality, and it has to be:
    the JSON round-trip test can only notice a dropped measurement once its
    own fixture carries a snapped outline, because an unsnapped one rebuilds
    its ``raw`` from the nominal values and compares equal either way.
    """
    measured = ReferenceOutline.from_measurement(112.0, 61.0)
    snapped = ReferenceOutline.from_measurement(113.0, 60.0).resized(112.0, 61.0)
    assert measured != snapped


# --------------------------------------------------------------------------
# the guard that was already there
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width,height",
    [(0.0, 60.0), (113.0, 0.0), (-113.0, 60.0), (113.0, -60.0)],
)
def test_a_non_positive_outline_is_refused(width, height):
    with pytest.raises(ValueError):
        ReferenceOutline(width, height)


def test_from_measurement_refuses_a_non_positive_outline():
    with pytest.raises(ValueError):
        ReferenceOutline.from_measurement(0.0, 60.0)
