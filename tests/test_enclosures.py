"""The catalogue is derived, so the tests re-derive it.

Asserting the shipped table against hand-written expectations would only prove
that two transcriptions agree, which is the failure mode the generator exists to
remove. The load-bearing test re-runs the derivation against
``docs/parts/dimensions.tsv`` and compares.

A second test then cross-checks that result against ``docs/1590.pdf``, which is a
genuinely independent document rather than a second reading of the same one: the
series datasheet publishes whole millimetres, and every fine length and width
rounded half-up must reproduce them. Two documents agreeing is a far stronger
claim than one document read twice, and it is what makes a revision of *either*
a red test rather than a quiet disagreement.

The rest pin the collapse rules, the nanometre conversion and the footprint
grouping, which is where a plausible-looking edit does real damage.
"""

from __future__ import annotations

import dataclasses
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from aidrill.enclosures import HAMMOND_1590, Enclosure, footprints

REPO = Path(__file__).resolve().parent.parent
DATASHEET = REPO / "docs" / "1590.pdf"
DRAWINGS = REPO / "docs" / "parts" / "dimensions.tsv"

#: Spelled out rather than imported from ``aidrill.units``: a test that took the
#: factor from the tree it is grading could not tell a correct conversion from a
#: consistently wrong one.
MM = 1_000_000


def test_the_catalogue_matches_the_drawings_the_repo_ships():
    """The table is derived from docs/parts/dimensions.tsv. If they disagree, the
    table is wrong.

    Hammond states its data may change; this test is what makes a revision
    visible rather than silent.
    """
    from tools.build_catalogue import read_drawings

    assert {
        (e.part, e.length_nm, e.width_nm, e.height_nm) for e in HAMMOND_1590
    } == read_drawings(DRAWINGS)


def test_every_footprint_axis_rounds_to_the_series_datasheets_own_millimetre():
    """The coarse cross-check, against a document the fine values did not come from.

    ``docs/1590.pdf`` is the series table Hammond publishes at whole millimetres.
    Rounding every drawing's length and width half-up must reproduce it, for all
    37 parts — which is the check that catches a transposed digit in the TSV
    without assuming the TSV.

    Half-*up*, not the builtin: Hammond publishes 60.50 as 61 where Python's
    banker's rounding gives 60, so a checker written with ``round()`` sees one
    axis of one part disagree and reads bad data rather than a rounding mode.
    """
    from tools.build_catalogue import extract_series

    series = {part: (length, width) for part, length, width, _ in extract_series(DATASHEET)}

    rounded = {
        e.part: (_half_up_mm(e.length_nm), _half_up_mm(e.width_nm)) for e in HAMMOND_1590
    }
    assert rounded == series


def test_the_two_documents_disagree_on_exactly_two_heights_and_nowhere_else():
    """Named rather than hidden, because a bare exception in the test above would
    look like a fudge.

    ``1590XX`` and ``1590X`` are 39.30 and 55.00 on their drawings against the
    series table's 40 and 56. One of the two documents is wrong in each case and
    the PDFs alone cannot say which. Neither disagreement can move a match, and
    the second assertion is why: matching goes through ``Enclosure.footprint``,
    which is length and width and nothing else, so a height the two documents
    argue about is a height no panel is identified by.

    Stated as a test rather than as a comment in the cross-check above, because
    an exception carved out of an assertion with no name is indistinguishable
    from a fudge.
    """
    from tools.build_catalogue import extract_series

    series = {part: height for part, _, _, height in extract_series(DATASHEET)}
    disagree = {
        e.part: (_half_up_mm(e.height_nm), series[e.part])
        for e in HAMMOND_1590
        if _half_up_mm(e.height_nm) != series[e.part]
    }

    assert disagree == {"1590XX": (39, 40), "1590X": (55, 56)}
    assert Enclosure("1590X", 1, 2, 3).footprint == (1, 2), "a height cannot reach a match"


def _half_up_mm(nm: int) -> int:
    """Whole millimetres, ties away from zero — the rule Hammond's own table uses."""
    return int((Decimal(nm) / MM).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def test_every_catalogue_dimension_is_an_exact_whole_nanometre():
    """The unit is the point: an ``int`` cannot be 112.39999999999999.

    ``type(...) is int`` rather than ``isinstance``, because ``bool`` is an
    ``int`` in Python and a catalogue that had acquired a ``True`` somewhere
    would pass the looser check.
    """
    for enclosure in HAMMOND_1590:
        for value in (enclosure.length_nm, enclosure.width_nm, enclosure.height_nm):
            assert type(value) is int, enclosure


def test_the_conversion_is_exact_where_float_multiplication_is_not():
    """The one value in the shipped catalogue that the float spelling corrupts.

    ``float("64.60") * 1e6`` is 64599999.99999999, so ``int()`` of it is
    64 599 999 — a 1590CE 0.4 microns shorter than the one Hammond casts.

    Asserted on the *converter*, not only on the shipped table, and the
    distinction is what makes this a test of the ``Decimal`` path rather than of
    the file on disk. A generator mutated back to floats leaves ``enclosures.py``
    exactly as it is until somebody re-runs it, so an assertion on
    ``HAMMOND_1590`` alone stays green through the whole defect and only the
    round-trip comparison notices. The shipped value is asserted too, because the
    two agreeing is the claim: the constant that was written is the one this
    conversion produces.
    """
    from tools.build_catalogue import _nanometres

    (ce,) = [e for e in HAMMOND_1590 if e.part == "1590CE"]

    assert _nanometres("64.60") == 64_600_000
    assert _nanometres("64.60") != int(float("64.60") * 1e6)
    assert ce.height_nm == _nanometres("64.60")


def test_a_figure_finer_than_a_nanometre_is_refused_rather_than_truncated():
    """A generator has no measurement to round: every figure it reads is
    published. So a source that started quoting finer than the unit can hold is a
    failed generation, not a silently shortened case."""
    from tools.build_catalogue import _nanometres

    assert _nanometres("112.40") == 112_400_000
    with pytest.raises(ValueError, match="whole number of nanometres"):
        _nanometres("112.4000000001")


def test_a_footprint_names_every_part_that_shares_it():
    """A 2-D outline identifies a footprint, never a part: these differ only in height."""
    assert footprints()[(112_400_000, 60_500_000)] == ("1590B", "1590B2")
    assert footprints()[(119_500_000, 94_000_000)] == (
        "1590BB", "1590BB2", "1590BBS", "1590C",
    )


def test_the_1590b_is_the_size_its_drawing_prints():
    """The one enclosure every pedal builder owns, spelled out.

    Named separately from the derived comparison so a regression in the
    derivation reports the part that matters rather than a set diff of 37.
    """
    assert (
        Enclosure("1590B", 112_400_000, 60_500_000, 31_000_000) in HAMMOND_1590
    ), "1590B must be 112.40 x 60.50 x 31.00 mm"


def test_the_catalogue_covers_every_part_exactly_once():
    """One entry per base part, and 26 outlines for artwork to match against.

    The counts are the cheap signal that a revision added or removed something: a
    change here is not necessarily wrong, but it is never silent. 26 rather than
    the 22 the whole-millimetre table had, because four outlines that coincided
    once rounded no longer do.
    """
    parts = [e.part for e in HAMMOND_1590]
    assert len(parts) == 37
    assert len(set(parts)) == 37
    assert len({(e.length_nm, e.width_nm, e.height_nm) for e in HAMMOND_1590}) == 37
    assert len(footprints()) == 26


def test_the_parts_the_coarse_table_could_not_tell_apart_are_separate_here():
    """1590B2 and 1590BS both round to 112 x 61 x 38 and are not the same box.

    112.40 x 60.50 x 37.50 against 112.00 x 60.50 x 38.00: three axes, all three
    different, and every one of them lost to the rounding. Keying the catalogue
    on whole millimetres would have made them one entry, and the operator who
    ordered a BS would have been told they own a B2.
    """
    same_coarse = sorted(
        (e.part, e.length_nm, e.width_nm, e.height_nm)
        for e in HAMMOND_1590
        if (_half_up_mm(e.length_nm), _half_up_mm(e.width_nm), _half_up_mm(e.height_nm))
        == (112, 61, 38)
    )

    assert same_coarse == [
        ("1590B2", 112_400_000, 60_500_000, 37_500_000),
        ("1590BS", 112_000_000, 60_500_000, 38_000_000),
    ]


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
        expected.setdefault((enclosure.length_nm, enclosure.width_nm), set()).add(
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
        enclosure.length_nm = 999  # type: ignore[misc]
    assert not hasattr(enclosure, "__dict__"), "slots=True, per house style"


def test_an_enclosures_footprint_is_its_length_and_width():
    """Length then width, in that order -- the axis order the datasheet uses.

    Numbers chosen so that transposing them cannot pass, which 145 x 145 would.
    """
    assert Enclosure(
        "1590XX", 145_200_000, 121_200_000, 39_300_000
    ).footprint == (145_200_000, 121_200_000)


def test_the_catalogue_is_ordered_by_footprint_then_height():
    """Parts sharing an outline sit together, so the table reads as the drawings do."""
    keys = [(e.length_nm, e.width_nm, e.height_nm, e.part) for e in HAMMOND_1590]
    assert keys == sorted(keys)


def test_the_runtime_never_opens_a_pdf():
    """pdfplumber is a dev dependency, and the invariant is about the whole
    package, not one module.

    If anything under ``src/aidrill`` imported it, installing aidrill would need
    it and the catalogue would stop being a shipped constant. Checking only
    ``enclosures.py`` would pass while a later stage re-read a PDF at runtime,
    which is exactly the shape this is meant to forbid. It still binds now that
    the catalogue is built from a TSV: the datasheet is still read, by the
    generator and by the test above.
    """
    package = REPO / "src" / "aidrill"
    modules = sorted(package.rglob("*.py"))
    assert modules, "found no modules to check -- the glob is wrong"
    offenders = [
        module.relative_to(package).as_posix()
        for module in modules
        if "pdfplumber" in module.read_text(encoding="utf-8")
    ]
    assert offenders == []


class TestReadingTheDrawings:
    """What the TSV reader accepts, and what it refuses to guess about."""

    def test_a_data_row_yields_its_part_and_three_nanometre_dimensions(self):
        from tools.build_catalogue import _drawing_row

        row = "1590B\t112.40\t60.50\t31.00\textracted"
        assert _drawing_row(row) == ("1590B", 112_400_000, 60_500_000, 31_000_000)

    def test_a_comment_and_the_header_are_skipped(self):
        """The header is recognised by its first cell, not by its line number, so
        a comment added above it cannot shift which line is the header."""
        from tools.build_catalogue import _drawing_row

        assert _drawing_row("# Hammond 1590 external dimensions") is None
        assert _drawing_row("part\tlength_mm\twidth_mm\theight_mm\tsource") is None
        assert _drawing_row("") is None

    def test_a_malformed_row_raises_rather_than_being_dropped(self):
        """The datasheet reader skips rows because a PDF table is full of
        non-data. This file has none: every line is either a comment, the header
        or a part, so a row that does not parse means the one document the
        catalogue trusts is damaged — and dropping it would ship a catalogue
        missing an enclosure, silently.
        """
        from tools.build_catalogue import _drawing_row

        with pytest.raises(ValueError, match="tab-separated"):
            _drawing_row("1590B\t112.40\t60.50\t31.00")

    def test_the_source_column_is_provenance_and_changes_no_dimension(self):
        """Two rows reached by different routes are still the same length."""
        from tools.build_catalogue import _drawing_row

        extracted = _drawing_row("1590B\t112.40\t60.50\t31.00\textracted")
        by_hand = _drawing_row("1590B\t112.40\t60.50\t31.00\tmaintainer")
        assert extracted == by_hand

    def test_every_part_in_the_file_reaches_the_catalogue(self):
        """A set is returned, so two identical rows would collapse into one and
        the count would be the only thing that noticed."""
        from tools.build_catalogue import read_drawings

        rows = [
            line
            for line in DRAWINGS.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#") and not line.startswith("part\t")
        ]
        assert len(read_drawings(DRAWINGS)) == len(rows)


class TestTheCollapseToBaseDesignators:
    """The variant-stripping rules, pinned individually.

    Used by the series-datasheet cross-check, whose column 0 carries order codes.
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
            ("1590WF", "1590F"),
            ("1590WFBK", "1590F"),
        ],
    )
    def test_a_variant_collapses_to_the_part_whose_outline_it_shares(
        self, part, expected
    ):
        from tools.build_catalogue import _base_designator

        assert _base_designator(part) == expected

    def test_the_bare_family_name_is_never_a_part(self):
        """No drawing gives ``1590`` dimensions; a collapse that lands there has
        stripped one character too many."""
        assert all(e.part != "1590" for e in HAMMOND_1590)
        assert Enclosure("1590F", 188_000_000, 188_000_000, 67_000_000) in HAMMOND_1590


class TestWhichSeriesRowsCountAsData:
    """What the datasheet extraction accepts, pinned without opening a PDF.

    The datasheet interleaves enclosure tables with screw and gasket tables, and
    pdfplumber leaves some rows unsplit. A filter that let either through would
    put a screwdriver bit in the cross-check -- and the whole-suite comparison
    against the shipped PDF cannot distinguish a filter that is right from one
    that is merely right about *this* revision.
    """

    #: A real enclosure row, split cleanly: part, five variants, colour, L, W, H,
    #: gasket. A tuple, so no test can edit the fixture the others depend on.
    GOOD: ClassVar[tuple[str, ...]] = (
        "1590BBK", "1590WBBK", "1590BBFLBK", "1590WBBFLBK", "1590BBFBK",
        "1590WBBFBK", "Black", "120", "94", "34", "1590BBGASKET",
    )

    def test_a_clean_enclosure_row_yields_its_part_and_dimensions(self):
        from tools.build_catalogue import _dimensioned_row

        assert _dimensioned_row(self.GOOD) == ("1590BBK", 120, 94, 34)

    def test_a_row_pdfplumber_failed_to_split_is_skipped(self):
        """The whole line lands in column 0 and the rest is ``None``."""
        from tools.build_catalogue import _dimensioned_row

        merged = ["1590BB 1590WBB Natural 120 94 34 1590BBGASKET"] + [None] * 10
        assert _dimensioned_row(merged) is None

    def test_a_screw_table_row_is_skipped(self):
        """Ten columns wide, with part numbers where the dimensions would be."""
        from tools.build_catalogue import _dimensioned_row

        screws = ["1590B", "1590MS100", "1590MS50BK", "1590WMS100",
                  "1590WMS100BK", "1590MS50T", "1590MS50TBK", "1590WMS50T",
                  "1590WMS50TBK", "SCDRIVET10-2"]
        assert _dimensioned_row(screws) is None

    def test_a_dimensioned_row_from_another_family_is_skipped(self):
        """A 1550 box has dimensions too. It is not in this catalogue.

        Nothing in the shipped revision exercises this, which is exactly why it
        is asserted here rather than left to the comparison against the PDF.
        """
        from tools.build_catalogue import _dimensioned_row

        assert _dimensioned_row(("1550B",) + self.GOOD[1:]) is None

    def test_a_row_too_narrow_to_hold_dimensions_is_skipped(self):
        from tools.build_catalogue import _dimensioned_row

        assert _dimensioned_row(["1590B", "Black", "120", "94"]) is None

    def test_a_blank_part_cell_is_skipped(self):
        from tools.build_catalogue import _dimensioned_row

        assert _dimensioned_row(("",) + self.GOOD[1:]) is None
        assert _dimensioned_row((None,) + self.GOOD[1:]) is None

    def test_the_dimensions_come_from_columns_seven_eight_and_nine(self):
        """Numbers chosen so that reading one column early or late cannot pass."""
        from tools.build_catalogue import _dimensioned_row

        row = ["1590B", "a", "b", "c", "d", "e", "Black", "11", "22", "33", "g"]
        assert _dimensioned_row(row) == ("1590B", 11, 22, 33)


class TestTheGeneratedModule:
    """The module is rendered, so the rendering is what gets tested."""

    def test_rendering_the_shipped_catalogue_reproduces_the_file_on_disk(self):
        """The strongest statement that the table was generated and not edited.

        If someone hand-corrects a dimension in ``enclosures.py``, this fails
        even though the module still imports and still looks plausible.
        """
        from tools.build_catalogue import read_drawings, render_module

        shipped = (REPO / "src" / "aidrill" / "enclosures.py").read_text(encoding="utf-8")
        assert render_module(read_drawings(DRAWINGS)) == shipped

    def test_the_rendered_table_is_ordered_by_footprint_then_height(self):
        """Four orderings are pulled apart deliberately, because any fixture
        chosen carelessly lets two or three of them agree.

        Part names run Z, M, A down the expected output, so sorting by part
        number cannot pass. Heights run 90, 34, 57, so sorting by height cannot
        pass either. And the two footprints are ``(100, 90)`` and ``(120, 60)``,
        which order oppositely by length and by width, so transposing the sort
        key cannot pass -- by width the order would be M, A, Z.

        Both of the last two were learned the hard way. The first fixture ran its
        heights ascending and was blind to a height-first sort; the second used a
        square ``(51, 51)`` alongside two entries sharing one footprint, and a
        transposed key left the order untouched.
        """
        from tools.build_catalogue import render_module

        rendered = render_module(
            {
                ("1590A", 120_000_000, 60_000_000, 57_000_000),
                ("1590Z", 100_000_000, 90_000_000, 90_000_000),
                ("1590M", 120_000_000, 60_000_000, 34_000_000),
            }
        )
        rows = [ln for ln in rendered.splitlines() if ln.startswith("    Enclosure(")]
        assert rows == [
            '    Enclosure("1590Z", 100_000_000, 90_000_000, 90_000_000),',
            '    Enclosure("1590M", 120_000_000, 60_000_000, 34_000_000),',
            '    Enclosure("1590A", 120_000_000, 60_000_000, 57_000_000),',
        ]
