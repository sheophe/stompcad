"""Tests for immutable model values, validation and processing provenance."""

from __future__ import annotations

import dataclasses

import pytest

from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.errors import EmitterError
from stompmodel.model import (
    DrillData,
    EnclosureMatch,
    Hole,
    Origin,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from stompmodel.units import Millimetre, Nanometre, mm_from_nm, nm_from_mm

# --------------------------------------------------------------------------
# every length is a whole number of nanometres
# --------------------------------------------------------------------------


def test_every_nominal_length_on_a_hole_is_an_integer() -> None:
    """``type(...) is int``, not ``isinstance``."""
    hole = Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4)
    for value in (hole.x_nm, hole.y_nm, hole.diameter_nm):
        assert type(value) is int


def test_every_measured_length_on_a_hole_is_a_float_millimetre() -> None:
    """Every measured length on a hole is a float millimetre."""
    hole = Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4)
    for value in (hole.raw.x, hole.raw.y, hole.raw.diameter):
        assert type(value) is float
    assert (hole.raw.x, hole.raw.y, hole.raw.diameter) == (-40.0, 18.0, 7.0)


#: A length that crossed no unit boundary: it is the shape of 7 mm and it is not
#: an integer, which is the whole of what makes it inadmissible.
_A_FLOAT = 7_000_000.5

#: The mirror image, for the millimetre fields: a whole number of nanometres,
#: which is exactly the value that reaches a millimetre field by never having
#: been converted at all.
_A_NANOMETRE_INT = 7_000_000

#: Valid provenance to hand a constructor whose guard is not the one under test.
#: ``ReferenceOutline`` needs it explicitly: left to default, the sentinel path
#: builds a ``RawOutline`` out of the very values being tested and *that* guard
#: raises, so the outline's own guard could be deleted and the test would still
#: pass on someone else's work.
_VALID_RAW_HOLE = RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(7.0))
_VALID_RAW_OUTLINE = RawOutline(Millimetre(113.0), Millimetre(60.0))

#: Every ``(owner, field)`` pair the model guards as whole nanometres, one
#: builder each, named by the pair so a failure says which guard went missing.
#:
#: Enumerated exhaustively and one field at a time because the guards are a
#: folded condition: they are separate keyword arguments to one helper, the
#: helper is strict, and a *call* that quietly stops naming a field is invisible
#: from anywhere else. ``Hole.y_nm`` and both of ``ReferenceOutline``'s Y-axis
#: lengths could each be dropped from their call with the whole suite staying
#: green. Proving the X axis proves nothing about the Y.
_GUARDED_LENGTHS = [
    pytest.param(
        lambda v: Hole(v, Nanometre(0), Nanometre(7_000_000), _VALID_RAW_HOLE, 4),
        id="Hole.x_nm",
    ),
    pytest.param(
        lambda v: Hole(Nanometre(0), v, Nanometre(7_000_000), _VALID_RAW_HOLE, 4),
        id="Hole.y_nm",
    ),
    pytest.param(
        lambda v: Hole(Nanometre(0), Nanometre(0), v, _VALID_RAW_HOLE, 4),
        id="Hole.diameter_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(v, Nanometre(60_000_000), raw=_VALID_RAW_OUTLINE),
        id="ReferenceOutline.width_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(Nanometre(113_000_000), v, raw=_VALID_RAW_OUTLINE),
        id="ReferenceOutline.height_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(
            Nanometre(113_000_000), Nanometre(60_000_000), centre_x_nm=v, raw=_VALID_RAW_OUTLINE
        ),
        id="ReferenceOutline.centre_x_nm",
    ),
    pytest.param(
        lambda v: ReferenceOutline(
            Nanometre(113_000_000), Nanometre(60_000_000), centre_y_nm=v, raw=_VALID_RAW_OUTLINE
        ),
        id="ReferenceOutline.centre_y_nm",
    ),
    pytest.param(
        lambda v: EnclosureMatch("Hammond 1590", v, Nanometre(94_000_000), ("1590BB",)),
        id="EnclosureMatch.length_nm",
    ),
    pytest.param(
        lambda v: EnclosureMatch("Hammond 1590", Nanometre(120_000_000), v, ("1590BB",)),
        id="EnclosureMatch.width_nm",
    ),
]


@pytest.mark.parametrize("build", _GUARDED_LENGTHS)
def test_a_float_is_not_a_length(build) -> None:
    """Refused at construction, where the offending value still has a call site."""
    with pytest.raises(TypeError, match="nanometres"):
        build(_A_FLOAT)


@pytest.mark.parametrize("build", _GUARDED_LENGTHS)
def test_a_bool_is_not_a_length(build) -> None:
    """A bool is not a length."""
    with pytest.raises(TypeError, match="nanometres"):
        build(True)


#: Every ``(owner, field)`` pair the model guards as float millimetres, listed
#: one field at a time for the same reason ``_GUARDED_LENGTHS`` is: the guard is
#: one strict helper taking separate keyword arguments, so a call that quietly
#: stops naming a field leaves that field unchecked and says nothing about it.
_GUARDED_MILLIMETRES = [
    pytest.param(lambda v: RawHole(v, Millimetre(0.0), Millimetre(7.0)), id="RawHole.x"),
    pytest.param(lambda v: RawHole(Millimetre(0.0), v, Millimetre(7.0)), id="RawHole.y"),
    pytest.param(lambda v: RawHole(Millimetre(0.0), Millimetre(0.0), v), id="RawHole.diameter"),
    pytest.param(lambda v: RawOutline(v, Millimetre(60.0)), id="RawOutline.width"),
    pytest.param(lambda v: RawOutline(Millimetre(113.0), v), id="RawOutline.height"),
]


def test_a_nanometre_integer_in_a_millimetre_field_would_print_as_forty_million() -> None:
    """Why the millimetre guard exists, stated as the sheet it keeps clean."""
    x_nm = nm_from_mm(40.0)
    assert f"{x_nm:.3f}" == "40000000.000"
    assert f"{mm_from_nm(x_nm):.3f}" == "40.000"

    with pytest.raises(TypeError, match="millimetres"):
        RawHole(x_nm, Millimetre(0.0), Millimetre(7.0))  # type: ignore[arg-type]


@pytest.mark.parametrize("build", _GUARDED_MILLIMETRES)
def test_an_integer_is_not_a_measurement(build) -> None:
    """``type(v) is float``, and an ``int`` is what it is there to refuse."""
    with pytest.raises(TypeError, match="millimetres"):
        build(_A_NANOMETRE_INT)


@pytest.mark.parametrize("build", _GUARDED_MILLIMETRES)
def test_a_bool_is_not_a_measurement(build) -> None:
    """A bool is not a float measurement despite being an ``int`` subclass."""
    with pytest.raises(TypeError, match="millimetres"):
        build(True)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
@pytest.mark.parametrize("build", _GUARDED_MILLIMETRES)
def test_a_measurement_that_is_not_finite_is_refused(build, value) -> None:
    """A NaN is a ``float`` and would sail through a type check alone."""
    with pytest.raises(TypeError, match="millimetres"):
        build(value)


def test_translation_is_exact_however_many_times_it_is_applied() -> None:
    """The property integers buy and floating point does not."""
    hole = Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4)

    stepped = hole
    for _ in range(1000):
        stepped = stepped.translated(Nanometre(1), Nanometre(0))

    assert stepped.x_nm == hole.translated(Nanometre(1_000), Nanometre(0)).x_nm
    assert stepped.translated(Nanometre(-1_000), Nanometre(0)).x_nm == hole.x_nm

    walked = stepped
    for _ in range(1000):
        walked = walked.translated(Nanometre(-1), Nanometre(0))
    assert walked.x_nm == hole.x_nm


def test_a_translated_hole_keeps_its_identity_and_its_measurement() -> None:
    """``translated`` moves the nominal position and nothing else. Rebuilding
    the hole would renumber it and overwrite what the artwork measured."""
    hole = Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4)
    moved = hole.translated(Nanometre(56_000_000), Nanometre(30_500_000))
    assert (moved.x_nm, moved.y_nm) == (16_000_000, 48_500_000)
    assert moved.index == 4
    assert moved.raw == RawHole(Millimetre(-40.0), Millimetre(18.0), Millimetre(7.0))


@pytest.mark.parametrize("value", [_A_FLOAT, True], ids=["float", "bool"])
@pytest.mark.parametrize(
    "translate",
    [
        pytest.param(lambda hole, v: hole.translated(v, Nanometre(0)), id="dx_nm"),
        pytest.param(lambda hole, v: hole.translated(Nanometre(0), v), id="dy_nm"),
    ],
)
def test_a_translation_that_is_not_a_length_is_refused(translate, value) -> None:
    """The *parameter* is guarded, not only the field it lands in."""
    hole = Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4)
    with pytest.raises(TypeError, match="nanometres"):
        translate(hole, value)


def test_an_unrouted_hole_has_no_number() -> None:
    hole = Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000))
    assert hole.index is None


@pytest.mark.parametrize("index", [0, -1], ids=["zero", "negative"])
def test_a_hole_numbered_below_one_is_refused(index) -> None:
    """``index`` is printed as it stands, so the model holds the floor itself.

    Numbering at the source alone would leave the guarantee resting on one
    source class; a library caller assembling holes reaches the same emitters.
    """
    with pytest.raises(ValueError, match="numbered from 1"):
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(index)


def test_zero_is_still_refused_even_though_none_is_allowed() -> None:
    """Both halves: a guard that allowed ``None`` by allowing everything would
    pass a test that only checked ``None``."""
    with pytest.raises(ValueError, match="numbered from 1"):
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(0)


def test_the_lowest_hole_number_the_model_accepts_is_one() -> None:
    """The other side of the floor: 1 is legal, so the guard is a floor and
    not a blanket refusal that a passing rejection test could not tell apart."""
    hole = Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(1)
    assert hole.index == 1


def test_numbered_refuses_data_that_was_never_routed() -> None:
    data = DrillData(holes=(
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
    ))
    with pytest.raises(EmitterError, match="no drill number"):
        data.numbered()


def test_the_refusal_names_the_remedy_without_naming_a_class() -> None:
    """A library caller reaches this, and a diagnosis it cannot act on is half
    a message. ``stompmodel`` cannot name ``RouteHoles``, so it names the role."""
    data = DrillData(holes=(
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)),
    ))
    with pytest.raises(EmitterError, match="compose a routing stage before emitting"):
        data.numbered()


def test_the_residual_is_the_nominal_position_less_the_measured_one() -> None:
    """Positive means the nominal value is the larger, in nanometres. Named
    ``residual_nm`` because it is three lengths, and a caller printing it as
    millimetres would be three decimal places out with nothing to notice."""
    hole = Hole.from_measurement(Nanometre(-39_990_600), Nanometre(18_000_400), Nanometre(6_800_000)).with_number(4)
    snapped = hole.moved_to(Nanometre(-40_000_000), Nanometre(18_000_000)).with_diameter(Nanometre(7_000_000))
    assert snapped.residual_nm == (-9_400, -400, 200_000)


def test_the_residual_quantises_the_measurement_rather_than_reporting_millimetres() -> None:
    """Nominal is nanometres and raw is millimetres, so the subtraction crosses a unit —
    and the answer stays on the nominal side of it.
    """
    hole = Hole(
        x_nm=Nanometre(-40_000_000),
        y_nm=Nanometre(18_000_000),
        diameter_nm=Nanometre(7_000_000),
        raw=RawHole(Millimetre(-39.9906), Millimetre(18.0004), Millimetre(6.8)),
        index=4,
    )
    assert hole.residual_nm == (-9_400, -400, 200_000)
    for value in hole.residual_nm:
        assert type(value) is int


# --------------------------------------------------------------------------
# provenance survives a resize
# --------------------------------------------------------------------------


def test_snapping_the_outline_does_not_destroy_what_was_measured() -> None:
    outline = ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000))
    snapped = outline.resized(Nanometre(112_000_000), Nanometre(61_000_000))
    assert (snapped.width_nm, snapped.height_nm) == (112_000_000, 61_000_000)
    assert (snapped.raw.width, snapped.raw.height) == (113.0, 60.0)


def test_resizing_twice_still_reports_the_original_measurement() -> None:
    """Provenance is the *measurement*, not the previous nominal value.

    Carrying forward "what it was before this resize" would look identical
    after one snap and be wrong after two — and nothing forbids a second one.
    """
    outline = ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000))
    twice = outline.resized(Nanometre(112_000_000), Nanometre(61_000_000)).resized(Nanometre(120_000_000), Nanometre(94_000_000))
    assert (twice.width_nm, twice.height_nm) == (120_000_000, 94_000_000)
    assert (twice.raw.width, twice.raw.height) == (113.0, 60.0)


def test_resizing_returns_a_new_outline_and_leaves_the_original_alone() -> None:
    outline = ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000))
    snapped = outline.resized(Nanometre(112_000_000), Nanometre(61_000_000))
    assert snapped is not outline
    assert (outline.width_nm, outline.height_nm) == (113_000_000, 60_000_000)
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)


def test_resizing_keeps_the_source_space_centre() -> None:
    """The snap changes the size, not where the outline was found on the page."""
    outline = ReferenceOutline.from_measurement(
        Nanometre(113_000_000), Nanometre(60_000_000), centre_x_nm=Nanometre(297_600_000), centre_y_nm=Nanometre(421_000_000)
    )
    snapped = outline.resized(Nanometre(112_000_000), Nanometre(61_000_000))
    assert (snapped.centre_x_nm, snapped.centre_y_nm) == (297_600_000, 421_000_000)


def test_resizing_still_refuses_a_non_positive_size() -> None:
    """The guard is on the value, not on the constructor a caller happened to use."""
    outline = ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000))
    with pytest.raises(ValueError):
        outline.resized(Nanometre(0), Nanometre(61_000_000))
    with pytest.raises(ValueError):
        outline.resized(Nanometre(112_000_000), Nanometre(-61_000_000))


# --------------------------------------------------------------------------
# what ``raw`` holds
# --------------------------------------------------------------------------


def test_from_measurement_records_the_measurement_it_was_given() -> None:
    outline = ReferenceOutline.from_measurement(
        Nanometre(113_000_000), Nanometre(60_000_000), centre_x_nm=Nanometre(297_600_000), centre_y_nm=Nanometre(421_000_000)
    )
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)
    assert (outline.width_nm, outline.height_nm) == (113_000_000, 60_000_000)
    assert (outline.centre_x_nm, outline.centre_y_nm) == (297_600_000, 421_000_000)


def test_a_plainly_constructed_outline_is_its_own_measurement() -> None:
    """Two-argument construction uses the nominal size as its measurement."""
    outline = ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000))
    assert outline.raw == RawOutline(Millimetre(113.0), Millimetre(60.0))


def test_an_explicit_raw_is_never_replaced_by_the_nominal_values() -> None:
    outline = ReferenceOutline(Nanometre(112_000_000), Nanometre(61_000_000), raw=RawOutline(Millimetre(113.0), Millimetre(60.0)))
    assert (outline.raw.width, outline.raw.height) == (113.0, 60.0)


def test_a_caller_who_really_measured_nothing_gets_that_measurement_back() -> None:
    """The sentinel is tested by identity, and this is what that buys."""
    outline = ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000), raw=RawOutline(Millimetre(0.0), Millimetre(0.0)))
    assert (outline.raw.width, outline.raw.height) == (0.0, 0.0)


def test_raw_is_never_none() -> None:
    """The field exists to remove an ambiguity; ``None`` would reintroduce it."""
    assert ReferenceOutline(Nanometre(113_000_000), Nanometre(60_000_000)).raw is not None
    assert ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000)).raw is not None


# --------------------------------------------------------------------------
# value-object mechanics, the same as RawHole's
# --------------------------------------------------------------------------


def test_raw_outline_is_frozen_and_slotted() -> None:
    raw = RawOutline(Millimetre(113.0), Millimetre(60.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        raw.width = 112.0  # type: ignore[misc,assignment]
    assert not hasattr(raw, "__dict__")


def test_raw_outline_compares_by_value() -> None:
    assert RawOutline(Millimetre(113.0), Millimetre(60.0)) == RawOutline(Millimetre(113.0), Millimetre(60.0))
    assert RawOutline(Millimetre(113.0), Millimetre(60.0)) != RawOutline(Millimetre(60.0), Millimetre(113.0))


def test_outlines_differing_only_in_provenance_are_not_equal() -> None:
    """A snapped 112 × 61 and a measured one describe different panels."""
    measured = ReferenceOutline.from_measurement(Nanometre(112_000_000), Nanometre(61_000_000))
    snapped = ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000)).resized(
        Nanometre(112_000_000), Nanometre(61_000_000)
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
def test_a_non_positive_outline_is_refused(width_nm, height_nm) -> None:
    with pytest.raises(ValueError):
        ReferenceOutline(width_nm, height_nm)


def test_from_measurement_refuses_a_non_positive_outline() -> None:
    with pytest.raises(ValueError):
        ReferenceOutline.from_measurement(Nanometre(0), Nanometre(60_000_000))


# --------------------------------------------------------------------------
# EnclosureMatch: a footprint, never a part
# --------------------------------------------------------------------------

#: The 120 × 94 footprint. Four Hammond parts share it — they differ only in
#: height, which a 2-D outline cannot see. Chosen as the fixture because its
#: length and width differ, so nothing here passes by coincidence.
_1590BB_FOOTPRINT = EnclosureMatch(
    family="Hammond 1590",
    length_nm=Nanometre(120_000_000),
    width_nm=Nanometre(94_000_000),
    candidates=("1590BB", "1590BB2", "1590BBS", "1590C"),
)


def test_a_match_records_the_catalogue_length_and_width() -> None:
    """Keyword construction preserves catalogue length and width independently."""
    assert _1590BB_FOOTPRINT.length_nm == 120_000_000
    assert _1590BB_FOOTPRINT.width_nm == 94_000_000


def test_the_field_order_is_family_length_width_candidates() -> None:
    """Positional construction orders family, dimensions and candidates."""
    positional = EnclosureMatch(
        "Hammond 1590", Nanometre(120_000_000), Nanometre(94_000_000), ("1590BB", "1590BB2")
    )
    assert positional.family == "Hammond 1590"
    assert positional.length_nm == 120_000_000
    assert positional.width_nm == 94_000_000
    assert positional.candidates == ("1590BB", "1590BB2")


def test_a_match_names_every_part_that_shares_the_footprint() -> None:
    """All four, not one: the outline cannot tell them apart, and neither may we."""
    assert _1590BB_FOOTPRINT.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_match_selects_no_part_of_its_own_accord() -> None:
    """``selected_part`` is operator knowledge. Geometry never supplies it.

    Defaulting to anything else — the sole candidate, the first one, the family
    name — would let a drawing print a part number the artwork never stated.
    """
    assert _1590BB_FOOTPRINT.selected_part is None


def test_a_single_candidate_footprint_still_selects_nothing() -> None:
    """Even where only one part shares the footprint, the artwork did not say so.

    A default of "the only candidate" would be right here and silently wrong on
    every shared footprint, which is most of the catalogue.
    """
    lone = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(145_000_000),
        width_nm=Nanometre(95_000_000),
        candidates=("1590DD",),
    )
    assert lone.selected_part is None


def test_an_operator_may_declare_the_part_without_narrowing_the_candidates() -> None:
    """The declaration is recorded beside the footprint, not folded into it.

    Overwriting ``candidates`` would destroy what the geometry actually
    established, leaving nothing to check a later declaration against.
    """
    declared = dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590C")
    assert declared.selected_part == "1590C"
    assert declared.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_declared_part_outside_the_candidates_is_not_the_models_business() -> None:
    """Constructing this must not raise: refusing it here would pre-empt the stage."""
    mismatched = dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590A")
    assert mismatched.selected_part == "1590A"
    assert mismatched.candidates == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_a_match_is_not_rotated_unless_it_says_so() -> None:
    assert _1590BB_FOOTPRINT.rotated is False


def test_a_rotated_match_still_reports_the_catalogue_orientation() -> None:
    """``rotated`` describes the artwork, not a second, transposed footprint."""
    portrait = dataclasses.replace(_1590BB_FOOTPRINT, rotated=True)
    assert portrait.rotated is True
    assert (portrait.length_nm, portrait.width_nm) == (120_000_000, 94_000_000)


def test_candidates_given_as_a_list_are_stored_as_a_tuple() -> None:
    """Candidates given as a list are stored as a tuple."""
    from_list = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(120_000_000),
        width_nm=Nanometre(94_000_000),
        candidates=["1590BB", "1590BB2", "1590BBS", "1590C"],  # type: ignore[arg-type]
    )
    assert isinstance(from_list.candidates, tuple)
    assert from_list == _1590BB_FOOTPRINT
    assert hash(from_list) == hash(_1590BB_FOOTPRINT)


def test_the_coercion_keeps_the_order_it_was_given() -> None:
    """Catalogue order is the caller's to choose; nothing here re-sorts it."""
    unsorted = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(120_000_000),
        width_nm=Nanometre(94_000_000),
        candidates=("1590C", "1590BB", "1590BBS", "1590BB2"),
    )
    assert unsorted.candidates == ("1590C", "1590BB", "1590BBS", "1590BB2")


def test_a_bare_string_of_candidates_is_refused() -> None:
    """``tuple("1590B")`` is five candidates, and every one of them type-checks."""
    with pytest.raises(TypeError):
        EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(120_000_000),
            width_nm=Nanometre(94_000_000),
            candidates="1590BB",  # type: ignore[arg-type]
        )


def test_a_single_candidate_must_still_be_given_as_a_sequence() -> None:
    """The guard's real target: one designator is where the mistake is tempting."""
    with pytest.raises(TypeError):
        EnclosureMatch(
            "Hammond 1590",
            Nanometre(145_000_000),
            Nanometre(95_000_000),
            "1590DD",  # type: ignore[arg-type]
        )
    assert EnclosureMatch(
        "Hammond 1590", Nanometre(145_000_000), Nanometre(95_000_000), ("1590DD",)
    ).candidates == ("1590DD",)


def test_enclosure_match_is_frozen_and_slotted() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _1590BB_FOOTPRINT.selected_part = "1590C"  # type: ignore[misc]
    assert not hasattr(_1590BB_FOOTPRINT, "__dict__")


def test_matches_differing_only_in_the_declared_part_are_not_equal() -> None:
    """A declared 1590C and an undeclared footprint describe different panels."""
    assert dataclasses.replace(_1590BB_FOOTPRINT, selected_part="1590C") != _1590BB_FOOTPRINT


def test_a_transposed_match_is_not_the_same_match() -> None:
    transposed = dataclasses.replace(
        _1590BB_FOOTPRINT, length_nm=Nanometre(94_000_000), width_nm=Nanometre(120_000_000)
    )
    assert transposed != _1590BB_FOOTPRINT


# --------------------------------------------------------------------------
# DrillData carries the match as domain state
# --------------------------------------------------------------------------


def test_drill_data_starts_with_no_enclosure() -> None:
    """Absent, not guessed. No stage has looked at the outline yet."""
    assert DrillData().enclosure is None


def test_an_outline_alone_does_not_identify_an_enclosure() -> None:
    """Only the stage sets this. A ``ReferenceOutline`` is a size, not a match."""
    data = DrillData(reference=ReferenceOutline.from_measurement(Nanometre(120_000_000), Nanometre(94_000_000)))
    assert data.enclosure is None


def test_with_enclosure_returns_a_new_instance_and_leaves_the_original_alone() -> None:
    data = DrillData()
    identified = data.with_enclosure(_1590BB_FOOTPRINT)
    assert identified is not data
    assert identified.enclosure is _1590BB_FOOTPRINT
    assert data.enclosure is None


def test_with_enclosure_keeps_everything_else_the_pipeline_has_accumulated() -> None:
    """Guards the ``replace``: rebuilding a ``DrillData`` around the match would
    silently discard the holes, the findings and the stage history."""
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(7_000_000), Nanometre(-3_000_000), Nanometre(12_000_000)).with_number(4),),
        reference=ReferenceOutline.from_measurement(Nanometre(113_000_000), Nanometre(60_000_000)),
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


def test_a_second_identification_replaces_the_first_rather_than_accumulating() -> None:
    """The enclosure is current state, not history — unlike ``processing``.

    A consumer asks "which enclosure is this?" and must get one answer. Only the
    audit log records that a stage ran twice.
    """
    first = DrillData().with_enclosure(_1590BB_FOOTPRINT)
    second_match = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(112_000_000),
        width_nm=Nanometre(61_000_000),
        candidates=("1590B", "1590B2", "1590BS"),
    )
    second = first.with_enclosure(second_match)
    assert second.enclosure is second_match


def test_the_enclosure_survives_the_other_transforms() -> None:
    """Every transform returns a new instance, and none of them may drop it."""
    data = DrillData(
        reference=ReferenceOutline.from_measurement(Nanometre(120_000_000), Nanometre(94_000_000))
    ).with_enclosure(_1590BB_FOOTPRINT)
    holes = [Hole.from_measurement(Nanometre(7_000_000), Nanometre(-3_000_000), Nanometre(12_000_000)).with_number(4)]
    assert data.with_holes(holes).enclosure is _1590BB_FOOTPRINT
    assert data.with_diagnostics(Diagnostic.info("note", "something")).enclosure is (
        _1590BB_FOOTPRINT
    )
    assert data.with_processing(StageRun("snap")).enclosure is _1590BB_FOOTPRINT


# --------------------------------------------------------------------------
# moving the frame
# --------------------------------------------------------------------------


def test_a_lower_left_origin_shifts_every_hole_by_half_the_outline() -> None:
    """The one frame change the model performs, so no emitter hand-rolls it.

    A whole-millimetre outline is an even number of nanometres, so the half is
    exact — which is the arithmetic every catalogue footprint gives.
    """
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(12_000_000)).with_number(2),
        ),
        reference=ReferenceOutline.from_measurement(Nanometre(112_000_000), Nanometre(61_000_000)),
    )

    shifted = data.with_origin(Origin.LOWER_LEFT)

    assert [(h.x_nm, h.y_nm) for h in shifted.holes] == [
        (16_000_000, 48_500_000),
        (56_000_000, 30_500_000),
    ]
    assert all(type(h.x_nm) is int for h in shifted.holes), "a shifted x is not a plain int"
    assert all(type(h.y_nm) is int for h in shifted.holes), "a shifted y is not a plain int"


def test_an_odd_outline_still_yields_whole_nanometres() -> None:
    """An outline of an odd number of nanometres has no exact half, and the
    shift floors rather than producing the first float in the model."""
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(3),),
        reference=ReferenceOutline.from_measurement(Nanometre(112_000_001), Nanometre(61_000_003)),
    )

    (hole,) = data.with_origin(Origin.LOWER_LEFT).holes

    assert (hole.x_nm, hole.y_nm) == (56_000_000, 30_500_001)


def test_the_centre_origin_is_the_frame_the_holes_are_already_in() -> None:
    data = DrillData(
        holes=(Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(4),),
        reference=ReferenceOutline.from_measurement(Nanometre(112_000_000), Nanometre(61_000_000)),
    )
    assert data.with_origin(Origin.CENTRE) is data


def test_a_lower_left_origin_without_an_outline_refuses_to_guess() -> None:
    """There is no defensible answer without knowing where the corner is."""
    data = DrillData(holes=(Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(3),))
    with pytest.raises(ValueError):
        data.with_origin(Origin.LOWER_LEFT)


# --------------------------------------------------------------------------
# the tool table, which both artifacts read
# --------------------------------------------------------------------------


def test_tools_number_the_distinct_diameters_ascending() -> None:
    """One numbering, on the model, so the drill file's tool table and the
    drawing's hole schedule cannot disagree about how many bits a panel needs."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(12_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(10_000_000), Nanometre(0), Nanometre(7_000_000)).with_number(1),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(0), Nanometre(12_000_000)).with_number(7),
        )
    )
    assert data.tools() == {7_000_000: 1, 12_000_000: 2}
    assert data.tool_counts() == {7_000_000: 1, 12_000_000: 2}


def test_two_diameters_a_nanometre_apart_are_two_tools() -> None:
    """Distinctness is exact equality, and in nanometres that is a real
    question with an exact answer: nothing here clusters."""
    data = DrillData(
        holes=(
            Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(4),
            Hole.from_measurement(Nanometre(10_000_000), Nanometre(0), Nanometre(7_000_001)).with_number(1),
        )
    )
    assert list(data.tools()) == [7_000_000, 7_000_001]


def test_numbered_pairs_each_hole_with_its_own_number_in_emission_order() -> None:
    """Not with its position: the two agree only after routing, and the
    accessor must read the model rather than recount the tuple."""
    data = DrillData(holes=(
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(7_000_000)).with_number(2),
        Hole.from_measurement(Nanometre(1_000_000), Nanometre(0), Nanometre(7_000_000)).with_number(1),
    ))
    assert [n for n, _ in data.numbered()] == [2, 1]
    assert [h.x_nm for _, h in data.numbered()] == [0, 1_000_000]


# --------------------------------------------------------------------------
# selecting findings by severity
# --------------------------------------------------------------------------


def four_findings() -> DrillData:
    """One ERROR, one INFO and two WARNINGs, in an order no grouping produces."""
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
def test_of_severity_selects_that_severity_and_nothing_else(severity, codes) -> None:
    """Matched on ``code``, and asserted whole: which findings came back, in
    which order, and that every one of them really is the severity asked for."""
    found = four_findings().of_severity(severity)

    assert [diagnostic.code for diagnostic in found] == codes
    assert {diagnostic.severity for diagnostic in found} == {severity}


def test_the_three_severities_partition_the_findings() -> None:
    """Every diagnostic appears under exactly one severity, and none is lost."""
    data = four_findings()
    selected = [
        diagnostic
        for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO)
        for diagnostic in data.of_severity(severity)
    ]

    assert len(selected) == len(data.diagnostics)
    assert set(selected) == set(data.diagnostics)


# --------------------------------------------------------------------------
# what a stage record may hold
#
# The ``Diagnostic``-only cases of this shared guard, and the pure ``Severity``
# tests, moved to ``stompmodel/tests/test_diagnostics.py`` with ``Diagnostic``
# and ``Severity`` themselves. ``StageRun`` stays here, and still proves the
# guard it imports from ``stompmodel.diagnostics`` by using it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [_A_FLOAT, True], ids=["float", "bool"])
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda v: StageRun("snap", (("grid_nm", v),)), id="StageRun.parameters"
        ),
        pytest.param(
            lambda v: StageRun("snap-diameters", (("sizes_nm", (7_000_000, v)),)),
            id="StageRun.parameters-in-a-tuple",
        ),
    ],
)
def test_a_payload_key_ending_nm_must_hold_whole_nanometres(build, value) -> None:
    """The suffix is the whole contract in a payload, so it is enforced."""
    with pytest.raises(TypeError, match="nanometres"):
        build(value)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: StageRun("snap", (("grid_nm", 500_000),)), id="StageRun.parameters"),
        pytest.param(
            lambda: StageRun("snap-diameters", (("sizes_nm", (7_000_000, 12_000_000)),)),
            id="StageRun.parameters-in-a-tuple",
        ),
    ],
)
def test_a_payload_key_ending_nm_accepts_whole_nanometres(build) -> None:
    """The other side of the same guard: it refuses a type, not a payload.

    Without this the rule above is satisfied by a check that rejects everything,
    and every stage in the pipeline would be unable to describe itself.
    """
    assert build() is not None


def test_a_payload_key_that_is_not_a_length_may_hold_a_float() -> None:
    """The rule is the suffix, not "no floats"."""
    run = StageRun("identify-enclosure", (("draft_angle_deg", 2.0),))
    assert run.get("draft_angle_deg") == 2.0


# --------------------------------------------------------------------------
# grouping holes into rows
# --------------------------------------------------------------------------


def row_panel(*holes: Hole) -> DrillData:
    return DrillData(holes=holes)


def test_rows_run_from_the_top_of_the_panel_down() -> None:
    """Descending Y, because the drawing stacks one chain dimension per row and
    builds the stack from the bottom row outwards — so an ascending order does
    not reorder the sheet, it changes *which* rows lose their dimension when the
    stack runs out of room."""
    panel = row_panel(
        Hole.from_measurement(Nanometre(0), Nanometre(-18_750_000), Nanometre(5_000_000)).with_number(7),
        Hole.from_measurement(Nanometre(0), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(2),
        Hole.from_measurement(Nanometre(0), Nanometre(0), Nanometre(3_000_000)).with_number(5),
    )

    assert [y for y, _ in panel.rows()] == [18_000_000, 0, -18_750_000]


def test_a_row_runs_left_to_right() -> None:
    """Ascending X within the row. The holes are handed over in an order that is
    neither ascending nor descending, and named by ``index`` rather than by
    position, so neither a reversal nor "whatever order they arrived in" passes.
    """
    panel = row_panel(
        Hole.from_measurement(Nanometre(20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(6),
        Hole.from_measurement(Nanometre(-40_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(2),
        Hole.from_measurement(Nanometre(0), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(9),
    )

    ((_, holes),) = panel.rows()

    assert [hole.index for hole in holes] == [2, 9, 6]
    assert [hole.x_nm for hole in holes] == [-40_000_000, 0, 20_000_000]


def test_two_holes_a_nanometre_apart_in_y_are_two_rows() -> None:
    """Grouping is exact, and a nanometre is the whole of what that decides."""
    panel = row_panel(
        Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(3),
        Hole.from_measurement(Nanometre(20_000_000), Nanometre(18_000_001), Nanometre(7_000_000)).with_number(8),
    )

    assert [y for y, _ in panel.rows()] == [18_000_001, 18_000_000]


def test_two_holes_half_a_millimetre_apart_are_two_rows() -> None:
    """The other side of the same boundary, at a distance a machinist can see.
    A bucket wide enough to swallow it would dimension two rows of holes as one.
    """
    panel = row_panel(
        Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(3),
        Hole.from_measurement(Nanometre(20_000_000), Nanometre(17_500_000), Nanometre(7_000_000)).with_number(8),
    )

    assert [y for y, _ in panel.rows()] == [18_000_000, 17_500_000]
