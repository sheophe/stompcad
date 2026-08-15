"""The catalogue is derived, so the tests re-derive it.

Asserting the shipped table against hand-written expectations would only prove
that two transcriptions agree, which is the failure mode the generator exists to
remove. The load-bearing test re-runs the extraction against ``docs/1590.pdf``
and compares. The rest pin the collapse rules and the footprint grouping, which
is where a plausible-looking edit does real damage.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from aidrill.enclosures import HAMMOND_1590, Enclosure, footprints

DATASHEET = Path(__file__).resolve().parent.parent / "docs" / "1590.pdf"


def test_the_catalogue_matches_the_datasheet_the_repo_ships():
    """The table is derived from docs/1590.pdf. If they disagree, the table is wrong.

    Hammond states its data may change; this test is what makes a revision
    visible rather than silent.
    """
    from tools.extract_1590 import extract

    assert {
        (e.part, e.length_mm, e.width_mm, e.height_mm) for e in HAMMOND_1590
    } == extract(DATASHEET)


def test_a_footprint_names_every_part_that_shares_it():
    """A 2-D outline identifies a footprint, never a part: these differ only in height."""
    assert footprints()[(112, 61)] == ("1590B", "1590B2", "1590BS")
    assert footprints()[(120, 94)] == ("1590BB", "1590BB2", "1590BBS", "1590C")


def test_the_1590b_is_the_size_the_datasheet_prints():
    """The one enclosure every pedal builder owns, spelled out.

    Named separately from the derived comparison so a regression in the
    extraction reports the part that matters rather than a set diff of 37.
    """
    assert (
        Enclosure("1590B", 112, 61, 31) in HAMMOND_1590
    ), "1590B must be 112 x 61 x 31 mm"


def test_the_catalogue_covers_every_part_exactly_once():
    """One entry per base part, and 22 outlines for artwork to match against.

    The counts are the cheap signal that a datasheet revision added or removed
    something: a change here is not necessarily wrong, but it is never silent.
    """
    parts = [e.part for e in HAMMOND_1590]
    assert len(parts) == 37
    assert len(set(parts)) == 37
    assert len({(e.length_mm, e.width_mm, e.height_mm) for e in HAMMOND_1590}) == 36
    assert len(footprints()) == 22


def test_parts_sharing_all_three_dimensions_stay_separate():
    """1590B2 and 1590BS are both 112 x 61 x 38 and are still two parts.

    Keying the catalogue on dimensions would silently drop one of them, and the
    operator who ordered a BS would be told they own a B2.
    """
    same_size = [
        e.part
        for e in HAMMOND_1590
        if (e.length_mm, e.width_mm, e.height_mm) == (112, 61, 38)
    ]
    assert sorted(same_size) == ["1590B2", "1590BS"]


def test_every_footprint_lists_its_candidates_sorted():
    """Sorted, for every footprint, not just the two the examples name.

    A matcher prints these to the operator; an order inherited from catalogue
    order would change the drawing's text when an unrelated part was added.
    """
    for outline, candidates in footprints().items():
        assert list(candidates) == sorted(candidates), outline


def test_every_footprint_names_exactly_the_parts_that_have_it():
    """The grouping is a partition of the catalogue, with nothing lost or invented."""
    expected: dict[tuple[int, int], set[str]] = {}
    for enclosure in HAMMOND_1590:
        expected.setdefault((enclosure.length_mm, enclosure.width_mm), set()).add(
            enclosure.part
        )
    assert {k: set(v) for k, v in footprints().items()} == expected


def test_footprints_cannot_be_edited_by_a_caller():
    """A matcher holds this mapping; a caller that mutated it would poison later matches."""
    with pytest.raises(TypeError):
        footprints()[(1, 1)] = ("nonsense",)


def test_footprints_is_the_same_mapping_every_call():
    """Rebuilding per call would let two callers disagree about candidate order."""
    assert footprints() is footprints()


def test_an_enclosure_is_a_frozen_value():
    """Value objects, like everything else in the model: a catalogue entry that
    could be mutated would let one stage rewrite a physical constant for the next."""
    enclosure = HAMMOND_1590[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        enclosure.length_mm = 999  # type: ignore[misc]
    assert not hasattr(enclosure, "__dict__"), "slots=True, per house style"


def test_an_enclosures_footprint_is_its_length_and_width():
    """Length then width, in that order -- the axis order the datasheet uses.

    Numbers chosen so that transposing them cannot pass, which 112 x 112 would.
    """
    assert Enclosure("1590XX", 145, 121, 40).footprint == (145, 121)


def test_the_catalogue_is_ordered_by_footprint_then_height():
    """Parts sharing an outline sit together, so the table reads as the datasheet does."""
    keys = [(e.length_mm, e.width_mm, e.height_mm, e.part) for e in HAMMOND_1590]
    assert keys == sorted(keys)


def test_the_runtime_never_opens_the_datasheet():
    """pdfplumber is a dev dependency. If enclosures.py imported it, installing
    aidrill would need it, and the catalogue would stop being a shipped constant."""
    source = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "aidrill"
        / "enclosures.py"
    ).read_text(encoding="utf-8")
    assert "pdfplumber" not in source


class TestTheCollapseToBaseDesignators:
    """The variant-stripping rules, pinned individually.

    Colour, watertight and flange decorations name the same outline as the base
    part, so they must collapse -- but ``1590F`` is a real 188 x 188 x 67
    enclosure whose name ends in the flange suffix, and collapsing it to a bare
    ``1590`` invents a part that has never existed.
    """

    @pytest.mark.parametrize(
        "part, expected",
        [
            ("1590B", "1590B"),
            ("1590BRD", "1590B"),
            ("1590BBS", "1590BBS"),
            ("1590BBSGR", "1590BBS"),
            ("1590WBB", "1590BB"),
            ("1590BBFL", "1590BB"),
            ("1590BBF", "1590BB"),
            ("1590WBBFLBK", "1590BB"),
            ("1590F", "1590F"),
            ("1590FBK", "1590F"),
            ("1590FF", "1590F"),
            ("1590FFL", "1590F"),
        ],
    )
    def test_a_variant_collapses_to_the_part_whose_outline_it_shares(
        self, part, expected
    ):
        from tools.extract_1590 import _base_designator

        assert _base_designator(part) == expected

    def test_the_bare_family_name_is_never_a_part(self):
        """No datasheet row gives ``1590`` dimensions; a collapse that lands
        there has stripped one character too many."""
        assert all(e.part != "1590" for e in HAMMOND_1590)
        assert Enclosure("1590F", 188, 188, 67) in HAMMOND_1590


class TestWhichRowsCountAsData:
    """What the extraction accepts, pinned without opening a PDF.

    The datasheet interleaves enclosure tables with screw and gasket tables, and
    pdfplumber leaves some rows unsplit. A filter that let either through would
    put a screwdriver bit in the catalogue -- and the whole-suite comparison
    against the shipped PDF cannot distinguish a filter that is right from one
    that is merely right about *this* revision.
    """

    #: A real enclosure row, split cleanly: part, five variants, colour, L, W, H, gasket.
    GOOD = ["1590BBK", "1590WBBK", "1590BBFLBK", "1590WBBFLBK", "1590BBFBK",
            "1590WBBFBK", "Black", "120", "94", "34", "1590BBGASKET"]

    def test_a_clean_enclosure_row_yields_its_part_and_dimensions(self):
        from tools.extract_1590 import _dimensioned_row

        assert _dimensioned_row(self.GOOD) == ("1590BBK", 120, 94, 34)

    def test_a_row_pdfplumber_failed_to_split_is_skipped(self):
        """The whole line lands in column 0 and the rest is ``None``."""
        from tools.extract_1590 import _dimensioned_row

        merged = ["1590BB 1590WBB Natural 120 94 34 1590BBGASKET"] + [None] * 10
        assert _dimensioned_row(merged) is None

    def test_a_screw_table_row_is_skipped(self):
        """Ten columns wide, with part numbers where the dimensions would be."""
        from tools.extract_1590 import _dimensioned_row

        screws = ["1590B", "1590MS100", "1590MS50BK", "1590WMS100",
                  "1590WMS100BK", "1590MS50T", "1590MS50TBK", "1590WMS50T",
                  "1590WMS50TBK", "SCDRIVET10-2"]
        assert _dimensioned_row(screws) is None

    def test_a_dimensioned_row_from_another_family_is_skipped(self):
        """A 1550 box has dimensions too. It is not in this catalogue.

        Nothing in the shipped revision exercises this, which is exactly why it
        is asserted here rather than left to the comparison against the PDF.
        """
        from tools.extract_1590 import _dimensioned_row

        assert _dimensioned_row(["1550B"] + self.GOOD[1:]) is None

    def test_a_row_too_narrow_to_hold_dimensions_is_skipped(self):
        from tools.extract_1590 import _dimensioned_row

        assert _dimensioned_row(["1590B", "Black", "120", "94"]) is None

    def test_a_blank_part_cell_is_skipped(self):
        from tools.extract_1590 import _dimensioned_row

        assert _dimensioned_row([""] + self.GOOD[1:]) is None
        assert _dimensioned_row([None] + self.GOOD[1:]) is None

    def test_the_dimensions_come_from_columns_seven_eight_and_nine(self):
        """Numbers chosen so that reading one column early or late cannot pass."""
        from tools.extract_1590 import _dimensioned_row

        row = ["1590B", "a", "b", "c", "d", "e", "Black", "11", "22", "33", "g"]
        assert _dimensioned_row(row) == ("1590B", 11, 22, 33)


class TestTheGeneratedModule:
    """The module is rendered, so the rendering is what gets tested."""

    def test_rendering_the_shipped_catalogue_reproduces_the_file_on_disk(self):
        """The strongest statement that the table was generated and not edited.

        If someone hand-corrects a dimension in ``enclosures.py``, this fails
        even though the module still imports and still looks plausible.
        """
        from tools.extract_1590 import extract, render_module

        shipped = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "aidrill"
            / "enclosures.py"
        ).read_text(encoding="utf-8")
        assert render_module(extract(DATASHEET)) == shipped

    def test_the_rendered_table_is_ordered_by_footprint_then_height(self):
        """Three orderings are pulled apart deliberately, because two of them
        agree on any fixture chosen carelessly.

        Part names run Z, M, A down the expected output, so sorting by part
        number cannot pass. Heights run 90, 34, 57, so sorting by height cannot
        pass either -- an earlier version of this fixture listed its heights
        ascending and was blind to both.
        """
        from tools.extract_1590 import render_module

        rendered = render_module(
            {("1590A", 120, 94, 57), ("1590Z", 51, 51, 90), ("1590M", 120, 94, 34)}
        )
        rows = [ln for ln in rendered.splitlines() if ln.startswith("    Enclosure(")]
        assert rows == [
            '    Enclosure("1590Z", 51, 51, 90),',
            '    Enclosure("1590M", 120, 94, 34),',
            '    Enclosure("1590A", 120, 94, 57),',
        ]
