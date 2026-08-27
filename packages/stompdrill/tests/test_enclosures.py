"""Tests for the generated TSV-backed enclosure catalogue."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from stompdrill.enclosures import HAMMOND_1590, Enclosure, footprints
from stompmodel.units import Nanometre

# Two roots, because the authority and its rendering live at different levels:
# the drawings TSV is repository documentation, the module it generates ships
# inside this package.
PACKAGE = Path(__file__).resolve().parent.parent
REPO = PACKAGE.parent.parent
DRAWINGS = REPO / "docs" / "parts" / "dimensions.tsv"


def test_the_catalogue_matches_the_drawings_the_repo_ships():
    """The generated table matches the distributed TSV authority."""
    from tools.build_catalogue import read_drawings

    assert {
        (enclosure.part, enclosure.length_nm, enclosure.width_nm, enclosure.height_nm)
        for enclosure in HAMMOND_1590
    } == read_drawings(DRAWINGS)


def test_every_catalogue_dimension_is_an_exact_whole_nanometre():
    """Catalogue dimensions are plain integers, never floating-point values."""
    for enclosure in HAMMOND_1590:
        for value in (enclosure.length_nm, enclosure.width_nm, enclosure.height_nm):
            assert type(value) is int, enclosure


WHOLE = {"length_nm": 112_400_000, "width_nm": 60_500_000, "height_nm": 31_000_000}


@pytest.mark.parametrize("dimension", list(WHOLE))
@pytest.mark.parametrize("value", [112.4, True], ids=["float", "bool"])
def test_a_dimension_that_is_not_a_plain_int_is_refused_at_construction(dimension, value):
    """Each dimension rejects floats and bools at construction."""
    with pytest.raises(TypeError, match=rf"^Enclosure\.{dimension} must be"):
        Enclosure("1590B", **{**WHOLE, dimension: value})


def test_the_conversion_is_exact_where_float_multiplication_is_not():
    """The TSV conversion preserves a value float multiplication corrupts."""
    from tools.build_catalogue import _nanometres

    (ce,) = [enclosure for enclosure in HAMMOND_1590 if enclosure.part == "1590CE"]

    assert _nanometres("64.60") == 64_600_000
    assert _nanometres("64.60") != int(float("64.60") * 1e6)
    assert ce.height_nm == _nanometres("64.60")


def test_a_figure_finer_than_a_nanometre_is_refused_rather_than_truncated():
    """Published values finer than a nanometre fail generation."""
    from tools.build_catalogue import _nanometres

    assert _nanometres("112.40") == 112_400_000
    with pytest.raises(ValueError, match="whole number of nanometres"):
        _nanometres("112.4000000001")


def test_a_footprint_names_every_part_that_shares_it():
    """A footprint identifies every part with that two-dimensional outline."""
    assert footprints()[(112_400_000, 60_500_000)] == ("1590B", "1590B2")
    assert footprints()[(119_500_000, 94_000_000)] == (
        "1590BB", "1590BB2", "1590BBS", "1590C",
    )


def test_the_tsv_names_every_row_publishing_length_smaller_than_width():
    """Catalogue invariant the 1590LB defect exposed: nothing states that a
    published length is always the larger figure, and one row -- 1590LB --
    publishes it smaller. Name exactly which rows those are, re-reading the
    TSV authority rather than the generated module, so a new such row cannot
    arrive unnoticed and someone must decide what it means.
    """
    from tools.build_catalogue import read_drawings

    inverted = {
        part for part, length_nm, width_nm, _ in read_drawings(DRAWINGS) if length_nm < width_nm
    }
    assert inverted == {"1590LB"}


def test_the_1590b_is_the_size_its_drawing_prints():
    """The common 1590B has its TSV dimensions."""
    assert (
        Enclosure("1590B", Nanometre(112_400_000), Nanometre(60_500_000), Nanometre(31_000_000)) in HAMMOND_1590
    ), "1590B must be 112.40 x 60.50 x 31.00 mm"


def test_the_catalogue_covers_every_part_exactly_once():
    """The catalogue has 37 parts, sizes, and 26 footprints."""
    parts = [enclosure.part for enclosure in HAMMOND_1590]
    assert len(parts) == 37
    assert len(set(parts)) == 37
    assert len({(e.length_nm, e.width_nm, e.height_nm) for e in HAMMOND_1590}) == 37
    assert len(footprints()) == 26


def test_the_tsv_distinguishes_the_b2_and_bs_footprints():
    """Fine TSV dimensions keep two similar enclosures distinct."""
    dimensions = {
        enclosure.part: (enclosure.length_nm, enclosure.width_nm, enclosure.height_nm)
        for enclosure in HAMMOND_1590
    }
    assert dimensions["1590B2"] == (112_400_000, 60_500_000, 37_500_000)
    assert dimensions["1590BS"] == (112_000_000, 60_500_000, 38_000_000)


def test_every_footprint_lists_its_candidates_sorted():
    """Each footprint presents candidates in deterministic order."""
    for outline, candidates in footprints().items():
        assert list(candidates) == sorted(candidates), outline


def test_every_footprint_names_exactly_the_parts_that_have_it():
    """The footprint mapping partitions the catalogue without loss."""
    expected: dict[tuple[int, int], set[str]] = {}
    for enclosure in HAMMOND_1590:
        expected.setdefault((enclosure.length_nm, enclosure.width_nm), set()).add(
            enclosure.part
        )
    assert {outline: set(parts) for outline, parts in footprints().items()} == expected


def test_footprints_cannot_be_edited_by_a_caller():
    """A caller cannot mutate the shared footprint mapping."""
    with pytest.raises(TypeError):
        footprints()[(1, 1)] = ("nonsense",)


def test_footprints_is_the_same_mapping_every_call():
    """Callers share the immutable cached mapping."""
    assert footprints() is footprints()


def test_an_enclosure_is_a_frozen_value():
    """Catalogue entries are frozen, slotted value objects."""
    enclosure = HAMMOND_1590[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        enclosure.length_nm = 999
    assert not hasattr(enclosure, "__dict__"), "slots=True, per house style"


def test_an_enclosures_footprint_is_its_length_and_width():
    """Footprints use the length-width axis order."""
    assert Enclosure(
        "1590XX", Nanometre(145_200_000), Nanometre(121_200_000), Nanometre(39_300_000)
    ).footprint == (145_200_000, 121_200_000)


def test_the_catalogue_is_ordered_by_footprint_then_height():
    """Generated entries sort by footprint, height, then part."""
    keys = [(e.length_nm, e.width_nm, e.height_nm, e.part) for e in HAMMOND_1590]
    assert keys == sorted(keys)


class TestReadingTheDrawings:
    """TSV reader behaviour at its authority boundary."""

    def test_a_data_row_yields_its_part_and_three_nanometre_dimensions(self):
        from tools.build_catalogue import _drawing_row

        row = "1590B\t112.40\t60.50\t31.00\textracted"
        assert _drawing_row(row) == ("1590B", 112_400_000, 60_500_000, 31_000_000)

    def test_a_comment_and_the_header_are_skipped(self):
        """Comments and the named header do not become catalogue rows."""
        from tools.build_catalogue import _drawing_row

        assert _drawing_row("# Hammond 1590 external dimensions") is None
        assert _drawing_row("part\tlength_mm\twidth_mm\theight_mm\tsource") is None
        assert _drawing_row("") is None

    def test_a_malformed_row_raises_rather_than_being_dropped(self):
        """Malformed authority rows fail rather than disappear silently."""
        from tools.build_catalogue import _drawing_row

        with pytest.raises(ValueError, match="tab-separated"):
            _drawing_row("1590B\t112.40\t60.50\t31.00")

    def test_the_source_column_is_provenance_and_changes_no_dimension(self):
        """Provenance does not change a part's dimensions."""
        from tools.build_catalogue import _drawing_row

        extracted = _drawing_row("1590B\t112.40\t60.50\t31.00\textracted")
        by_hand = _drawing_row("1590B\t112.40\t60.50\t31.00\tmaintainer")
        assert extracted == by_hand

    def test_every_part_in_the_file_reaches_the_catalogue(self):
        """Every TSV data row reaches the generated catalogue."""
        from tools.build_catalogue import read_drawings

        rows = [
            line
            for line in DRAWINGS.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#") and not line.startswith("part\t")
        ]
        assert len(read_drawings(DRAWINGS)) == len(rows)


class TestTheGeneratedModule:
    """The rendered module is checked as distributed source."""

    def test_rendering_the_shipped_catalogue_reproduces_the_file_on_disk(self):
        """Rendering the TSV catalogue reproduces the checked-in module."""
        from tools.build_catalogue import read_drawings, render_module

        shipped = (PACKAGE / "src" / "stompdrill" / "enclosures.py").read_text(encoding="utf-8")
        assert render_module(read_drawings(DRAWINGS)) == shipped

    def test_the_rendered_table_is_ordered_by_footprint_then_height(self):
        """The renderer sorts by footprint, height, then part."""
        from tools.build_catalogue import render_module

        # Opposing footprint and height orders prevent a transposed sort from passing.
        rendered = render_module(
            {
                ("1590A", 120_000_000, 60_000_000, 57_000_000),
                ("1590Z", 100_000_000, 90_000_000, 90_000_000),
                ("1590M", 120_000_000, 60_000_000, 34_000_000),
            }
        )
        rows = [line for line in rendered.splitlines() if line.startswith("    Enclosure(")]
        def row(part: str, length: str, width: str, height: str) -> str:
            return (
                f'    Enclosure("{part}", Nanometre({length}), '
                f"Nanometre({width}), Nanometre({height})),"
            )

        assert rows == [
            row("1590Z", "100_000_000", "90_000_000", "90_000_000"),
            row("1590M", "120_000_000", "60_000_000", "34_000_000"),
            row("1590A", "120_000_000", "60_000_000", "57_000_000"),
        ]
