"""Tests for :mod:`aidrill.model` — the outline's provenance, and its enclosure.

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

The second half of this file covers ``EnclosureMatch``, which answers a
different question about the same outline: *which enclosure was this panel drawn
for?* Its danger is the opposite one — not losing information, but claiming
more than the artwork holds. A 2-D outline identifies a **footprint**, and
several Hammond parts share each footprint because they differ only in height,
so every test below is written to fail the moment the type lets someone read a
part number out of geometry.

Fixtures deliberately use the 120 × 94 footprint: length and width differ, so an
implementation that swaps them cannot pass, and its four candidates line up with
nothing else being asserted.

The third and fourth sections cover the two accessors every renderer reads the
document through, and they are here because both were fully invertible while the
suite stayed green. ``of_severity`` was only ever asserted against documents
holding *no* diagnostics, where the correct predicate and its exact negation both
return ``()``; ``rows`` was only ever asserted through ``len()``, which says
nothing about the order it promises. Every test below is therefore written to
fail under the negation of the rule it names.
"""

from __future__ import annotations

import dataclasses
import operator

import pytest

from aidrill.model import (
    Diagnostic,
    DrillData,
    EnclosureMatch,
    Hole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)

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


# --------------------------------------------------------------------------
# EnclosureMatch: a footprint, never a part
# --------------------------------------------------------------------------

#: The 120 × 94 footprint. Four Hammond parts share it — they differ only in
#: height, which a 2-D outline cannot see. Chosen as the fixture because its
#: length and width differ, so nothing here passes by coincidence.
_1590BB_FOOTPRINT = EnclosureMatch(
    family="Hammond 1590",
    length_mm=120,
    width_mm=94,
    candidates=("1590BB", "1590BB2", "1590BBS", "1590C"),
)


def test_a_match_records_the_catalogue_length_and_width():
    """Kept as given — this fixture is keyword-built, so it pins storage only.

    The *order* of the two declarations is a separate claim, and the positional
    test below is the one that earns it.
    """
    assert _1590BB_FOOTPRINT.length_mm == 120
    assert _1590BB_FOOTPRINT.width_mm == 94


def test_the_field_order_is_family_length_width_candidates():
    """Pinned positionally, because the stage and the emitters agreed on it.

    Length before width is the datasheet's own column order. Swapping the two
    declarations would keep every keyword call site working and quietly
    transpose every positional one.
    """
    positional = EnclosureMatch("Hammond 1590", 120, 94, ("1590BB", "1590BB2"))
    assert positional.family == "Hammond 1590"
    assert positional.length_mm == 120
    assert positional.width_mm == 94
    assert positional.candidates == ("1590BB", "1590BB2")


def test_a_match_names_every_part_that_shares_the_footprint():
    """All four, not one: the outline cannot tell them apart, and neither may we."""
    assert _1590BB_FOOTPRINT.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_match_selects_no_part_of_its_own_accord():
    """``selected_part`` is operator knowledge. Geometry never supplies it.

    Defaulting to anything else — the sole candidate, the first one, the family
    name — would let a drawing print a part number the artwork never stated.
    """
    assert _1590BB_FOOTPRINT.selected_part is None


def test_a_single_candidate_footprint_still_selects_nothing():
    """Even where only one part shares the footprint, the artwork did not say so.

    A default of "the only candidate" would be right here and silently wrong on
    every shared footprint, which is most of the catalogue.
    """
    lone = EnclosureMatch(
        family="Hammond 1590",
        length_mm=145,
        width_mm=95,
        candidates=("1590DD",),
    )
    assert lone.selected_part is None


def test_an_operator_may_declare_the_part_without_narrowing_the_candidates():
    """The declaration is recorded beside the footprint, not folded into it.

    Overwriting ``candidates`` would destroy what the geometry actually
    established, leaving nothing to check a later declaration against.
    """
    declared = dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590C")
    assert declared.selected_part == "1590C"
    assert declared.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_declared_part_outside_the_candidates_is_not_the_models_business():
    """Constructing this must not raise: refusing it here would pre-empt the stage.

    A panel declared as a 1590BB but drawn to a 1590B footprint is a real
    operator error, and it has to reach the diagnostics as ``wrong-enclosure``
    with both names in it. An exception in the value type would instead abort
    the run with no finding to render.
    """
    mismatched = dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590A")
    assert mismatched.selected_part == "1590A"
    assert mismatched.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_match_is_not_rotated_unless_it_says_so():
    assert _1590BB_FOOTPRINT.rotated is False


def test_a_rotated_match_still_reports_the_catalogue_orientation():
    """``rotated`` describes the artwork, not a second, transposed footprint.

    Storing 94 × 120 for a portrait panel would make the same enclosure appear
    twice in the catalogue under two footprints, and a consumer comparing
    against the datasheet would find neither.
    """
    portrait = dataclasses.replace(_1590BB_FOOTPRINT, rotated=True)
    assert portrait.rotated is True
    assert (portrait.length_mm, portrait.width_mm) == (120, 94)


def test_candidates_given_as_a_list_are_stored_as_a_tuple():
    """The same coercion ``StageRun`` and ``Diagnostic`` do, for the same reason.

    A match holding a list is unhashable and compares unequal to the identical
    match built from a tuple, so a document read back from JSON — where every
    sequence arrives as a list — would differ from the one it was written from
    while printing identically.
    """
    from_list = EnclosureMatch(
        family="Hammond 1590",
        length_mm=120,
        width_mm=94,
        candidates=["1590BB", "1590BB2", "1590BBS", "1590C"],  # type: ignore[arg-type]
    )
    assert isinstance(from_list.candidates, tuple)
    assert from_list == _1590BB_FOOTPRINT
    assert hash(from_list) == hash(_1590BB_FOOTPRINT)


def test_the_coercion_keeps_the_order_it_was_given():
    """Catalogue order is the caller's to choose; nothing here re-sorts it.

    Deliberately out of sort order, because every other fixture in this file
    happens to be sorted already — a ``tuple(sorted(...))`` coercion would sail
    through all of them and only surface once a datasheet listed a footprint's
    parts in some other order.
    """
    unsorted = EnclosureMatch(
        family="Hammond 1590",
        length_mm=120,
        width_mm=94,
        candidates=("1590C", "1590BB", "1590BBS", "1590BB2"),
    )
    assert unsorted.candidates == ("1590C", "1590BB", "1590BBS", "1590BB2")


def test_a_bare_string_of_candidates_is_refused():
    """``tuple("1590B")`` is five candidates, and every one of them type-checks.

    The neighbouring coercions in this module can afford not to guard: their
    payloads are tuples of pairs, so a string fails on unpacking and says so.
    ``candidates`` is flat, so the wrong answer is well-formed — it compares,
    hashes, and prints "1", "5", "9", "0", "B" onto a drawing. Nothing later
    can catch it, so construction has to.
    """
    with pytest.raises(TypeError):
        EnclosureMatch(
            family="Hammond 1590",
            length_mm=120,
            width_mm=94,
            candidates="1590BB",  # type: ignore[arg-type]
        )


def test_a_single_candidate_must_still_be_given_as_a_sequence():
    """The guard's real target: one designator is where the mistake is tempting."""
    with pytest.raises(TypeError):
        EnclosureMatch("Hammond 1590", 145, 95, "1590DD")  # type: ignore[arg-type]
    assert EnclosureMatch("Hammond 1590", 145, 95, ("1590DD",)).candidates == ("1590DD",)


def test_enclosure_match_is_frozen_and_slotted():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _1590BB_FOOTPRINT.selected_part = "1590C"  # type: ignore[misc]
    assert not hasattr(_1590BB_FOOTPRINT, "__dict__")


def test_matches_differing_only_in_the_declared_part_are_not_equal():
    """A declared 1590C and an undeclared footprint describe different panels."""
    assert dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590C") != _1590BB_FOOTPRINT


def test_a_transposed_match_is_not_the_same_match():
    assert dataclasses.replace(_1590BB_FOOTPRINT, length_mm=94, width_mm=120) != _1590BB_FOOTPRINT


# --------------------------------------------------------------------------
# DrillData carries the match as domain state
# --------------------------------------------------------------------------


def test_drill_data_starts_with_no_enclosure():
    """Absent, not guessed. No stage has looked at the outline yet."""
    assert DrillData().enclosure is None


def test_an_outline_alone_does_not_identify_an_enclosure():
    """Only the stage sets this. A ``ReferenceOutline`` is a size, not a match."""
    data = DrillData(reference=ReferenceOutline.from_measurement(120.0, 94.0))
    assert data.enclosure is None


def test_with_enclosure_returns_a_new_instance_and_leaves_the_original_alone():
    data = DrillData()
    identified = data.with_enclosure(_1590BB_FOOTPRINT)
    assert identified is not data
    assert identified.enclosure is _1590BB_FOOTPRINT
    assert data.enclosure is None


def test_with_enclosure_keeps_everything_else_the_pipeline_has_accumulated():
    """Guards the ``replace``: rebuilding a ``DrillData`` around the match would
    silently discard the holes, the findings and the stage history."""
    data = DrillData(
        holes=(Hole.from_measurement(7.0, -3.0, 12.0, index=4),),
        reference=ReferenceOutline.from_measurement(113.0, 60.0),
        diagnostics=(Diagnostic.warning("off-grid", "hole 4 is off grid"),),
        source=SourceInfo(path="tar.ai"),
        processing=(StageRun("snap", (("grid_mm", 0.5),)),),
    )
    identified = data.with_enclosure(_1590BB_FOOTPRINT)
    assert identified.holes == data.holes
    assert identified.reference == data.reference
    assert identified.diagnostics == data.diagnostics
    assert identified.source == data.source
    assert identified.processing == data.processing


def test_a_second_identification_replaces_the_first_rather_than_accumulating():
    """The enclosure is current state, not history — unlike ``processing``.

    A consumer asks "which enclosure is this?" and must get one answer. Only the
    audit log records that a stage ran twice.
    """
    first = DrillData().with_enclosure(_1590BB_FOOTPRINT)
    second_match = EnclosureMatch(
        family="Hammond 1590",
        length_mm=112,
        width_mm=61,
        candidates=("1590B", "1590B2", "1590BS"),
    )
    second = first.with_enclosure(second_match)
    assert second.enclosure is second_match


def test_the_enclosure_survives_the_other_transforms():
    """Every transform returns a new instance, and none of them may drop it."""
    data = DrillData(
        reference=ReferenceOutline.from_measurement(120.0, 94.0)
    ).with_enclosure(_1590BB_FOOTPRINT)
    assert data.with_holes([Hole.from_measurement(7.0, -3.0, 12.0, index=4)]).enclosure is (
        _1590BB_FOOTPRINT
    )
    assert data.with_diagnostics(Diagnostic.info("note", "something")).enclosure is (
        _1590BB_FOOTPRINT
    )
    assert data.with_processing(StageRun("snap")).enclosure is _1590BB_FOOTPRINT


def test_the_enclosure_is_re_exported_from_the_package_root():
    """The wider toolchain imports from ``aidrill``, not ``aidrill.model``."""
    import aidrill

    assert aidrill.EnclosureMatch is EnclosureMatch
    assert "EnclosureMatch" in aidrill.__all__


# --------------------------------------------------------------------------
# selecting findings by severity
# --------------------------------------------------------------------------


def four_findings() -> DrillData:
    """One ERROR, one INFO and two WARNINGs, in an order no grouping produces.

    The two warnings are deliberately not adjacent: a selector that returned
    every diagnostic *except* the ones asked for would still hand back a
    non-empty tuple, and one that lost the order they were appended in would
    still hand back the right two.
    """
    return DrillData(
        diagnostics=(
            Diagnostic.warning("off-grid", "hole 4 moved 0.12 mm"),
            Diagnostic.error("unknown-diameter", "⌀30.0 mm is no bit in the drawer"),
            Diagnostic.info("duplicate-hole", "two circles in one place"),
            Diagnostic.warning("unknown-enclosure", "113 × 60 is no catalogue footprint"),
        )
    )


@pytest.mark.parametrize(
    "severity, codes",
    [
        (Severity.ERROR, ["unknown-diameter"]),
        (Severity.WARNING, ["off-grid", "unknown-enclosure"]),
        (Severity.INFO, ["duplicate-hole"]),
    ],
)
def test_of_severity_selects_that_severity_and_nothing_else(severity, codes):
    """Matched on ``code``, and asserted whole: which findings came back, in
    which order, and that every one of them really is the severity asked for."""
    found = four_findings().of_severity(severity)

    assert [diagnostic.code for diagnostic in found] == codes
    assert {diagnostic.severity for diagnostic in found} == {severity}


def test_the_three_severities_partition_the_findings():
    """Every diagnostic appears under exactly one severity, and none is lost.

    The report groups by severity and then states a total, so a selector that
    put a finding in two groups — or in none — would make the two halves of one
    rendering disagree while each looked plausible on its own.
    """
    data = four_findings()
    selected = [
        diagnostic
        for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO)
        for diagnostic in data.of_severity(severity)
    ]

    assert len(selected) == len(data.diagnostics)
    assert set(selected) == set(data.diagnostics)


def test_severities_order_by_how_much_they_matter():
    """``worst_severity`` is a ``max`` over this order, and the exit code is read
    off that — so the order is a contract, not an implementation detail."""
    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert Severity.ERROR > Severity.WARNING > Severity.INFO
    assert Severity.WARNING >= Severity.WARNING and Severity.WARNING <= Severity.WARNING
    assert max((Severity.INFO, Severity.ERROR, Severity.WARNING)) is Severity.ERROR


def test_a_severity_does_not_compare_with_anything_else():
    """An unorderable pair must raise ``TypeError``, which is what a caller
    catching a comparison failure expects. Ranking the members through
    ``list.index`` raised ``ValueError`` instead — a lookup miss reported as
    though the comparison had been attempted."""
    with pytest.raises(TypeError):
        operator.lt(Severity.WARNING, "warning")
    with pytest.raises(TypeError):
        operator.ge(Severity.WARNING, 2)


# --------------------------------------------------------------------------
# grouping holes into rows
# --------------------------------------------------------------------------


def row_panel(*holes: Hole) -> DrillData:
    return DrillData(holes=holes)


def test_rows_run_from_the_top_of_the_panel_down():
    """Descending Y, because the drawing stacks one chain dimension per row and
    builds the stack from the bottom row outwards — so an ascending order does
    not reorder the sheet, it changes *which* rows lose their dimension when the
    stack runs out of room."""
    panel = row_panel(
        Hole.from_measurement(0.0, -18.75, 5.0, index=7),
        Hole.from_measurement(0.0, 18.0, 7.0, index=2),
        Hole.from_measurement(0.0, 0.0, 3.0, index=5),
    )

    assert [y for y, _ in panel.rows()] == [18.0, 0.0, -18.75]


def test_a_row_runs_left_to_right():
    """Ascending X within the row. The holes are handed over in an order that is
    neither ascending nor descending, and named by ``index`` rather than by
    position, so neither a reversal nor "whatever order they arrived in" passes.
    """
    panel = row_panel(
        Hole.from_measurement(20.0, 18.0, 7.0, index=6),
        Hole.from_measurement(-40.0, 18.0, 7.0, index=2),
        Hole.from_measurement(0.0, 18.0, 7.0, index=9),
    )

    (_, holes), = panel.rows()

    assert [hole.index for hole in holes] == [2, 9, 6]
    assert [hole.x for hole in holes] == [-40.0, 0.0, 20.0]


def test_two_holes_a_hair_apart_in_y_are_one_row():
    """Y comes back off the artwork through a snap and a frame translation, so
    two holes the designer drew on one line can differ in the last bits. The
    bucket absorbs that and nothing wider."""
    panel = row_panel(
        Hole.from_measurement(-20.0, 18.0, 7.0, index=3),
        Hole.from_measurement(20.0, 18.0 + 5e-7, 7.0, index=8),
    )

    rows = panel.rows()

    assert len(rows) == 1
    assert [hole.index for hole in rows[0][1]] == [3, 8]


def test_two_holes_half_a_millimetre_apart_are_two_rows():
    """The other side of the same boundary. Half a millimetre is a distance a
    machinist can see on the panel, and a bucket wide enough to swallow it would
    dimension two rows of holes as one."""
    panel = row_panel(
        Hole.from_measurement(-20.0, 18.0, 7.0, index=3),
        Hole.from_measurement(20.0, 17.5, 7.0, index=8),
    )

    assert [y for y, _ in panel.rows()] == [18.0, 17.5]
