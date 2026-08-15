"""Tests for :mod:`aidrill.model` — its unit, the outline's provenance, its enclosure.

Every length here is a whole number of nanometres, and the first section is
about nothing else. A model that will hold a float holds a quantity two
artifacts can round differently: 7.0000000000000009 mm is one bit in a drill
file and another in a drawing, and the panel they describe is the same panel.
The guards are therefore at construction, where the offending value still has a
call site to point at, rather than at the far end of a pipeline where all that
is left is a number nobody can explain. ``bool`` is the case worth naming: it is
an ``int`` in Python, so a ``True`` that reached a coordinate would satisfy
``isinstance`` and be drilled at 1 nm.

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

The next section covers ``EnclosureMatch``, which answers a different question
about the same outline: *which enclosure was this panel drawn for?* Its danger
is the opposite one — not losing information, but claiming more than the artwork
holds. A 2-D outline identifies a **footprint**, and several Hammond parts share
each footprint because they differ only in height, so every test below is
written to fail the moment the type lets someone read a part number out of
geometry.

Fixtures deliberately use the 120 × 94 footprint: length and width differ, so an
implementation that swaps them cannot pass, and its four candidates line up with
nothing else being asserted.

The last two sections cover the two accessors every renderer reads the document
through, and they are here because both were fully invertible while the suite
stayed green. ``of_severity`` was only ever asserted against documents holding
*no* diagnostics, where the correct predicate and its exact negation both return
``()``; ``rows`` was only ever asserted through ``len()``, which says nothing
about the order it promises. Every test below is therefore written to fail under
the negation of the rule it names.
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
    Origin,
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)

# --------------------------------------------------------------------------
# every length is a whole number of nanometres
# --------------------------------------------------------------------------


def test_every_length_on_a_hole_is_an_integer():
    """``type(...) is int``, not ``isinstance``.

    ``bool`` is a subclass of ``int``, so an assertion written with
    ``isinstance`` would accept a ``True`` that had found its way into a
    coordinate and call it a nanometre.
    """
    hole = Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=4)
    for value in (
        hole.x_nm,
        hole.y_nm,
        hole.diameter_nm,
        hole.raw.x_nm,
        hole.raw.y_nm,
        hole.raw.diameter_nm,
    ):
        assert type(value) is int


#: A length that crossed no unit boundary: it is the shape of 7 mm and it is not
#: an integer, which is the whole of what makes it inadmissible.
_A_FLOAT = 7_000_000.5

#: Valid provenance to hand a constructor whose guard is not the one under test.
#: ``ReferenceOutline`` needs it explicitly: left to default, the sentinel path
#: builds a ``RawOutline`` out of the very values being tested and *that* guard
#: raises, so the outline's own guard could be deleted and the test would still
#: pass on someone else's work.
_VALID_RAW_HOLE = RawHole(0, 0, 7_000_000)
_VALID_RAW_OUTLINE = RawOutline(113_000_000, 60_000_000)

#: Every ``(owner, field)`` pair the model guards, one builder each, named by
#: the pair so a failure says which guard went missing.
#:
#: Enumerated exhaustively and one field at a time because the guards are a
#: folded condition: they are separate keyword arguments to one helper, the
#: helper is strict, and a *call* that quietly stops naming a field is invisible
#: from anywhere else. Six of these pairs — both of ``RawHole``'s trailing
#: lengths, ``Hole.y_nm``, ``RawOutline.height_nm`` and both of
#: ``ReferenceOutline``'s Y-axis lengths — could each be dropped from their
#: call with the whole suite staying green. Proving the X axis proves nothing
#: about the Y.
_GUARDED_LENGTHS = [
    pytest.param(lambda v: RawHole(v, 0, 7_000_000), id="RawHole.x_nm"),
    pytest.param(lambda v: RawHole(0, v, 7_000_000), id="RawHole.y_nm"),
    pytest.param(lambda v: RawHole(0, 0, v), id="RawHole.diameter_nm"),
    pytest.param(lambda v: Hole(v, 0, 7_000_000, _VALID_RAW_HOLE, 4), id="Hole.x_nm"),
    pytest.param(lambda v: Hole(0, v, 7_000_000, _VALID_RAW_HOLE, 4), id="Hole.y_nm"),
    pytest.param(lambda v: Hole(0, 0, v, _VALID_RAW_HOLE, 4), id="Hole.diameter_nm"),
    pytest.param(lambda v: RawOutline(v, 60_000_000), id="RawOutline.width_nm"),
    pytest.param(lambda v: RawOutline(113_000_000, v), id="RawOutline.height_nm"),
    pytest.param(
        lambda v: ReferenceOutline(v, 60_000_000, raw=_VALID_RAW_OUTLINE),
        id="ReferenceOutline.width_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(113_000_000, v, raw=_VALID_RAW_OUTLINE),
        id="ReferenceOutline.height_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(
            113_000_000, 60_000_000, centre_x_nm=v, raw=_VALID_RAW_OUTLINE
        ),
        id="ReferenceOutline.centre_x_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(
            113_000_000, 60_000_000, centre_y_nm=v, raw=_VALID_RAW_OUTLINE
        ),
        id="ReferenceOutline.centre_y_nm",
    ),
    pytest.param(
        lambda v: EnclosureMatch("Hammond 1590", v, 94_000_000, ("1590BB",)),
        id="EnclosureMatch.length_nm",
    ),
    pytest.param(
        lambda v: EnclosureMatch("Hammond 1590", 120_000_000, v, ("1590BB",)),
        id="EnclosureMatch.width_nm",
    ),
]


@pytest.mark.parametrize("build", _GUARDED_LENGTHS)
def test_a_float_is_not_a_length(build):
    """Refused at construction, where the offending value still has a call site.

    A float that gets in is only ever noticed at the far end, as a drill file
    reading ``X6.999999999`` with nothing left to say where the value came from
    — and it is a quantity the drill file and the drawing may round differently,
    which is one panel described by two disagreeing artifacts.
    """
    with pytest.raises(TypeError, match="nanometres"):
        build(_A_FLOAT)


@pytest.mark.parametrize("build", _GUARDED_LENGTHS)
def test_a_bool_is_not_a_length(build):
    """``True`` is an ``int`` in Python, and ``isinstance(True, int)`` is
    ``True``. A guard written that way accepts it, and a hole at ``True``
    nanometres is a hole one millionth of a millimetre from the origin — a
    position no report would ever make look wrong. Asserted for every guarded
    field and not only for the float, because ``type(v) is int`` and
    ``isinstance(v, int)`` differ on exactly this value and nothing else."""
    with pytest.raises(TypeError, match="nanometres"):
        build(True)


def test_translation_is_exact_however_many_times_it_is_applied():
    """The property integers buy and floating point does not.

    The obvious form of this test is the symmetric walk at the end — a thousand
    steps of +1 nm and a thousand back — and on its own it earns nothing: in
    millimetres the return trip retraces the rounding of the outward one step
    for step, so ``-40.0`` walked a thousand microns out and back really does
    come home, and the test passes on an implementation with no integers in it
    at all.

    What floating point cannot do is agree with itself about where those
    thousand steps left off: ``-40.0`` plus ``1e-6`` a thousand times is not
    ``-40.0`` plus ``1e-3``, and the gap is the rounding of every step in
    between. That is not a contrived pairing — a snap nudges each hole a
    little, a frame change moves the whole panel at once, and both numbers are
    printed on the same sheet.
    """
    hole = Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=4)

    stepped = hole
    for _ in range(1000):
        stepped = stepped.translated(1, 0)

    assert stepped.x_nm == hole.translated(1_000, 0).x_nm
    assert stepped.translated(-1_000, 0).x_nm == hole.x_nm

    walked = stepped
    for _ in range(1000):
        walked = walked.translated(-1, 0)
    assert walked.x_nm == hole.x_nm


def test_a_translated_hole_keeps_its_identity_and_its_measurement():
    """``translated`` moves the nominal position and nothing else. Rebuilding
    the hole would renumber it and overwrite what the artwork measured."""
    hole = Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=4)
    moved = hole.translated(56_000_000, 30_500_000)
    assert (moved.x_nm, moved.y_nm) == (16_000_000, 48_500_000)
    assert moved.index == 4
    assert moved.raw == RawHole(-40_000_000, 18_000_000, 7_000_000)


def test_the_residual_is_the_nominal_position_less_the_measured_one():
    """Positive means the nominal value is the larger, in nanometres. Named
    ``residual_nm`` because it is three lengths, and a caller printing it as
    millimetres would be three decimal places out with nothing to notice."""
    hole = Hole.from_measurement(-39_990_600, 18_000_400, 6_800_000, index=4)
    snapped = hole.moved_to(-40_000_000, 18_000_000).with_diameter(7_000_000)
    assert snapped.residual_nm == (-9_400, -400, 200_000)


# --------------------------------------------------------------------------
# provenance survives a resize
# --------------------------------------------------------------------------


def test_snapping_the_outline_does_not_destroy_what_was_measured():
    outline = ReferenceOutline.from_measurement(113_000_000, 60_000_000)
    snapped = outline.resized(112_000_000, 61_000_000)
    assert (snapped.width_nm, snapped.height_nm) == (112_000_000, 61_000_000)
    assert (snapped.raw.width_nm, snapped.raw.height_nm) == (113_000_000, 60_000_000)


def test_resizing_twice_still_reports_the_original_measurement():
    """Provenance is the *measurement*, not the previous nominal value.

    Carrying forward "what it was before this resize" would look identical
    after one snap and be wrong after two — and nothing forbids a second one.
    """
    outline = ReferenceOutline.from_measurement(113_000_000, 60_000_000)
    twice = outline.resized(112_000_000, 61_000_000).resized(120_000_000, 94_000_000)
    assert (twice.width_nm, twice.height_nm) == (120_000_000, 94_000_000)
    assert (twice.raw.width_nm, twice.raw.height_nm) == (113_000_000, 60_000_000)


def test_resizing_returns_a_new_outline_and_leaves_the_original_alone():
    outline = ReferenceOutline.from_measurement(113_000_000, 60_000_000)
    snapped = outline.resized(112_000_000, 61_000_000)
    assert snapped is not outline
    assert (outline.width_nm, outline.height_nm) == (113_000_000, 60_000_000)
    assert (outline.raw.width_nm, outline.raw.height_nm) == (113_000_000, 60_000_000)


def test_resizing_keeps_the_source_space_centre():
    """The snap changes the size, not where the outline was found on the page."""
    outline = ReferenceOutline.from_measurement(
        113_000_000, 60_000_000, centre_x_nm=297_600_000, centre_y_nm=421_000_000
    )
    snapped = outline.resized(112_000_000, 61_000_000)
    assert (snapped.centre_x_nm, snapped.centre_y_nm) == (297_600_000, 421_000_000)


def test_resizing_still_refuses_a_non_positive_size():
    """The guard is on the value, not on the constructor a caller happened to use."""
    outline = ReferenceOutline.from_measurement(113_000_000, 60_000_000)
    with pytest.raises(ValueError):
        outline.resized(0, 61_000_000)
    with pytest.raises(ValueError):
        outline.resized(112_000_000, -61_000_000)


# --------------------------------------------------------------------------
# what ``raw`` holds
# --------------------------------------------------------------------------


def test_from_measurement_records_the_measurement_it_was_given():
    outline = ReferenceOutline.from_measurement(
        113_000_000, 60_000_000, centre_x_nm=297_600_000, centre_y_nm=421_000_000
    )
    assert (outline.raw.width_nm, outline.raw.height_nm) == (113_000_000, 60_000_000)
    assert (outline.width_nm, outline.height_nm) == (113_000_000, 60_000_000)
    assert (outline.centre_x_nm, outline.centre_y_nm) == (297_600_000, 421_000_000)


def test_a_plainly_constructed_outline_is_its_own_measurement():
    """Two-argument construction predates this field and must keep working.

    An outline nobody has snapped *is* as-measured, so ``raw`` mirroring its own
    dimensions is the truthful answer — and it means no call site has to decide
    whether provenance is known, which is what a ``None`` here would have cost.
    """
    outline = ReferenceOutline(113_000_000, 60_000_000)
    assert outline.raw == RawOutline(113_000_000, 60_000_000)


def test_an_explicit_raw_is_never_replaced_by_the_nominal_values():
    outline = ReferenceOutline(
        112_000_000, 61_000_000, raw=RawOutline(113_000_000, 60_000_000)
    )
    assert (outline.raw.width_nm, outline.raw.height_nm) == (113_000_000, 60_000_000)


def test_raw_is_never_none():
    """The field exists to remove an ambiguity; ``None`` would reintroduce it."""
    assert ReferenceOutline(113_000_000, 60_000_000).raw is not None
    assert ReferenceOutline.from_measurement(113_000_000, 60_000_000).raw is not None


# --------------------------------------------------------------------------
# value-object mechanics, the same as RawHole's
# --------------------------------------------------------------------------


def test_raw_outline_is_frozen_and_slotted():
    raw = RawOutline(113_000_000, 60_000_000)
    with pytest.raises(dataclasses.FrozenInstanceError):
        raw.width_nm = 112_000_000  # type: ignore[misc]
    assert not hasattr(raw, "__dict__")


def test_raw_outline_compares_by_value():
    assert RawOutline(113_000_000, 60_000_000) == RawOutline(113_000_000, 60_000_000)
    assert RawOutline(113_000_000, 60_000_000) != RawOutline(60_000_000, 113_000_000)


def test_outlines_differing_only_in_provenance_are_not_equal():
    """A snapped 112 × 61 and a measured one describe different panels.

    This is the only test pinning ``raw`` into equality, and it has to be:
    the JSON round-trip test can only notice a dropped measurement once its
    own fixture carries a snapped outline, because an unsnapped one rebuilds
    its ``raw`` from the nominal values and compares equal either way.
    """
    measured = ReferenceOutline.from_measurement(112_000_000, 61_000_000)
    snapped = ReferenceOutline.from_measurement(113_000_000, 60_000_000).resized(
        112_000_000, 61_000_000
    )
    assert measured != snapped


# --------------------------------------------------------------------------
# the guard that was already there
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width_nm,height_nm",
    [
        (0, 60_000_000),
        (113_000_000, 0),
        (-113_000_000, 60_000_000),
        (113_000_000, -60_000_000),
    ],
)
def test_a_non_positive_outline_is_refused(width_nm, height_nm):
    with pytest.raises(ValueError):
        ReferenceOutline(width_nm, height_nm)


def test_from_measurement_refuses_a_non_positive_outline():
    with pytest.raises(ValueError):
        ReferenceOutline.from_measurement(0, 60_000_000)


# --------------------------------------------------------------------------
# EnclosureMatch: a footprint, never a part
# --------------------------------------------------------------------------

#: The 120 × 94 footprint. Four Hammond parts share it — they differ only in
#: height, which a 2-D outline cannot see. Chosen as the fixture because its
#: length and width differ, so nothing here passes by coincidence.
_1590BB_FOOTPRINT = EnclosureMatch(
    family="Hammond 1590",
    length_nm=120_000_000,
    width_nm=94_000_000,
    candidates=("1590BB", "1590BB2", "1590BBS", "1590C"),
)


def test_a_match_records_the_catalogue_length_and_width():
    """Kept as given — this fixture is keyword-built, so it pins storage only.

    The *order* of the two declarations is a separate claim, and the positional
    test below is the one that earns it.
    """
    assert _1590BB_FOOTPRINT.length_nm == 120_000_000
    assert _1590BB_FOOTPRINT.width_nm == 94_000_000


def test_the_field_order_is_family_length_width_candidates():
    """Pinned positionally, because the stage and the emitters agreed on it.

    Length before width is the datasheet's own column order. Swapping the two
    declarations would keep every keyword call site working and quietly
    transpose every positional one.
    """
    positional = EnclosureMatch(
        "Hammond 1590", 120_000_000, 94_000_000, ("1590BB", "1590BB2")
    )
    assert positional.family == "Hammond 1590"
    assert positional.length_nm == 120_000_000
    assert positional.width_nm == 94_000_000
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
        length_nm=145_000_000,
        width_nm=95_000_000,
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

    A panel declared as one case and drawn to another is a real operator error,
    and it has to reach the diagnostics as ``wrong-enclosure`` with both names in
    it. An exception in the value type would instead abort the run with no
    finding to render.
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
    assert (portrait.length_nm, portrait.width_nm) == (120_000_000, 94_000_000)


def test_candidates_given_as_a_list_are_stored_as_a_tuple():
    """The same coercion ``StageRun`` and ``Diagnostic`` do, for the same reason.

    A match holding a list is unhashable and compares unequal to the identical
    match built from a tuple, so a document read back from JSON — where every
    sequence arrives as a list — would differ from the one it was written from
    while printing identically.
    """
    from_list = EnclosureMatch(
        family="Hammond 1590",
        length_nm=120_000_000,
        width_nm=94_000_000,
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
        length_nm=120_000_000,
        width_nm=94_000_000,
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
            length_nm=120_000_000,
            width_nm=94_000_000,
            candidates="1590BB",  # type: ignore[arg-type]
        )


def test_a_single_candidate_must_still_be_given_as_a_sequence():
    """The guard's real target: one designator is where the mistake is tempting."""
    with pytest.raises(TypeError):
        EnclosureMatch("Hammond 1590", 145_000_000, 95_000_000, "1590DD")  # type: ignore[arg-type]
    assert EnclosureMatch(
        "Hammond 1590", 145_000_000, 95_000_000, ("1590DD",)
    ).candidates == ("1590DD",)


def test_enclosure_match_is_frozen_and_slotted():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _1590BB_FOOTPRINT.selected_part = "1590C"  # type: ignore[misc]
    assert not hasattr(_1590BB_FOOTPRINT, "__dict__")


def test_matches_differing_only_in_the_declared_part_are_not_equal():
    """A declared 1590C and an undeclared footprint describe different panels."""
    assert dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590C") != _1590BB_FOOTPRINT


def test_a_transposed_match_is_not_the_same_match():
    transposed = dataclasses.replace(
        _1590BB_FOOTPRINT, length_nm=94_000_000, width_nm=120_000_000
    )
    assert transposed != _1590BB_FOOTPRINT


# --------------------------------------------------------------------------
# DrillData carries the match as domain state
# --------------------------------------------------------------------------


def test_drill_data_starts_with_no_enclosure():
    """Absent, not guessed. No stage has looked at the outline yet."""
    assert DrillData().enclosure is None


def test_an_outline_alone_does_not_identify_an_enclosure():
    """Only the stage sets this. A ``ReferenceOutline`` is a size, not a match."""
    data = DrillData(reference=ReferenceOutline.from_measurement(120_000_000, 94_000_000))
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
        holes=(Hole.from_measurement(7_000_000, -3_000_000, 12_000_000, index=4),),
        reference=ReferenceOutline.from_measurement(113_000_000, 60_000_000),
        diagnostics=(Diagnostic.warning("off-grid", "hole 4 is off grid"),),
        source=SourceInfo(path="tar.ai"),
        processing=(StageRun("snap", (("grid_nm", 500_000),)),),
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
        length_nm=112_000_000,
        width_nm=61_000_000,
        candidates=("1590B", "1590B2", "1590BS"),
    )
    second = first.with_enclosure(second_match)
    assert second.enclosure is second_match


def test_the_enclosure_survives_the_other_transforms():
    """Every transform returns a new instance, and none of them may drop it."""
    data = DrillData(
        reference=ReferenceOutline.from_measurement(120_000_000, 94_000_000)
    ).with_enclosure(_1590BB_FOOTPRINT)
    holes = [Hole.from_measurement(7_000_000, -3_000_000, 12_000_000, index=4)]
    assert data.with_holes(holes).enclosure is _1590BB_FOOTPRINT
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
# moving the frame
# --------------------------------------------------------------------------


def test_a_lower_left_origin_shifts_every_hole_by_half_the_outline():
    """The one frame change the model performs, so no emitter hand-rolls it.

    A whole-millimetre outline is an even number of nanometres, so the half is
    exact — which is the arithmetic every catalogue footprint gives.
    """
    data = DrillData(
        holes=(
            Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=4),
            Hole.from_measurement(0, 0, 12_000_000, index=2),
        ),
        reference=ReferenceOutline.from_measurement(112_000_000, 61_000_000),
    )

    shifted = data.with_origin(Origin.LOWER_LEFT)

    assert [(h.x_nm, h.y_nm) for h in shifted.holes] == [
        (16_000_000, 48_500_000),
        (56_000_000, 30_500_000),
    ]
    assert all(type(h.x_nm) is int and type(h.y_nm) is int for h in shifted.holes)


def test_an_odd_outline_still_yields_whole_nanometres():
    """An outline of an odd number of nanometres has no exact half, and the
    shift floors rather than producing the first float in the model."""
    data = DrillData(
        holes=(Hole.from_measurement(0, 0, 7_000_000, index=3),),
        reference=ReferenceOutline.from_measurement(112_000_001, 61_000_003),
    )

    (hole,) = data.with_origin(Origin.LOWER_LEFT).holes

    assert (hole.x_nm, hole.y_nm) == (56_000_000, 30_500_001)


def test_the_centre_origin_is_the_frame_the_holes_are_already_in():
    data = DrillData(
        holes=(Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=4),),
        reference=ReferenceOutline.from_measurement(112_000_000, 61_000_000),
    )
    assert data.with_origin(Origin.CENTRE) is data


def test_a_lower_left_origin_without_an_outline_refuses_to_guess():
    """There is no defensible answer without knowing where the corner is."""
    data = DrillData(holes=(Hole.from_measurement(0, 0, 7_000_000, index=3),))
    with pytest.raises(ValueError):
        data.with_origin(Origin.LOWER_LEFT)


# --------------------------------------------------------------------------
# the tool table, which both artifacts read
# --------------------------------------------------------------------------


def test_tools_number_the_distinct_diameters_ascending():
    """One numbering, on the model, so the drill file's tool table and the
    drawing's hole schedule cannot disagree about how many bits a panel needs."""
    data = DrillData(
        holes=(
            Hole.from_measurement(0, 0, 12_000_000, index=4),
            Hole.from_measurement(10_000_000, 0, 7_000_000, index=1),
            Hole.from_measurement(20_000_000, 0, 12_000_000, index=7),
        )
    )
    assert data.tools() == {7_000_000: 1, 12_000_000: 2}
    assert data.tool_counts() == {7_000_000: 1, 12_000_000: 2}


def test_two_diameters_a_nanometre_apart_are_two_tools():
    """Distinctness is exact equality, and in nanometres that is a real
    question with an exact answer: nothing here clusters."""
    data = DrillData(
        holes=(
            Hole.from_measurement(0, 0, 7_000_000, index=4),
            Hole.from_measurement(10_000_000, 0, 7_000_001, index=1),
        )
    )
    assert list(data.tools()) == [7_000_000, 7_000_001]


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
        Hole.from_measurement(0, -18_750_000, 5_000_000, index=7),
        Hole.from_measurement(0, 18_000_000, 7_000_000, index=2),
        Hole.from_measurement(0, 0, 3_000_000, index=5),
    )

    assert [y for y, _ in panel.rows()] == [18_000_000, 0, -18_750_000]


def test_a_row_runs_left_to_right():
    """Ascending X within the row. The holes are handed over in an order that is
    neither ascending nor descending, and named by ``index`` rather than by
    position, so neither a reversal nor "whatever order they arrived in" passes.
    """
    panel = row_panel(
        Hole.from_measurement(20_000_000, 18_000_000, 7_000_000, index=6),
        Hole.from_measurement(-40_000_000, 18_000_000, 7_000_000, index=2),
        Hole.from_measurement(0, 18_000_000, 7_000_000, index=9),
    )

    ((_, holes),) = panel.rows()

    assert [hole.index for hole in holes] == [2, 9, 6]
    assert [hole.x_nm for hole in holes] == [-40_000_000, 0, 20_000_000]


def test_two_holes_a_nanometre_apart_in_y_are_one_row():
    """Y comes off the artwork through a transform and a frame translation, so
    two holes the designer drew on one line can land a nanometre apart. The
    bucket absorbs exactly that — its own boundary, inclusive, which is the rule
    ``within`` states once for the whole pipeline."""
    panel = row_panel(
        Hole.from_measurement(-20_000_000, 18_000_000, 7_000_000, index=3),
        Hole.from_measurement(20_000_000, 18_000_001, 7_000_000, index=8),
    )

    rows = panel.rows()

    assert len(rows) == 1
    assert [hole.index for hole in rows[0][1]] == [3, 8]


def test_two_holes_two_nanometres_apart_are_two_rows():
    """One nanometre outside, so the width of the bucket is pinned rather than
    merely its order of magnitude."""
    panel = row_panel(
        Hole.from_measurement(-20_000_000, 18_000_000, 7_000_000, index=3),
        Hole.from_measurement(20_000_000, 18_000_002, 7_000_000, index=8),
    )

    assert [y for y, _ in panel.rows()] == [18_000_002, 18_000_000]


def test_two_holes_one_micron_apart_are_two_rows():
    """A micron is not a hair — it is a coordinate the drill file writes.

    Excellon at three decimal places prints 18.000 for one of these holes and
    18.001 for the other, so a bucket a micron wide would have the drawing
    dimension a single row while the machine drills two Y positions: one panel,
    two artifacts, silently disagreeing.
    """
    panel = row_panel(
        Hole.from_measurement(-20_000_000, 18_000_000, 7_000_000, index=3),
        Hole.from_measurement(20_000_000, 18_001_000, 7_000_000, index=8),
    )

    assert [y for y, _ in panel.rows()] == [18_001_000, 18_000_000]


def test_two_holes_half_a_millimetre_apart_are_two_rows():
    """The other side of the same boundary, at a distance a machinist can see.
    A bucket wide enough to swallow it would dimension two rows of holes as one.
    """
    panel = row_panel(
        Hole.from_measurement(-20_000_000, 18_000_000, 7_000_000, index=3),
        Hole.from_measurement(20_000_000, 17_500_000, 7_000_000, index=8),
    )

    assert [y for y, _ in panel.rows()] == [18_000_000, 17_500_000]
