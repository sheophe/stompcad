"""Tests for ``aidrill.cli`` (SPEC §8, §9).

Three things are being pinned here.

1. **The open/closed proof.** ``test_emit_dispatches_to_an_emitter_the_cli_has_never_heard_of``
   registers an emitter *inside this file*, under a name that appears in no
   source file, and asserts the CLI dispatches to it and writes its output with
   zero edits to ``cli.py``. That is the whole reason the registry exists; if it
   ever fails, ``cli.py`` has started hardcoding formats.
2. **The documented exit codes**, derived from ``DrillData.worst_severity``.
3. **The fixture ground truth of SPEC §9**, end to end through the real CLI.
"""

from __future__ import annotations

import dataclasses
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

from aidrill import cli
from aidrill.emitters.base import available, register_emitter
from aidrill.errors import EmptyLayerError, LayerNotFoundError
from aidrill.model import (
    Diagnostic,
    DrillData,
    EnclosureMatch,
    Hole,
    RawDrillData,
    RawHole,
    RawOutline,
    ReferenceOutline,
    Severity,
    SourceInfo,
    StageRun,
)
from aidrill.pipeline import DRILL_STANDARDS

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def read(
    *,
    holes=None,
    reference=RawOutline(99.6, 50.4),
    diagnostics=(),
) -> RawDrillData:
    """What a source hands the CLI: float millimetres, nothing quantised.

    The default panel is deliberately one the whole run leaves alone — every
    centre is already on the 0.25 mm grid, both diameters are real metric bits,
    and 99.6 × 50.4 is within tolerance of 1590G's 100.00 × 50.00 and of nothing
    else — so a test asserting on an exit code or a report line is not also
    asserting on a diagnostic it never mentioned.

    A 1590G rather than the 1590B ``tests/fixtures/tar.ai`` is, because these
    runs declare no ``--case``: the fixture's outline is within tolerance of two
    real footprints and an undeclared run refuses it, which is the tool's own
    behaviour and is pinned as such at the end of this file. A default that
    aborted on ``ambiguous-enclosure`` would make every test here a test of the
    abort path. 100.00 × 50.00 is still shared by two parts — 1590G and 1590G2,
    which differ only in height — so a declared ``--case`` still has something to
    choose between, which is what makes the flag worth testing at all.
    """
    if holes is None:
        holes = (
            RawHole(-20.0, 18.0, 7.0, 0),
            RawHole(20.0, 18.0, 7.0, 1),
            RawHole(0.0, -18.75, 5.0, 2),
        )
    return RawDrillData(
        source=SourceInfo(
            path="fake.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill"),
        ),
        reference=reference,
        centre=(56.5, 30.0),
        holes=tuple(holes),
        diagnostics=tuple(diagnostics),
    )


def document(
    *,
    holes=None,
    reference=ReferenceOutline(112_000_000, 61_000_000),
    diagnostics=(),
    processing=(),
) -> DrillData:
    """A finished ``DrillData``, for the report renderers called directly.

    Separate from :func:`read` because it is the *other* side of the
    quantisation phase: whole nanometres, a nominal outline, and a processing
    history a run would have filled in. A test that drives ``cli.main`` wants
    the first; one that calls ``cli.format_tools`` wants this.
    """
    if holes is None:
        holes = (
            Hole.from_measurement(-20_000_000, 18_000_000, 7_000_000, index=0),
            Hole.from_measurement(20_000_000, 18_000_000, 7_000_000, index=1),
            Hole.from_measurement(0, -18_750_000, 5_000_000, index=2),
        )
    return DrillData(
        holes=tuple(holes),
        reference=reference,
        diagnostics=tuple(diagnostics),
        processing=tuple(processing),
        source=SourceInfo(
            path="fake.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill"),
        ),
    )


def quantised_against(standard: str, size_count: int = 183) -> StageRun:
    """The provenance ``SnapDiametersToDrillTable`` leaves behind.

    Hand-built rather than taken from a real run, so that a test can record a
    standard the registry does not hold — which is what a document from another
    version of this tool looks like when the report is asked to render it.
    """
    return StageRun("snap-diameters", (("standard", standard), ("size_count", size_count)))


@pytest.fixture
def fake_source(monkeypatch):
    """Install a stand-in for ``AiPdfSource``. Returns an ``install`` callable."""

    def install(result):
        class FakeSource:
            def __init__(self, path, drill_layer="Drill", reference_layer="Background"):
                self.path = path
                self.drill_layer = drill_layer
                self.reference_layer = reference_layer

            def read(self):
                if isinstance(result, Exception):
                    raise result
                return result

        monkeypatch.setattr(cli, "AiPdfSource", FakeSource)
        return FakeSource

    return install


# ---------------------------------------------------------------------------
# the OCP proof
# ---------------------------------------------------------------------------


def test_emit_dispatches_to_an_emitter_the_cli_has_never_heard_of(
    clean_registry, fake_source, tmp_path, capsys
):
    """A format registered only in this test file must work with no CLI edit."""

    @register_emitter
    class DummyEmitter:
        name = "dummy-test-format"
        media_type = "text/plain"
        extension = ".txt"

        def __init__(self, options=None):
            self.options = options

        def emit(self, data):
            return f"DUMMY {len(data.holes)} holes\n"

    fake_source(read())
    out = tmp_path / "out.txt"

    code = cli.main([str(FIXTURE), "--emit", f"dummy-test-format={out}"])

    assert code == 0
    assert out.read_text() == "DUMMY 3 holes\n"
    assert "dummy-test-format" in capsys.readouterr().out


def test_unregistering_the_dummy_leaves_the_registry_as_it_was(clean_registry):
    assert "dummy-test-format" not in available()


def test_cli_source_never_names_a_registered_format(clean_registry):
    """``cli.py`` may name options classes, never format names (OCP)."""
    source = Path(cli.__file__).read_text()
    for name in available():
        assert name not in source, f"cli.py hardcodes the format name {name!r}"


def test_help_lists_the_registry(clean_registry, capsys):
    @register_emitter
    class DummyEmitter:
        name = "dummy-test-format"
        media_type = "text/plain"
        extension = ".txt"

        def __init__(self, options=None):
            self.options = options

        def emit(self, data):
            return ""

    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in available():
        assert name in out


# ---------------------------------------------------------------------------
# pipeline construction
# ---------------------------------------------------------------------------


def pipeline_for(*argv: str):
    """The pipeline the CLI actually builds for ``argv``.

    Every test below that cares about stage order reads it from here rather than
    restating it, because a parallel list of stage names has already drifted
    once in this repo — ``tests/test_pipeline.py`` still carried the CLI's old
    order long after the CLI had changed.
    """
    return cli.build_pipeline(cli.build_parser().parse_args(["panel.ai", *argv]))


def test_the_cli_fixes_the_stage_order():
    """The one deliberately literal statement of the order in the suite.

    It is literal because it *is* the specification: order is the single thing a
    stage may not declare for itself (LSP), so somebody has to say it, and this
    is the assertion that says it. Everything else derives from
    :func:`pipeline_for`.

    Three stages, and no quantiser: their order is ``aidrill.quantise``'s and is
    pinned in ``tests/test_quantise.py``, where the reasons for it live.

    The middle position is the one with a defect behind it. ``ReviewGridTies``
    must follow ``Deduplicate``, because it judges the pitch from the holes that
    reach the artifacts and dedupe is what settles which those are; run earlier
    it can name a hole that is about to be collapsed away. That argument lives
    in ``cli.build_pipeline`` and the stage's own docstring, and the shape of it
    is pinned in ``tests/test_pipeline.py``.
    """
    assert [stage.name for stage in pipeline_for()] == [
        "deduplicate",
        "review-grid-ties",
        "sort",
    ]


def quantisers_for(*argv: str) -> cli.Quantisers:
    """The three quantisers the CLI actually builds for ``argv``."""
    return cli.build_quantisers(cli.build_parser().parse_args(["panel.ai", *argv]))


def test_the_cli_quantises_between_the_source_and_the_pipeline(fake_source, capsys):
    """The seam, asserted where it is observable rather than by reading source.

    ``read()`` measures 99.6 × 50.4 and hands over float millimetres; the report
    prints the catalogue's 100.000 × 50.000 in whole nanometres and a tool table.
    Neither could exist if the CLI had folded the pipeline over the raw read.
    """
    fake_source(read())

    assert cli.main([str(FIXTURE)]) == 0

    out = capsys.readouterr().out
    assert "100.000 x 50.000 mm" in out
    assert "raw 99.6000 x 50.4000 mm" in out


def test_the_enclosure_is_identified_whether_or_not_a_case_was_declared():
    """Identification is not opt-in. The outline is snapped to the catalogue on
    every run, and ``--case`` only adds the cross-check against what was drawn —
    so a panel drawn 1 mm out is still reported without the operator having to
    know to ask."""
    assert quantisers_for().enclosure.expected_part is None
    assert quantisers_for("--case", "1590B").enclosure.expected_part == "1590B"


def test_grid_warn_defaults_are_left_to_the_quantiser():
    """The grid/4 rule lives in SnapPositions; the CLI must not restate it."""
    snap = quantisers_for("--grid", "1.0").positions
    assert snap.grid_nm == 1_000_000
    assert snap.warn_over_nm == 250_000

    explicit = quantisers_for("--grid", "1.0", "--grid-warn", "0.4").positions
    assert explicit.warn_over_nm == 400_000


def test_the_grid_crosses_the_unit_boundary_exactly_once():
    """``--grid 0.25`` is a quarter of a millimetre, not 0.25 nanometres.

    ``SnapPositions`` takes whole nanometres and refuses anything that is not a
    plain ``int``, so the conversion has to happen at this boundary — and a
    fixture whose millimetres and nanometres could be confused would not show
    it. 0.25 and 250 000 differ by six orders of magnitude.
    """
    assert quantisers_for().positions.grid_nm == 250_000
    assert quantisers_for("--grid", "0.5").positions.grid_nm == 500_000


class TestAGridThatIsNotANumberIsAUsageError:
    """Exit 3, not 1, and not an artifact full of ``XnanYnan``.

    ``--grid=nan`` used to crash out of the snapping code with an uncaught
    ``ValueError``: Python exits **1** for that, which is the code this CLI
    reserves for "warnings present", so a wrapper testing ``[ $? -le 1 ]`` read
    it as a run that had produced usable output. ``--grid=inf`` did not crash at
    all — every coordinate became ``nan`` and the files were written.
    """

    @pytest.mark.parametrize("argv", [["--grid", "nan"], ["--grid", "inf"]])
    def test_a_non_finite_grid_exits_three(self, fake_source, capsys, argv):
        fake_source(read())
        assert cli.main([str(FIXTURE), *argv]) == 3
        assert capsys.readouterr().err.startswith("aidrill: error:")

    def test_a_non_finite_warning_threshold_exits_three(self, fake_source, capsys):
        fake_source(read())
        assert cli.main([str(FIXTURE), "--grid-warn", "nan"]) == 3
        assert capsys.readouterr().err.startswith("aidrill: error:")

    def test_nothing_is_written(self, fake_source, tmp_path, capsys):
        """The failure this is really about: a file that looks well-formed.

        An Excellon file of ``XnanYnan`` lines parses, loads and is the obvious
        one to hand to the machine.
        """
        fake_source(read())
        target = tmp_path / "panel.drl"

        assert cli.main([str(FIXTURE), "--grid", "inf", "--emit", f"excellon={target}"]) == 3
        assert not target.exists()

    def test_the_grid_is_checked_before_the_file_is_even_opened(self, capsys):
        """A typo costs no PDF parse, and is reported as a typo rather than I/O."""
        assert cli.main(["/no/such/panel.ai", "--grid", "nan"]) == 3
        assert "nan" in capsys.readouterr().err


class TestAGridFinerThanAnArtifactCanPrint:
    """Two different faults with the same shape, and two different answers.

    A pitch *below* a micron is a request for finer positioning than the drill
    file and the drawing can render, and the quantiser clamps it to the floor
    with a WARNING — the operator gets the finest grid that renders rather than
    no panel at all. A pitch that is not a whole *number* of microns is not a
    pitch this program can offer at any value, so it is a usage error like every
    other typo, refused before the input is opened.
    """

    def test_a_pitch_below_a_micron_is_clamped_and_said_so(self, fake_source, capsys):
        fake_source(read())

        assert cli.main([str(FIXTURE), "--grid", "0.0001"]) == 1

        assert "[grid-too-fine]" in capsys.readouterr().out

    def test_zero_is_clamped_too_rather_than_switching_snapping_off(self, fake_source, capsys):
        """There is no way to disable snapping: a hole has to be drilled
        somewhere, and "wherever the artwork said" is a position no bit lands on
        twice."""
        fake_source(read())

        assert cli.main([str(FIXTURE), "--grid", "0"]) == 1

        assert "[grid-too-fine]" in capsys.readouterr().out
        assert quantisers_for("--grid", "0").positions.grid_nm == 1_000

    def test_the_clamp_is_reported_once_and_not_once_per_hole(self, fake_source, capsys):
        """The finding is about the configuration, so it is raised once however
        many circles the panel carries."""
        fake_source(read())

        cli.main([str(FIXTURE), "--grid", "0"])

        assert capsys.readouterr().out.count("[grid-too-fine]") == 1

    @pytest.mark.parametrize("grid", ["0.2504", "0.0015"])
    def test_a_pitch_that_is_not_a_whole_micron_is_a_usage_error(
        self, fake_source, capsys, grid
    ):
        fake_source(read())

        assert cli.main([str(FIXTURE), "--grid", grid]) == 3

        err = capsys.readouterr().err
        assert err.startswith("aidrill: error:"), err
        assert "--grid" in err


# ---------------------------------------------------------------------------
# which bits are in the drawer
# ---------------------------------------------------------------------------


def test_the_default_standard_is_metric_and_the_tolerance_is_the_quantisers():
    """The CLI restates neither. ``--drill-standard`` has a default because
    argparse needs one; the matching tolerance has none here at all."""
    snap = quantisers_for().diameters
    assert snap.standard.name == "metric"
    assert snap.standard.sizes_nm == DRILL_STANDARDS["metric"].sizes_nm
    assert snap.tolerance_nm == 250_000


def test_the_declared_standard_reaches_the_quantiser():
    snap = quantisers_for("--drill-standard", "fractional").diameters
    assert snap.standard.name == "fractional"
    assert snap.standard.sizes_nm == DRILL_STANDARDS["fractional"].sizes_nm


def test_the_declared_standard_decides_what_a_hole_is_drilled_with(fake_source, capsys):
    """The flag, proved on the run's output rather than on the object it built.

    6.348 mm is 0.048 from the 6.3 mm metric bit and 0.002 from a 1/4" one, so
    the two standards give different, unmistakable answers — and a CLI that
    accepted ``--drill-standard`` and then built the metric table anyway would
    still print 6.3 here. The fractional drawer also spells the bit as a
    fraction, which is a second thing only the declared standard can produce.
    """
    fake_source(read(holes=[RawHole(0.0, 0.0, 6.348, 4)]))

    assert cli.main([str(FIXTURE), "--drill-standard", "fractional"]) == 0

    assert '⌀1/4"' in capsys.readouterr().out


def test_an_unknown_standard_is_a_usage_error_that_names_the_ones_there_are(
    fake_source, capsys
):
    fake_source(read())
    assert cli.main([str(FIXTURE), "--drill-standard", "whitworth"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "whitworth" in err
    for name in DRILL_STANDARDS:
        assert name in err


def test_a_whitelist_narrows_the_table_to_the_drawer():
    """The sizes are millimetres on the command line and nanometres in the
    table, and the flag is useless unless the CLI converts between them:
    ``--drill-sizes 3.2`` taken literally is a request for a three-nanometre
    bit, which the standard correctly reports as a size it does not stock."""
    snap = quantisers_for("--drill-sizes", "3.2,5,7,12").diameters
    assert snap.standard.sizes_nm == (3_200_000, 5_000_000, 7_000_000, 12_000_000)


def test_a_blacklist_removes_the_bit_that_is_broken():
    snap = quantisers_for("--no-drill-sizes", "7.0").diameters
    assert 7_000_000 not in snap.standard.sizes_nm
    assert len(snap.standard.sizes_nm) == len(DRILL_STANDARDS["metric"].sizes_nm) - 1
    assert 6_900_000 in snap.standard.sizes_nm


def test_the_two_size_flags_combine():
    snap = quantisers_for(
        "--drill-sizes", "3.2,5,7,12", "--no-drill-sizes", "5"
    ).diameters
    assert snap.standard.sizes_nm == (3_200_000, 7_000_000, 12_000_000)


def test_a_narrowed_table_is_what_the_holes_are_actually_quantised_against(
    fake_source, capsys
):
    """With no 7 mm bit in the drawer, a 6.9998 mm hole is drilled with what is.

    Asserted on the run rather than on the drawer it built, because the claim is
    that the narrowed table is what the *measurement* was compared against: a
    CLI that narrowed a copy and quantised against the full series would build
    an identical-looking drawer and still print 7.000.
    """
    fake_source(read(holes=[RawHole(0.0, 0.0, 6.9998, 4)]))

    assert cli.main([str(FIXTURE), "--drill-sizes", "3.2,6.8,12"]) == 0

    out = capsys.readouterr().out
    assert "⌀6.80 mm" in out
    assert "7.000" not in out


def test_a_size_the_standard_does_not_have_is_a_usage_error(fake_source, capsys):
    """``3.33`` is a typo. Read leniently it would give the panel a drawer with
    a bit missing; read as a match it would give it one that does not exist."""
    fake_source(read())
    assert cli.main([str(FIXTURE), "--drill-sizes", "3.2,3.33"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "3.33" in err


def test_a_metric_size_is_not_a_fractional_bit(fake_source, capsys):
    """The refusal is against the declared standard, not against drills at large."""
    fake_source(read())
    assert cli.main([str(FIXTURE), "--drill-standard", "fractional", "--drill-sizes", "3.2"]) == 3
    assert "fractional" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--drill-sizes", "--no-drill-sizes"])
@pytest.mark.parametrize("bad", ["", "3.2,fish", "3,nan", "3.2,0"])
def test_a_malformed_size_list_is_a_usage_error(fake_source, capsys, flag, bad):
    """Both flags, because a bug has more than one spelling: the whitelist and
    the blacklist are two call sites of one parser, and only one of them was
    ever reached by the old ``--drill-sizes`` tests.

    ``nan`` is why finiteness is checked rather than positivity alone: every
    comparison against it is False, so ``size <= 0`` lets it through.
    """
    fake_source(read())
    assert cli.main([str(FIXTURE), flag, bad]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert flag in err


# ---------------------------------------------------------------------------
# which case the panel is for
# ---------------------------------------------------------------------------


def test_a_declared_case_reaches_the_enclosure_quantiser_in_catalogue_form():
    assert quantisers_for("--case", " 1590b ").enclosure.expected_part == "1590B"
    assert quantisers_for().enclosure.expected_part is None


def test_the_declared_case_agreeing_with_the_artwork_is_silent(fake_source, capsys):
    fake_source(read())  # a 99.6 x 50.4 outline, which is a 100.00 x 50.00 1590G
    assert cli.main([str(FIXTURE), "--case", "1590G2"]) == 0


def test_a_case_that_disagrees_with_the_artwork_is_an_error(fake_source, capsys, tmp_path):
    """Exit 2, reported, and no artifact left behind.

    This is what finally makes exit 2 reachable from a correct file: the panel
    parses, every hole is a real bit, and the run is still refused because the
    aluminium in front of the operator is the wrong case.

    Read off the report rather than the machine-readable document, because a run
    with errors deliberately writes no document — matched on the ``[code]`` the
    report prints, never on the wording around it. What the finding *carries* is
    pinned where it is produced, in ``TestDeclaredCase``.
    """
    fake_source(read())
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    assert "[wrong-enclosure]" in capsys.readouterr().out
    assert not doc.exists(), "a document describing the wrong case reached the disk"


def test_an_order_code_is_not_told_it_drew_the_wrong_case(fake_source, capsys):
    """``1590BBBK`` is a real order code — BB body, BK black finish — and the
    single most likely thing an operator types.

    It is not a base designator, so it cannot be checked against a footprint,
    and treating it as one would report ``wrong-enclosure`` on a *correct*
    1590BB panel: a message telling the operator they drew the wrong case when
    they drew the right one. It is a usage error instead, and it says which
    designator the order code is built on so the fix is one retype.
    """
    fake_source(read())
    assert cli.main([str(FIXTURE), "--case", "1590BBBK"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "1590BBBK" in err
    # The whole phrase, not the substring: ``"1590BB" in err`` is satisfied by
    # the echoed order code itself, so it passes just as happily when the
    # suggestion is the wrong one — and suggesting 1590B for a 1590BB panel
    # sends the operator to a case 8 mm narrower.
    assert "did you mean 1590BB?" in err


def test_a_part_number_from_nowhere_is_a_usage_error(fake_source, capsys):
    """No suggestion to make, and none invented: 1590ZZ resembles nothing."""
    fake_source(read())
    assert cli.main([str(FIXTURE), "--case", "1590ZZ"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "1590ZZ" in err


def test_a_panel_that_is_no_hammond_case_still_gets_its_drill_data(fake_source, capsys):
    """A folded-aluminium one-off, or any of the enclosures we do not stock.

    The exit code is asserted where an operator actually meets it, because that
    is the number a Makefile branches on: **1**, not 2. "We have never heard of
    your enclosure" is a statement about this tool's 22-footprint catalogue, and
    a panel with no reference layer at all exits 0 — so refusing this one would
    punish the operator for having drawn their outline. The finding is reported,
    the outline keeps the size it was measured at, and the run goes on.
    """
    fake_source(read(reference=RawOutline(200.0, 100.0)))

    assert cli.main([str(FIXTURE)]) == 1

    out = capsys.readouterr().out
    assert "[unknown-enclosure]" in out
    # The outline is left as drawn, not snapped to the nearest thing we stock.
    assert report_field(out, "reference").startswith("200.000 x 100.000 mm")
    assert "(not identified)" in out
    assert "HOLES (3)" in out, "the drill data went missing with the enclosure"


def test_an_empty_case_is_told_it_is_empty(fake_source, capsys):
    """``--case "$CASE"`` with ``CASE`` unset is a Makefile away, and the answer
    to it must not be a sentence about ``''`` not being in the catalogue — the
    operator would go looking for a part number they never typed."""
    fake_source(read())
    assert cli.main([str(FIXTURE), "--case", "  "]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "needs a part number" in err


def test_the_case_is_checked_before_the_file_is_even_opened(capsys):
    """A typo costs no PDF parse, and — the point — it is reported *as* a typo.

    The file here does not exist, so an unvalidated ``--case`` would surface as
    an I/O failure instead, and the operator would go looking at the wrong end
    of the command line.
    """
    assert cli.main(["/no/such/panel.ai", "--case", "1590ZZ"]) == 3
    assert "1590ZZ" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------


def test_exit_zero_when_clean(fake_source, capsys):
    fake_source(read())
    assert cli.main([str(FIXTURE)]) == 0


def test_info_diagnostics_do_not_change_the_exit_code(fake_source, capsys):
    fake_source(read(diagnostics=[Diagnostic.info("note", "just so you know")]))
    assert cli.main([str(FIXTURE)]) == 0


def test_exit_one_on_warnings(fake_source, capsys):
    fake_source(read(diagnostics=[Diagnostic.warning("something", "watch out")]))
    assert cli.main([str(FIXTURE)]) == 1


def test_exit_two_on_errors(fake_source, capsys):
    fake_source(
        read(
            diagnostics=[
                Diagnostic.warning("something", "watch out"),
                Diagnostic.error("bad", "that will not drill"),
            ]
        )
    )
    assert cli.main([str(FIXTURE)]) == 2


def test_exit_code_comes_from_worst_severity(fake_source, capsys):
    for severity, expected in [
        (Severity.INFO, 0),
        (Severity.WARNING, 1),
        (Severity.ERROR, 2),
    ]:
        fake_source(read(diagnostics=[Diagnostic(severity, "c", "m")]))
        assert cli.main([str(FIXTURE)]) == expected


# ---------------------------------------------------------------------------
# usage and I/O failures — exit 3, never a traceback
# ---------------------------------------------------------------------------


def test_no_arguments_is_a_usage_error(capsys):
    assert cli.main([]) == 3


def test_argparse_rejection_is_not_mistaken_for_our_validation(fake_source, capsys):
    """The two rejections are told apart by shape, because nothing else does it.

    ``--drill-sizes -3.2,7`` and ``--drill-sizes 3.33`` both exit 3 and both put
    the string ``--drill-sizes`` on stderr — argparse's own error line even
    carries the same ``aidrill: error:`` prefix, since it is ``parser.prog``.
    Substring matching therefore cannot separate them however it is spelled;
    only the usage banner can, and only at the start of the stream. That is what
    is asserted, and it is what stops a test claiming to exercise our validation
    while argparse quietly satisfies it first.

    A stray leading minus is the version argparse claims, and only because the
    rest of the field stops it looking like a negative number: ``-5`` alone
    *does* reach our own check, which is precisely why "starts with a dash"
    cannot be assumed to mean "argparse handled it".
    """
    fake_source(read())

    assert cli.main([str(FIXTURE), "--drill-sizes", "-3.2,7"]) == 3
    argparse_err = capsys.readouterr().err
    assert argparse_err.startswith("usage:")  # argparse's, never ours
    # Why ``startswith`` and not ``in`` — argparse says this too:
    assert "aidrill: error:" in argparse_err
    assert "--drill-sizes" in argparse_err

    assert cli.main([str(FIXTURE), "--drill-sizes", "3.33"]) == 3
    ours = capsys.readouterr().err
    assert ours.startswith("aidrill: error:")
    assert "usage:" not in ours


@pytest.mark.parametrize("spec", ["excellon", "=out.drl", "excellon="])
def test_malformed_emit_is_a_usage_error(fake_source, capsys, spec):
    fake_source(read())
    assert cli.main([str(FIXTURE), "--emit", spec]) == 3
    assert "FORMAT=PATH" in capsys.readouterr().err


def test_unknown_emit_format_is_a_usage_error(fake_source, tmp_path, capsys):
    fake_source(read())
    assert cli.main([str(FIXTURE), "--emit", f"dxf={tmp_path / 'x.dxf'}"]) == 3
    err = capsys.readouterr().err
    assert "dxf" in err
    assert "Traceback" not in err


def test_library_errors_are_reported_cleanly(fake_source, capsys):
    fake_source(LayerNotFoundError("Drill", ["Background", "Graphics"]))
    assert cli.main([str(FIXTURE)]) == 3
    err = capsys.readouterr().err
    assert "Drill" in err and "Background" in err
    assert "Traceback" not in err


def test_empty_layer_error_is_reported_cleanly(fake_source, capsys):
    fake_source(EmptyLayerError("Drill"))
    assert cli.main([str(FIXTURE)]) == 3
    assert "Traceback" not in capsys.readouterr().err


def test_emitter_error_is_reported_cleanly(fake_source, tmp_path, capsys):
    """LOWER_LEFT excellon without a reference outline raises EmitterError."""
    fake_source(read(reference=None))
    assert cli.main([str(FIXTURE), "--emit", f"excellon={tmp_path / 'x.drl'}"]) == 3
    err = capsys.readouterr().err
    assert "Traceback" not in err


def test_a_failing_emitter_writes_nothing_at_all(fake_source, tmp_path, capsys):
    """All or nothing: a half-written output set is worse than no output set.

    ``excellon`` defaults to a lower-left origin, which needs a reference
    outline; with none it raises. The ``json`` target is named first, so a CLI
    that writes as it goes leaves ``a.json`` on disk beside a missing ``b.drl``
    and an exit code of 3 — a stale artifact that looks like a good run.
    """
    fake_source(read(reference=None))
    doc = tmp_path / "a.json"
    drl = tmp_path / "b.drl"

    code = cli.main([str(FIXTURE), "--emit", f"json={doc}", "--emit", f"excellon={drl}"])

    assert code == 3
    assert not doc.exists(), "the JSON artifact survived a failed run"
    assert not drl.exists()
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.count("error:") == 1  # reported once, not once per target


def test_an_erroring_run_writes_no_artifact_at_all(fake_source, tmp_path, capsys):
    """The expensive failure, in the one artifact nobody reads with their eyes.

    A panel with a 30 mm cut-out loses that hole in the quantisation phase: no
    bit makes it, so it is an ERROR and the hole is dropped. Every emitter then
    faithfully describes a *two*-hole panel. The machine-readable document and
    the drawing's NOTES both carry the finding, but the Excellon format renders
    no diagnostics at all — so the file that goes to the machine is silently
    short a hole, and it looks exactly like a good one.

    An exit code the operator may not read is not enough of a guard. A run with
    errors produces no artifacts, so there is nothing to load by mistake.
    """
    fake_source(
        read(
            holes=[
                RawHole(-20.0, 18.0, 7.0, 4),
                RawHole(0.0, 18.0, 30.0, 1),  # no bit makes this
                RawHole(20.0, 18.0, 5.0, 9),
            ]
        )
    )
    drl = tmp_path / "panel.drl"
    doc = tmp_path / "panel.txt"

    code = cli.main(
        [str(FIXTURE), "--emit", f"excellon={drl}", "--emit", f"json={doc}"]
    )

    assert code == 2
    assert not drl.exists(), "a drill file missing a hole reached the disk"
    assert not doc.exists()

    captured = capsys.readouterr()
    assert "[unknown-diameter]" in captured.out, "the finding was not reported either"
    assert str(drl) in captured.out, "the operator is not told which artifact was withheld"
    assert captured.err == "", "a refusal is a result, not a failure to run"


def test_a_warning_still_gets_its_artifacts(fake_source, tmp_path, capsys):
    """Only ERROR withholds output. A warning is a thing to look at, not a
    reason to leave the operator with nothing — and after ``unknown-enclosure``
    became a warning, this is the difference between "we do not stock your case"
    and "you get no drill file"."""
    fake_source(read(diagnostics=[Diagnostic.warning("something", "watch out")]))
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--emit", f"json={doc}"]) == 1
    assert doc.exists() and doc.read_text().strip()


def test_every_target_is_written_on_the_happy_path(fake_source, tmp_path, capsys):
    """Rendering to memory first must not cost anyone their artifacts."""
    fake_source(read())
    targets = {
        "json": tmp_path / "out.json",
        "excellon": tmp_path / "out.drl",
        "drawing-svg": tmp_path / "out.svg",
    }
    argv = [str(FIXTURE)]
    for name, path in targets.items():
        argv += ["--emit", f"{name}={path}"]

    assert cli.main(argv) == 0

    out = capsys.readouterr().out
    for name, path in targets.items():
        assert path.exists(), f"{name} was not written"
        assert path.read_text().strip(), f"{name} wrote an empty file"
        assert str(path) in out


def test_io_failure_is_exit_three(fake_source, tmp_path, capsys):
    fake_source(read())
    target = tmp_path / "no-such-dir" / "out.drl"
    assert cli.main([str(FIXTURE), "--emit", f"excellon={target}"]) == 3
    assert "Traceback" not in capsys.readouterr().err


def test_missing_input_file_is_exit_three(tmp_path, capsys):
    missing = tmp_path / "nope.ai"
    assert cli.main([str(missing)]) == 3
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def test_report_shows_source_holes_tools_and_diagnostics(fake_source, capsys):
    fake_source(read(diagnostics=[Diagnostic.warning("something", "watch out")]))
    cli.main([str(FIXTURE)])
    out = capsys.readouterr().out

    assert "fake.ai" in out
    assert "Drill" in out and "Background" in out
    # 100 × 50, not the 99.6 × 50.4 the artwork measured: the enclosure is
    # identified on every panel, and the report states the catalogue's own
    # figures because those are what the holes are positioned against.
    assert "100.000" in out and "50.000" in out
    assert "7.000" in out and "5.000" in out  # hole diameters
    assert "T1" in out and "T2" in out  # tool summary
    assert "something" in out and "watch out" in out


def report_diagnostic_groups(out: str) -> dict[str, list[str]]:
    """``{"error": ["unknown-diameter"], …}`` — the DIAGNOSTICS block as printed.

    Read back out of the rendered report and keyed on ``code``, because the
    claim under test is the *grouping*: an assertion that a finding appears
    somewhere in the output passes just as happily when it is printed under
    every heading at once.
    """
    groups: dict[str, list[str]] = {}
    current: list[str] | None = None
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("DIAGNOSTICS"))
    for line in lines[start + 1:]:
        heading = re.fullmatch(r"  (\w+) \(\d+\)", line)
        entry = re.match(r"    \[([\w-]+)\]", line)
        if heading is not None:
            current = groups.setdefault(heading.group(1), [])
        elif entry is not None and current is not None:
            current.append(entry.group(1))
        elif not line.startswith(" "):
            break
    return groups


def test_each_finding_is_printed_once_under_its_own_severity(fake_source, capsys):
    """One finding of each severity, one rendering of each.

    ``of_severity`` was invertible: negate its predicate and every finding was
    printed twice, under two headings that were both wrong, with the summary
    line claiming three errors — while the exit code, which comes from
    ``worst_severity`` down another path, went on saying "warnings". The report
    and the exit code are two renderings of one set of findings, and the whole
    point of this project is that two renderings cannot be allowed to disagree.
    """
    fake_source(
        read(
            diagnostics=[
                Diagnostic.warning("off-grid", "hole 4 moved 0.12 mm"),
                Diagnostic.error("unknown-diameter", "⌀30.0 mm is no bit in the drawer"),
                Diagnostic.info("duplicate-hole", "two circles in one place"),
            ]
        )
    )

    assert cli.main([str(FIXTURE)]) == 2

    out = capsys.readouterr().out
    assert "DIAGNOSTICS (3)" in out
    assert "  error (1)" in out and "  warning (1)" in out and "  info (1)" in out
    assert report_diagnostic_groups(out) == {
        "error": ["unknown-diameter"],
        "warning": ["off-grid"],
        "info": ["duplicate-hole"],
    }
    assert out.splitlines()[-1] == "3 holes, 2 tools, 1 error, 1 warning, 1 info"


def test_the_summary_counts_every_finding_of_a_severity(fake_source, capsys):
    """The counts are plural where they should be, and a severity nobody
    reported is not listed at all — a report that ends "0 errors" invites the
    reader to skim past the line that says how many there were."""
    fake_source(
        read(
            diagnostics=[
                Diagnostic.warning("off-grid", "hole 4 moved 0.12 mm"),
                Diagnostic.warning("unknown-enclosure", "113 × 60 is no catalogue footprint"),
            ]
        )
    )

    assert cli.main([str(FIXTURE)]) == 1

    assert capsys.readouterr().out.splitlines()[-1] == "3 holes, 2 tools, 2 warnings"


def test_tool_summary_counts_come_from_the_model(capsys):
    """The ``xN`` column is ``DrillData.tool_counts()``, not a third re-count.

    Counting holes per nominal diameter is one computation shared by the CLI
    summary, the JSON ``count`` field and the drawing's QTY column. A subclass
    that answers ``tool_counts()`` differently must change the report; if the
    report ignores it, ``cli.py`` is counting for itself again.
    """
    calls = []

    class SpyData(DrillData):
        def tool_counts(self):
            calls.append(tuple(self.tools()))
            return {diameter: 99 for diameter in self.tools()}

    data = SpyData(
        holes=document().holes,
        reference=ReferenceOutline(112_000_000, 61_000_000),
        source=SourceInfo(path="fake.ai"),
    )

    lines = cli.format_tools(data)

    assert calls, "cli.format_tools never asked the model for its tool counts"
    assert [line for line in lines if "x99" in line], lines
    assert not [line for line in lines if "x2" in line or "x1" in line], lines


def report_tool_labels(lines) -> dict[int, str]:
    """``{1: '⌀13/64"'}`` — the ``TOOLS`` block as printed, tool number to spelling."""
    labels = {}
    for line in lines:
        match = re.fullmatch(r"  T(\d+)\s+(.+?)\s+x\d+", line)
        if match is not None:
            labels[int(match.group(1))] = match.group(2)
    return labels


def report_tool_diameters(lines) -> list[str]:
    """The rendered diameter of each ``TOOLS`` line, as printed."""
    return [
        match.group(1)
        for match in (re.fullmatch(r"⌀([\d.]+) mm", label) for label in report_tool_labels(lines).values())
        if match
    ]


def test_the_tools_report_never_prints_one_diameter_as_two_tools():
    """The founding defect, in the renderer a human reads.

    ``T2C7.000`` beside ``T3C7.000`` is what ADR-0001 exists to prevent, and the
    Excellon emitter now refuses to write it. The CLI's ``TOOLS`` block had the
    same trap for the same reason — its own fixed 3 dp — and printed::

        T2   dia 7.000 mm   x1
        T3   dia 7.000 mm   x1

    for two genuinely distinct nominals, which is the report stating something
    false. The precision follows the values present, so distinct nominals stay
    distinguishable however tight the tolerance was.
    """
    data = document(
        holes=[
            Hole.from_measurement(-20_000_000, 18_000_000, 6_999_800, index=6),
            Hole.from_measurement(20_000_000, 18_000_000, 7_000_000, index=2),
        ]
    )
    assert len(data.tools()) == 2  # the fixture must actually pose the problem

    printed = report_tool_diameters(cli.format_tools(data))

    assert len(printed) == 2
    assert len(set(printed)) == 2, f"two tools printed the same diameter: {printed}"


def test_the_tools_report_keeps_its_usual_three_decimals():
    """Widening is for the collision, not for every panel: an ordinary run must
    read exactly as it always did."""
    assert report_tool_diameters(cli.format_tools(document())) == ["5.000", "7.000"]


def test_the_tools_block_spells_a_bit_the_way_the_standard_that_ran_spells_it():
    """The spelling comes from provenance, exactly as the drawing's schedule
    takes it, because a fractional bit has no honest millimetre name.

    ``⌀5.159 mm`` is a size in no drawer on earth: its nearest purchasable
    neighbour is a 5.2 mm metric bit, which is the wrong hole. 13/64" is the
    number stamped on the bit the machinist picks up.
    """
    data = document(
        holes=[
            Hole.from_measurement(-20_000_000, 18_000_000, 7_143_750, index=3),
            Hole.from_measurement(0, -18_750_000, 5_159_375, index=1),
        ],
        processing=[quantised_against("fractional", size_count=64)],
    )

    assert report_tool_labels(cli.format_tools(data)) == {1: '⌀13/64"', 2: '⌀9/32"'}


def test_a_recorded_standard_the_registry_does_not_hold_is_not_a_standard():
    """A hand-built drawer, or a document written by a later version of this
    tool: the name resolves to nothing and the report states millimetres rather
    than inventing a spelling for a series it cannot see. The same fallback
    carries a ``DrillData`` that never went through the quantiser at all."""
    assert report_tool_labels(cli.format_tools(document())) == {
        1: "⌀5.000 mm",
        2: "⌀7.000 mm",
    }

    data = document(processing=[quantised_against("whitworth")])

    assert report_tool_labels(cli.format_tools(data)) == {1: "⌀5.000 mm", 2: "⌀7.000 mm"}


def test_a_standards_own_spelling_still_may_not_print_one_diameter_as_two_tools():
    """The same trap, one layer up: the metric drawer spells to 2 dp, so a
    document carrying two nominals that agree to two decimals would be stamped
    ``⌀7.00 mm`` twice under two tool numbers.

    The CLI cannot build such a document — every nominal it produces comes from
    a table whose sizes are further apart than that — but a library consumer
    hands the report whatever it likes, and a renderer that is only correct for
    the inputs one entry point happens to produce is not correct.
    """
    data = document(
        holes=[
            Hole.from_measurement(-20_000_000, 18_000_000, 6_999_800, index=6),
            Hole.from_measurement(20_000_000, 18_000_000, 7_000_000, index=2),
        ],
        processing=[quantised_against("metric")],
    )

    printed = report_tool_labels(cli.format_tools(data))

    assert len(set(printed.values())) == 2, f"two tools printed the same diameter: {printed}"


def test_report_shows_raw_values_beside_nominal(fake_source, capsys):
    fake_source(read(holes=[RawHole(-19.9906, 18.0021, 6.9998, 4)]))
    cli.main([str(FIXTURE)])
    out = capsys.readouterr().out
    assert "-20.000" in out  # nominal, after snapping to the grid
    assert "-19.9906" in out  # raw provenance
    assert "6.9998" in out


def report_field(out: str, label: str) -> str:
    """The value of one ``  label   value`` line of the report.

    The label is matched against the whole of its padded column, so that
    ``reference`` cannot be answered by the ``reference layer`` line above it.
    """
    prefix = f"  {label:<17}"
    line = next(line for line in out.splitlines() if line.startswith(prefix))
    return line[len(prefix):].strip()


def test_the_report_shows_the_outline_the_artwork_measured_beside_the_snapped_one(
    fake_source, capsys
):
    """``IdentifyHammondFootprint`` rewrites a real measurement — this panel
    comes to 99.600 × 50.400 and leaves as the catalogue's 100.000 × 50.000 — and
    a report stating only the second sends a nominal size out as though it were
    what the artwork said. The hole table prints ``raw X``/``raw Y`` beside every
    nominal four lines below for exactly this reason; the outline is the same
    question one level up.

    Four decimals on the raw pair and three on the nominal, deliberately: the
    two agree to three, so a report printing both at the same precision would
    show one number twice and prove nothing.
    """
    fake_source(read())

    assert cli.main([str(FIXTURE)]) == 0

    reference = report_field(capsys.readouterr().out, "reference")
    assert "100.000 x 50.000 mm" in reference
    assert "99.6000 x 50.4000 mm" in reference


def test_the_report_states_which_enclosure_the_panel_was_identified_as(fake_source, capsys):
    """A clean run said nothing at all about the enclosure, while the sheet and
    the machine-readable document both carried it.

    A *mismatch* surfaces as a diagnostic, so the silence fell exactly on the
    success case — where confirmation that the artwork is the case the operator
    thinks it is, is the one thing they are looking for.
    """
    fake_source(read())

    assert cli.main([str(FIXTURE)]) == 0

    out = capsys.readouterr().out
    assert "ENCLOSURE" in out
    # Three decimals, like every other length in the report: the catalogue
    # carries Hammond's 0.05 mm figures, and a 1590B printed as "112 x 61" would
    # be indistinguishable from a 1590BS.
    assert report_field(out, "footprint") == "Hammond 1590  100.000 x 50.000 mm"
    assert report_field(out, "candidates") == "1590G, 1590G2"


def test_an_enclosure_nobody_could_identify_is_said_out_loud():
    """A missing line reads as a case nobody wrote down. "This is no footprint we
    stock" is a legitimate outcome — the catalogue holds 26 and the world holds
    rather more — and it is not the same statement as saying nothing."""
    lines = cli.format_enclosure(document())

    assert "ENCLOSURE" in lines
    assert any("not identified" in line for line in lines)


def test_a_declared_part_replaces_the_candidate_list():
    """The question the list asks has been answered, so the report answers it —
    the same rule the drawing's title block follows. A turned panel says so,
    because the catalogue's own orientation is what is printed beside it.

    The footprint is printed as the catalogue holds it — ``119.500 x 94.000``,
    to the same three decimals as every other length in the report. Hammond's
    drawings give 0.05 mm, so rounding a footprint on the way out would print
    1590B and 1590BS as one enclosure.
    """
    data = dataclasses.replace(
        document(),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=119_500_000,
            width_nm=94_000_000,
            candidates=("1590BB", "1590BB2", "1590BBS", "1590C"),
            rotated=True,
            selected_part="1590BB",
        ),
    )

    lines = cli.format_enclosure(data)

    assert (
        report_field("\n".join(lines), "footprint")
        == "Hammond 1590  119.500 x 94.000 mm (rotated)"
    )
    assert report_field("\n".join(lines), "part") == "1590BB"
    assert not [line for line in lines if "candidates" in line]


def test_the_hole_table_names_holes_by_identity_not_by_position(fake_source, capsys):
    """The ``No.`` column is ``Hole.index``, the identity the diagnostics and the
    drawing's balloons both use.

    The fixture's indices are 4, 1, 9 — not ``0, 1, 2`` and not in order, because
    position and identity agree on a list numbered from zero and a test written
    over one cannot tell which column it is reading. Under positional numbering
    this table would read 1, 2, 3, so every assertion below fails.
    """
    fake_source(
        read(
            holes=[
                RawHole(-20.0, 18.0, 7.0, 4),
                RawHole(0.0, 18.0, 7.0, 1),
                RawHole(20.0, 18.0, 7.0, 9),
            ]
        )
    )
    cli.main([str(FIXTURE)])
    numbers = [
        int(line.split()[0])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("  ") and line.split() and line.split()[0].isdigit()
    ]

    assert numbers == [4, 1, 9]


def test_verbose_reports_every_stage_the_cli_built(fake_source, capsys):
    """The list of stages comes from ``build_pipeline``, so a stage added there
    is covered here without anyone remembering to add it twice."""
    fake_source(read())
    cli.main([str(FIXTURE)])
    quiet = capsys.readouterr().out
    assert "deduplicate" not in quiet

    fake_source(read())
    cli.main([str(FIXTURE), "-v"])
    loud = capsys.readouterr().out
    for stage in pipeline_for():
        assert stage.name in loud, f"--verbose said nothing about {stage.name}"
    assert len(loud) > len(quiet)


def test_verbose_reports_the_quantisation_phase_as_well_as_the_stages(fake_source, capsys):
    """The phase is where holes are dropped and most findings are made.

    A listing that jumped from the source's hole count straight to dedupe's
    would leave the operator with nothing to look at for the step that refused
    their 30 mm cut-out — which is the step they most need to see.
    """
    fake_source(
        read(
            holes=[
                RawHole(-20.0, 18.0, 7.0, 4),
                RawHole(0.0, 18.0, 30.0, 1),  # no bit makes this
            ]
        )
    )

    cli.main([str(FIXTURE), "-v"])

    line = next(
        line for line in capsys.readouterr().out.splitlines() if "quantise" in line
    )
    assert "1 holes" in line
    assert "-1 holes" in line
    assert "unknown-diameter" in line


def test_the_traced_path_folds_through_the_same_pipeline_as_the_plain_one():
    """``--verbose`` must not be a second, divergent fold.

    It was one: an ``apply`` loop of its own, identical to ``Pipeline.run`` right
    up until the fold gained a second responsibility. A verbose run then produced
    data with no processing history at all, and the drawing made from it could
    not say what grid the holes had been snapped to.
    """
    args = cli.build_parser().parse_args(["panel.ai", "--grid", "0.5"])
    pipeline = cli.build_pipeline(args)
    data = document()

    plain = cli.run_pipeline(pipeline, data)
    traced = cli.run_pipeline(pipeline, data, trace=lambda *_: None)

    assert traced.processing == plain.processing
    assert [run.name for run in traced.processing] == [stage.name for stage in pipeline]
    assert traced.last_run("sort").get("key") == "default"


def test_the_grid_reaches_the_drawing_through_the_quantiser_not_the_options(
    fake_source, tmp_path
):
    """``--grid`` is handed to ``SnapPositions``, and to nothing else.

    It used to be copied into ``DrawingOptions`` as well, which made the sheet's
    stamp agree with the flag rather than with the holes. Asserted on the
    emitted SVG, since agreement between two artifacts is not visible in the
    objects they were built from.
    """
    fake_source(read())
    svg = tmp_path / "out.svg"
    # 1, not 0: a 0.5 mm grid moves a hole far enough to raise ``off-grid``.
    assert cli.main([str(FIXTURE), "--grid", "0.5", "--emit", f"drawing-svg={svg}"]) == 1
    text = svg.read_text()
    assert "GRID 0.5 mm" in text
    assert "GRID 0.25 mm" not in text


def test_the_output_settings_carry_no_grid():
    """One route from ``--grid`` to the sheet, so there is nothing to diverge."""
    assert "grid" not in {f.name for f in dataclasses.fields(cli.OutputSettings)}


def test_title_reaches_the_drawing(fake_source, tmp_path):
    fake_source(read())
    svg = tmp_path / "out.svg"
    assert cli.main([str(FIXTURE), "--title", "TAR - FRONT PANEL", "--emit", f"drawing-svg={svg}"]) == 0
    assert "TAR - FRONT PANEL" in svg.read_text()


# ---------------------------------------------------------------------------
# reading the artifacts back, as the shop floor would
# ---------------------------------------------------------------------------

SVG = "{http://www.w3.org/2000/svg}"


def drl_tool_diameters(text: str) -> dict[int, float]:
    """``T1C5.000`` → ``{1: 5.0}``, straight out of the drill file's tool table."""
    return {
        int(number): float(diameter)
        for number, diameter in re.findall(r"^T(\d+)C([\d.]+)\s*$", text, flags=re.MULTILINE)
    }


def drl_holes(text: str) -> list[tuple[int, float, float]]:
    """``[(tool, x, y)]`` in the order the machine will drill them."""
    holes: list[tuple[int, float, float]] = []
    tool = 0
    for line in text.splitlines():
        select = re.fullmatch(r"T(\d+)", line.strip())
        if select is not None:
            tool = int(select.group(1))
            continue
        move = re.fullmatch(r"X(-?[\d.]+)Y(-?[\d.]+)", line.strip())
        if move is not None:
            holes.append((tool, float(move.group(1)), float(move.group(2))))
    return holes


def svg_schedule_rows(root: ET.Element) -> list[tuple[int, float, float, float, int]]:
    """``[(no, x, y, diameter, tool)]`` from the drawing's hole schedule.

    **The ⌀ cell is matched whole, and metric-only on purpose.** The schedule
    spells a diameter the way the drill standard that ran spells it — ``⌀7.00
    mm`` from the metric drawer, ``⌀9/32"`` from the fractional one, because
    1/64" is 0.396875 mm and no decimal-millimetre label for it is honest. This
    test drives the CLI with its default standard, so metric is the only
    spelling that can reach here, and a fractional label arriving would mean the
    run under test had changed. That is worth an assertion naming the string it
    could not read: coercing with ``float`` instead gave a bare ``ValueError``
    from inside a helper, which is a poor failure mode for the one test that
    compares two emitted artifacts. ``svg_tool_summary`` below pins the same
    format for the same reason, and this now matches its idiom.
    """
    rows = []
    for group in root.iter(SVG + "g"):
        if group.get("class") != "sched-row":
            continue
        number, x, y, diameter, tool = [text.text or "" for text in group.iter(SVG + "text")]
        match = re.fullmatch(r"⌀([\d.]+) mm", diameter)
        assert match is not None, f"unreadable metric schedule diameter {diameter!r}"
        rows.append(
            (
                int(number),
                float(x),
                float(y),
                float(match.group(1)),
                int(tool.lstrip("T")),
            )
        )
    return rows


def svg_tool_summary(root: ET.Element) -> dict[int, tuple[float, int]]:
    """``{tool: (diameter, qty)}`` from the schedule's per-tool summary lines."""
    summary = {}
    for text in root.iter(SVG + "text"):
        if text.get("class") != "sched-summary":
            continue
        match = re.fullmatch(r"T(\d+)\s+⌀([\d.]+) mm\s+QTY (\d+)", text.text or "")
        assert match is not None, f"unreadable summary line {text.text!r}"
        summary[int(match.group(1))] = (float(match.group(2)), int(match.group(3)))
    return summary


def svg_tool_labels(root: ET.Element) -> dict[int, str]:
    """``{tool: "⌀13/64\\""}`` — how the sheet spells each bit, whatever drawer
    it came out of. ``svg_tool_summary`` above reads the same lines but coerces
    the diameter to a float, which only a metric run can survive."""
    labels = {}
    for text in root.iter(SVG + "text"):
        if text.get("class") != "sched-summary":
            continue
        match = re.fullmatch(r"T(\d+)  (.+)  QTY \d+", text.text or "")
        assert match is not None, f"unreadable summary line {text.text!r}"
        labels[int(match.group(1))] = match.group(2)
    return labels


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_console_and_the_sheet_spell_a_bit_the_same_way(tmp_path, capsys):
    """Two renderings of one tool table, parsed back out of what was printed.

    The console spelled a fractional bit in decimal millimetres while the sheet
    spelled it as a fraction: ``dia 5.159 mm`` beside ``⌀13/64"``, for one bit,
    in one run. 5.159 mm is a size in no drawer, and the operator who goes
    looking for it comes back with the 5.2 mm metric bit next to it — the wrong
    hole, drilled from a document that never said anything false about the
    number, only about how to buy it.

    Asserted across the emitted bytes rather than in memory, because both
    renderings read the same ``DrillData`` and would agree there under exactly
    the bug this is written to catch.
    """
    svg = tmp_path / "tar.svg"

    code = cli.main(
        [
            str(FIXTURE),
            # The fixture fits two footprints, so its case is declared on every
            # real-file run below; see the pair at the end of this file.
            "--case",
            "1590B",
            "--drill-standard",
            "fractional",
            "--emit",
            f"drawing-svg={svg}",
        ]
    )

    assert code == 1  # a duplicate hole on the fixture, and nothing worse
    console = report_tool_labels(capsys.readouterr().out.splitlines())
    assert console == svg_tool_labels(ET.parse(svg).getroot())
    assert console == {1: '⌀13/64"', 2: '⌀9/32"'}


def svg_balloon_numbers(root: ET.Element) -> list[int]:
    return [
        int(text.text or "")
        for text in root.iter(SVG + "text")
        if text.get("class") == "balloon-no"
    ]


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_drill_file_and_the_drawing_agree_with_each_other(tmp_path, capsys):
    """Two artifacts, one run, parsed back as text: they must say the same thing.

    This is the failure the rewrite exists to prevent — the drawing and the
    Excellon file legitimately disagreeing, because each derived tool numbers,
    quantities and hole order for itself. Everything below is read out of the
    emitted bytes, never out of the Python objects: what is asserted is what
    reaches the shop floor.
    """
    drl = tmp_path / "tar.drl"
    svg = tmp_path / "tar.svg"

    assert (
        cli.main(
            [
                str(FIXTURE),
                "--case",
                "1590B",
                "--emit",
                f"excellon={drl}",
                "--emit",
                f"drawing-svg={svg}",
            ]
        )
        == 1
    )

    drill_text = drl.read_text(encoding="utf-8")
    root = ET.fromstring(svg.read_text(encoding="utf-8"))

    # 1. the tool tables are the same map, and no diameter is defined twice
    summary = svg_tool_summary(root)
    drill_tools = drl_tool_diameters(drill_text)
    drawing_tools = {tool: diameter for tool, (diameter, _) in summary.items()}
    assert drill_tools == drawing_tools == {1: 5.0, 2: 7.0}
    assert len(set(drill_tools.values())) == len(drill_tools)

    # 2. the hole counts agree — in total, and tool by tool
    holes = drl_holes(drill_text)
    rows = svg_schedule_rows(root)
    balloons = svg_balloon_numbers(root)
    assert len(holes) == len(rows) == len(balloons) == 7
    assert Counter(tool for tool, _, _ in holes) == {
        tool: quantity for tool, (_, quantity) in summary.items()
    }
    for _, _, _, diameter, tool in rows:
        assert drawing_tools[tool] == diameter  # every row uses its own tool's bit

    # 3. the drilling order is the balloon order, grouped by tool, and both name
    # holes by ``Hole.index``. The literal is the fixture's traversal order, which
    # is deliberately not 1..7: were either artifact numbering by position in its
    # own list, this would read 1, 2, 3, … and pass while naming different holes
    # than every diagnostic does.
    assert balloons == [number for number, *_ in rows] == [2, 3, 4, 6, 7, 0, 1]
    # The drill file is in a lower-left frame and the schedule in the centre
    # frame; the two differ by a pure translation, so the corner of the bounding
    # box recovers it without the test knowing the panel size.
    dx = min(x for _, x, _ in holes) - min(row[1] for row in rows)
    dy = min(y for _, _, y in holes) - min(row[2] for row in rows)
    by_position = {
        (round(row[1] + dx, 3), round(row[2] + dy, 3), row[4]): row[0] for row in rows
    }
    drilled = [by_position[(round(x, 3), round(y, 3), tool)] for tool, x, y in holes]
    assert drilled == [row[0] for row in sorted(rows, key=lambda row: row[4])]


# ---------------------------------------------------------------------------
# end to end against the fixture (SPEC §9)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_end_to_end_on_the_fixture(tmp_path, capsys):
    drl = tmp_path / "tar.drl"
    svg = tmp_path / "tar.svg"
    doc = tmp_path / "tar.json"

    code = cli.main(
        [
            str(FIXTURE),
            "--case",
            "1590B",
            "--title",
            "TAR - FRONT PANEL",
            "--emit",
            f"excellon={drl}",
            "--emit",
            f"drawing-svg={svg}",
            "--emit",
            f"json={doc}",
        ]
    )

    # one duplicate-hole warning, nothing worse
    assert code == 1

    assert drl.exists() and svg.exists() and doc.exists()
    assert drl.read_text().startswith("M48")
    ET.fromstring(svg.read_text())  # parses as XML

    document = json.loads(doc.read_text())
    assert len(document["holes"]) == 7
    assert len(document["tools"]) == 2
    assert sorted(t["diameter"] for t in document["tools"]) == [5.0, 7.0]

    codes = [d["code"] for d in document["diagnostics"]]
    assert codes.count("duplicate-hole") == 1
    assert "off-grid" not in codes

    # exactly two tool definitions in the drill file, no diameter repeated
    tools = re.findall(r"^T(\d+)C([\d.]+)", drl.read_text(), flags=re.MULTILINE)
    diameters = [d for _, d in tools]
    assert len(tools) == 2
    assert len(set(diameters)) == 2

    out = capsys.readouterr().out
    assert "duplicate-hole" in out
    assert str(drl) in out and str(svg) in out


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_grid_half_millimetre_raises_two_off_grid_warnings(tmp_path, capsys):
    doc = tmp_path / "tar.json"
    code = cli.main(
        [str(FIXTURE), "--case", "1590B", "--grid", "0.5", "--emit", f"json={doc}"]
    )
    assert code == 1

    codes = [d["code"] for d in json.loads(doc.read_text())["diagnostics"]]
    assert codes.count("off-grid") == 2


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_is_identified_as_the_case_it_was_drawn_for(capsys):
    """The 1590B footprint, and the artwork's own measurement kept beside it.

    The real file, parsed by the real source and quantised by the real phase:
    the artwork measures 113.000 × 60.000 and the drawing says 1590B is
    112.40 × 60.50, so a catalogue figure printed beside the measurement it
    replaced is the whole claim. Without ``raw`` the report would state a
    datasheet number as though it were what the artwork said, and nothing on the
    page would disagree.

    ``--case`` is required rather than optional here, which is the pair below.
    """
    assert cli.main([str(FIXTURE), "--case", "1590B"]) == 1

    out = capsys.readouterr().out
    reference = report_field(out, "reference")
    assert reference.startswith("112.400 x 60.500 mm")
    assert re.search(r"raw 113\.0000 x 60\.000\d mm", reference), reference
    assert report_field(out, "footprint") == "Hammond 1590  112.400 x 60.500 mm"
    assert report_field(out, "part") == "1590B"
    assert report_diagnostic_groups(out) == {"warning": ["duplicate-hole"]}


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_undeclared_is_refused_and_writes_nothing(tmp_path, capsys):
    """The other half, and the behaviour change the fine catalogue brought.

    ``tar.ai`` is a real 1590B and used to be the one panel this tool could run
    with no arguments at all. Hammond's own 0.05 mm figures separate 1590BS
    (112.00 × 60.50) from 1590B (112.40 × 60.50), and the artwork's 113.000 ×
    60.000 sits within tolerance of both — 1.000 mm from one and 0.600 mm from
    the other. No tolerance tells those apart while still admitting a panel
    measured a millimetre off, so the honest answer is to refuse and say which
    two enclosures fit.

    Asserted against the *file system*, not only the exit code: ERROR withholds
    every artifact, and a drill file for the wrong one of two enclosures 0.4 mm
    apart is exactly the artifact that looks perfectly well-formed.
    """
    doc = tmp_path / "tar.json"

    assert cli.main([str(FIXTURE), "--emit", f"json={doc}"]) == 2

    out = capsys.readouterr().out
    assert "[ambiguous-enclosure]" in out
    assert "1590BS" in out and "1590B2" in out
    assert not doc.exists(), "a document naming one of two enclosures reached the disk"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_declared_as_a_case_it_does_not_fit_exits_two(tmp_path, capsys):
    """The real fixture, end to end: exit 2 and nothing on disk to load.

    ``unmatched-enclosure`` rather than ``wrong-enclosure``, and the difference
    is the point: two footprints fit this outline and neither is a 1590BB, so
    nothing was identified and an accusation about what *was* drawn would be
    unfounded. ``wrong-enclosure`` is reachable from a panel that matches one
    footprint, which is asserted where the source is a stand-in.
    """
    doc = tmp_path / "tar.json"
    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    assert "[unmatched-enclosure]" in capsys.readouterr().out
    assert not doc.exists()


# ---------------------------------------------------------------------------
# the error hierarchy
# ---------------------------------------------------------------------------


def test_layer_not_found_lists_the_layers_that_were_there():
    """The operator's next move is reading the list, so the list is the message."""
    error = LayerNotFoundError("Drill", ["Graphics", "Background"])
    assert error.wanted == "Drill"
    assert error.available == ("Graphics", "Background")
    assert "Background, Graphics" in str(error)


def test_layer_not_found_says_so_when_there_were_no_layers_at_all():
    assert "(none)" in str(LayerNotFoundError("Drill", []))


def test_empty_layer_blames_the_missing_paint_when_no_paths_were_seen():
    """The Illustrator trap: unpainted artwork never reaches the PDF stream."""
    error = EmptyLayerError("Drill")
    assert error.layer == "Drill"
    assert error.path_count == 0
    assert "stroke" in str(error)


def test_empty_layer_blames_the_shapes_when_paths_were_seen():
    """Two faults, two remedies. Paths that are not circles are a drawing problem,
    and telling that operator to add a stroke sends them to the wrong place.

    The count is a constructor argument because it was previously a rewrite of
    ``.args`` at the call site, which left half of this module's message outside
    this module.
    """
    error = EmptyLayerError("Drill", path_count=1)
    assert error.path_count == 1
    message = str(error)
    assert "1 path" in message
    assert "circle" in message
    assert "stroke" not in message


def test_the_two_empty_layer_causes_do_not_read_alike():
    assert str(EmptyLayerError("Drill")) != str(EmptyLayerError("Drill", path_count=3))
