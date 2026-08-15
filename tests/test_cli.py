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
from aidrill.pipeline import DRILL_STANDARDS
from aidrill.model import (
    Diagnostic,
    DrillData,
    Hole,
    ReferenceOutline,
    Severity,
    SourceInfo,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_data(
    *,
    holes=None,
    reference=ReferenceOutline(113.0, 60.0),
    diagnostics=(),
) -> DrillData:
    """DrillData that the default pipeline leaves alone: on-grid, two sizes."""
    if holes is None:
        holes = (
            Hole.from_measurement(-20.0, 18.0, 7.0, index=0),
            Hole.from_measurement(20.0, 18.0, 7.0, index=1),
            Hole.from_measurement(0.0, -18.75, 5.0, index=2),
        )
    return DrillData(
        holes=tuple(holes),
        reference=reference,
        diagnostics=tuple(diagnostics),
        source=SourceInfo(
            path="fake.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill"),
        ),
    )


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

    fake_source(make_data())
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
    """
    assert [stage.name for stage in pipeline_for()] == [
        "snap",
        "snap-diameters",
        "deduplicate",
        "identify-enclosure",
        "sort",
    ]


def test_the_enclosure_stage_is_wired_in_whether_or_not_a_case_was_declared():
    """Identification is not opt-in. The outline is snapped to the catalogue on
    every run, and ``--case`` only adds the cross-check against what was drawn —
    so a panel drawn 1 mm out is still reported without the operator having to
    know to ask."""
    for argv in ([], ["--case", "1590B"]):
        assert "identify-enclosure" in [s.name for s in pipeline_for(*argv)]


def stage_named(name: str, *argv: str):
    """One stage out of the pipeline the CLI built, found by name not position."""
    found = [stage for stage in pipeline_for(*argv) if stage.name == name]
    assert len(found) == 1, f"{name} appears {len(found)} times in the pipeline"
    return found[0]


def test_grid_warn_defaults_are_left_to_the_stage():
    """The grid/4 rule lives in SnapPositions; the CLI must not restate it."""
    snap = stage_named("snap", "--grid", "1.0")
    assert snap.grid == 1.0
    assert snap.warn_over == pytest.approx(0.25)

    assert stage_named("snap", "--grid", "1.0", "--grid-warn", "0.4").warn_over == pytest.approx(0.4)


def test_dedupe_tolerance_reaches_the_stage():
    assert stage_named("deduplicate", "--dedupe-tolerance", "0.3").tolerance == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# which bits are in the drawer
# ---------------------------------------------------------------------------


def test_the_default_standard_is_metric_and_the_tolerance_is_the_stages():
    """The CLI restates neither. ``--drill-standard`` has a default because
    argparse needs one; the matching tolerance has none here at all."""
    stage = stage_named("snap-diameters")
    assert stage.standard.name == "metric"
    assert stage.standard.sizes_mm == DRILL_STANDARDS["metric"].sizes_mm
    assert stage.tolerance_mm == pytest.approx(0.25)


def test_the_declared_standard_reaches_the_stage():
    stage = stage_named("snap-diameters", "--drill-standard", "fractional")
    assert stage.standard.name == "fractional"
    assert stage.standard.sizes_mm == DRILL_STANDARDS["fractional"].sizes_mm


def test_the_declared_standard_decides_what_a_hole_is_drilled_with(fake_source, tmp_path):
    """The flag, proved on the emitted bytes rather than on the stage object.

    6.348 mm is 0.048 from the 6.3 mm metric bit and 0.002 from a 1/4" one, so
    the two standards give different, unmistakable answers — and a CLI that
    accepted ``--drill-standard`` and then built the metric table anyway would
    still write 6.3 here.
    """
    fake_source(
        make_data(holes=[Hole.from_measurement(0.0, 0.0, 6.348, index=0)])
    )
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--drill-standard", "fractional", "--emit", f"json={doc}"]) == 0

    assert [t["diameter"] for t in json.loads(doc.read_text())["tools"]] == [6.35]


def test_an_unknown_standard_is_a_usage_error_that_names_the_ones_there_are(
    fake_source, capsys
):
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--drill-standard", "whitworth"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "whitworth" in err
    for name in DRILL_STANDARDS:
        assert name in err


def test_a_whitelist_narrows_the_table_to_the_drawer():
    stage = stage_named("snap-diameters", "--drill-sizes", "3.2,5,7,12")
    assert stage.standard.sizes_mm == (3.2, 5.0, 7.0, 12.0)


def test_a_blacklist_removes_the_bit_that_is_broken():
    stage = stage_named("snap-diameters", "--no-drill-sizes", "7.0")
    assert 7.0 not in stage.standard.sizes_mm
    assert len(stage.standard.sizes_mm) == len(DRILL_STANDARDS["metric"].sizes_mm) - 1
    assert 6.9 in stage.standard.sizes_mm


def test_the_two_size_flags_combine():
    stage = stage_named("snap-diameters", "--drill-sizes", "3.2,5,7,12", "--no-drill-sizes", "5")
    assert stage.standard.sizes_mm == (3.2, 7.0, 12.0)


def test_a_narrowed_table_is_what_the_holes_are_actually_quantised_against(
    fake_source, tmp_path
):
    """With no 7 mm bit in the drawer, a 6.9998 mm hole is drilled with what is.

    Read back out of the machine-readable document, because the claim is about
    what reaches a consumer: both the hole's nominal size *and* the record of
    which sizes were available must be the narrowed set.
    """
    fake_source(make_data(holes=[Hole.from_measurement(0.0, 0.0, 6.9998, index=0)]))
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--drill-sizes", "3.2,6.8,12", "--emit", f"json={doc}"]) == 0

    document = json.loads(doc.read_text())
    assert [t["diameter"] for t in document["tools"]] == [6.8]
    recorded = [r for r in document["processing"] if r["name"] == "snap-diameters"]
    assert recorded[0]["parameters"]["sizes_mm"] == [3.2, 6.8, 12.0]
    assert recorded[0]["parameters"]["standard"] == "metric"


def test_a_size_the_standard_does_not_have_is_a_usage_error(fake_source, capsys):
    """``3.33`` is a typo. Read leniently it would give the panel a drawer with
    a bit missing; read as a match it would give it one that does not exist."""
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--drill-sizes", "3.2,3.33"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "3.33" in err


def test_a_metric_size_is_not_a_fractional_bit(fake_source, capsys):
    """The refusal is against the declared standard, not against drills at large."""
    fake_source(make_data())
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
    fake_source(make_data())
    assert cli.main([str(FIXTURE), flag, bad]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert flag in err


# ---------------------------------------------------------------------------
# which case the panel is for
# ---------------------------------------------------------------------------


def test_a_declared_case_reaches_the_enclosure_stage_in_catalogue_form():
    assert stage_named("identify-enclosure", "--case", " 1590b ").expected_part == "1590B"
    assert stage_named("identify-enclosure").expected_part is None


def test_the_declared_case_agreeing_with_the_artwork_is_silent(fake_source, capsys):
    fake_source(make_data())  # a 113 x 60 outline, which is a 112 x 61 1590B
    assert cli.main([str(FIXTURE), "--case", "1590B"]) == 0


def test_a_case_that_disagrees_with_the_artwork_is_an_error(fake_source, capsys, tmp_path):
    """Exit 2, and the finding names both parts.

    This is what finally makes exit 2 reachable from a correct file: the panel
    parses, every hole is a real bit, and the run is still refused because the
    aluminium in front of the operator is the wrong case.
    """
    fake_source(make_data())
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    found = [
        d for d in json.loads(doc.read_text())["diagnostics"] if d["code"] == "wrong-enclosure"
    ]
    assert len(found) == 1
    assert found[0]["data"]["requested_part"] == "1590BB"
    assert found[0]["severity"] == "error"


def test_an_order_code_is_not_told_it_drew_the_wrong_case(fake_source, capsys):
    """``1590BBBK`` is a real order code — BB body, BK black finish — and the
    single most likely thing an operator types.

    It is not a base designator, so it cannot be checked against a footprint,
    and treating it as one would report ``wrong-enclosure`` on a *correct*
    1590BB panel: a message telling the operator they drew the wrong case when
    they drew the right one. It is a usage error instead, and it says which
    designator the order code is built on so the fix is one retype.
    """
    fake_source(make_data())
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
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--case", "1590ZZ"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("aidrill: error:"), err
    assert "1590ZZ" in err


def test_an_empty_case_is_told_it_is_empty(fake_source, capsys):
    """``--case "$CASE"`` with ``CASE`` unset is a Makefile away, and the answer
    to it must not be a sentence about ``''`` not being in the catalogue — the
    operator would go looking for a part number they never typed."""
    fake_source(make_data())
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


@pytest.mark.parametrize(
    "argv",
    [
        ["--diameters", "cluster"],
        ["--diameter-tolerance", "0.2"],
        ["--true-size", "113x60"],
    ],
)
def test_the_flags_that_went_with_the_strategies_are_gone(fake_source, capsys, argv):
    """Rejected by argparse, not quietly ignored. A flag that still parses but
    no longer does anything is worse than one that fails."""
    fake_source(make_data())
    assert cli.main([str(FIXTURE), *argv]) == 3
    assert capsys.readouterr().err.startswith("usage:")  # argparse's, never ours


# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------


def test_exit_zero_when_clean(fake_source, capsys):
    fake_source(make_data())
    assert cli.main([str(FIXTURE)]) == 0


def test_info_diagnostics_do_not_change_the_exit_code(fake_source, capsys):
    fake_source(make_data(diagnostics=[Diagnostic.info("note", "just so you know")]))
    assert cli.main([str(FIXTURE)]) == 0


def test_exit_one_on_warnings(fake_source, capsys):
    fake_source(make_data(diagnostics=[Diagnostic.warning("something", "watch out")]))
    assert cli.main([str(FIXTURE)]) == 1


def test_exit_two_on_errors(fake_source, capsys):
    fake_source(
        make_data(
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
        fake_source(make_data(diagnostics=[Diagnostic(severity, "c", "m")]))
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
    fake_source(make_data())

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
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--emit", spec]) == 3
    assert "FORMAT=PATH" in capsys.readouterr().err


def test_unknown_emit_format_is_a_usage_error(fake_source, tmp_path, capsys):
    fake_source(make_data())
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
    fake_source(make_data(reference=None))
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
    fake_source(make_data(reference=None))
    doc = tmp_path / "a.json"
    drl = tmp_path / "b.drl"

    code = cli.main([str(FIXTURE), "--emit", f"json={doc}", "--emit", f"excellon={drl}"])

    assert code == 3
    assert not doc.exists(), "the JSON artifact survived a failed run"
    assert not drl.exists()
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.count("error:") == 1  # reported once, not once per target


def test_every_target_is_written_on_the_happy_path(fake_source, tmp_path, capsys):
    """Rendering to memory first must not cost anyone their artifacts."""
    fake_source(make_data())
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
    fake_source(make_data())
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
    fake_source(make_data(diagnostics=[Diagnostic.warning("something", "watch out")]))
    cli.main([str(FIXTURE)])
    out = capsys.readouterr().out

    assert "fake.ai" in out
    assert "Drill" in out and "Background" in out
    # 112 × 61, not the 113 × 60 the artwork measured: the enclosure stage runs
    # on every panel now, and the report states the catalogue's whole
    # millimetres because those are what the holes are positioned against.
    assert "112.000" in out and "61.000" in out
    assert "7.000" in out and "5.000" in out  # hole diameters
    assert "T1" in out and "T2" in out  # tool summary
    assert "something" in out and "watch out" in out


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
        holes=make_data().holes,
        reference=ReferenceOutline(113.0, 60.0),
        source=SourceInfo(path="fake.ai"),
    )

    lines = cli.format_tools(data)

    assert calls, "cli.format_tools never asked the model for its tool counts"
    assert [line for line in lines if "x99" in line], lines
    assert not [line for line in lines if "x2" in line or "x1" in line], lines


def report_tool_diameters(lines) -> list[str]:
    """The rendered diameter of each ``TOOLS`` line, as printed."""
    return [match.group(1) for match in (re.search(r"dia ([\d.]+) mm", line) for line in lines) if match]


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
    data = make_data(
        holes=[
            Hole.from_measurement(-20.0, 18.0, 6.9998, index=0),
            Hole.from_measurement(20.0, 18.0, 7.0, index=1),
        ]
    )
    assert len(data.tools()) == 2  # the fixture must actually pose the problem

    printed = report_tool_diameters(cli.format_tools(data))

    assert len(printed) == 2
    assert len(set(printed)) == 2, f"two tools printed the same diameter: {printed}"


def test_the_tools_report_keeps_its_usual_three_decimals(fake_source, capsys):
    """Widening is for the collision, not for every panel: an ordinary run must
    read exactly as it always did."""
    assert report_tool_diameters(cli.format_tools(make_data())) == ["5.000", "7.000"]


def test_report_shows_raw_values_beside_nominal(fake_source, capsys):
    hole = Hole.from_measurement(-19.9906, 18.0021, 6.9998, index=0)
    fake_source(make_data(holes=[hole]))
    cli.main([str(FIXTURE)])
    out = capsys.readouterr().out
    assert "-20.000" in out  # nominal, after snapping
    assert "-19.9906" in out  # raw provenance
    assert "6.9998" in out


def test_verbose_reports_every_stage_the_cli_built(fake_source, capsys):
    """The list of stages comes from ``build_pipeline``, so a stage added there
    is covered here without anyone remembering to add it twice."""
    fake_source(make_data())
    cli.main([str(FIXTURE)])
    quiet = capsys.readouterr().out
    assert "deduplicate" not in quiet

    fake_source(make_data())
    cli.main([str(FIXTURE), "-v"])
    loud = capsys.readouterr().out
    for stage in pipeline_for():
        assert stage.name in loud, f"--verbose said nothing about {stage.name}"
    assert len(loud) > len(quiet)


def test_the_traced_path_folds_through_the_same_pipeline_as_the_plain_one():
    """``--verbose`` must not be a second, divergent fold.

    It was one: an ``apply`` loop of its own, identical to ``Pipeline.run`` right
    up until the fold gained a second responsibility. A verbose run then produced
    data with no processing history at all, and the drawing made from it could
    not say what grid the holes had been snapped to.
    """
    args = cli.build_parser().parse_args(["panel.ai", "--grid", "0.5"])
    pipeline = cli.build_pipeline(args)
    data = make_data()

    plain = cli.run_pipeline(pipeline, data)
    traced = cli.run_pipeline(pipeline, data, trace=lambda *_: None)

    assert traced.processing == plain.processing
    assert [run.name for run in traced.processing] == [stage.name for stage in pipeline]
    assert traced.last_run("snap").get("grid_mm") == 0.5


def test_the_grid_reaches_the_drawing_through_the_pipeline_not_the_options(
    fake_source, tmp_path
):
    """``--grid`` is handed to ``SnapPositions``, and to nothing else.

    It used to be copied into ``DrawingOptions`` as well, which made the sheet's
    stamp agree with the flag rather than with the holes. Asserted on the
    emitted SVG, since agreement between two artifacts is not visible in the
    objects they were built from.
    """
    fake_source(make_data())
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
    fake_source(make_data())
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
    """``[(no, x, y, diameter, tool)]`` from the drawing's hole schedule."""
    rows = []
    for group in root.iter(SVG + "g"):
        if group.get("class") != "sched-row":
            continue
        number, x, y, diameter, tool = [text.text or "" for text in group.iter(SVG + "text")]
        rows.append(
            (
                int(number),
                float(x),
                float(y),
                float(diameter.lstrip("⌀")),
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

    assert cli.main([str(FIXTURE), "--emit", f"excellon={drl}", "--emit", f"drawing-svg={svg}"]) == 1

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

    # 3. the drilling order is the balloon order, grouped by tool
    assert balloons == [number for number, *_ in rows] == list(range(1, 8))
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
    code = cli.main([str(FIXTURE), "--grid", "0.5", "--emit", f"json={doc}"])
    assert code == 1

    codes = [d["code"] for d in json.loads(doc.read_text())["diagnostics"]]
    assert codes.count("off-grid") == 2


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_is_identified_as_the_case_it_was_drawn_for(tmp_path):
    """The 1590B footprint, and the artwork's own measurement kept beside it.

    ``--case`` is what makes the check two-way; without it the panel is still
    identified, which is what lets the drawing dimension whole millimetres.
    """
    doc = tmp_path / "tar.json"
    assert cli.main([str(FIXTURE), "--case", "1590B", "--emit", f"json={doc}"]) == 1

    document = json.loads(doc.read_text())
    # Read off the emitted bytes: the artwork measures 113.000 × 60.000 and the
    # catalogue says 1590B is 112 × 61, so a document carrying whole millimetres
    # beside a fractional measurement is the enclosure stage having run.
    assert (document["reference"]["width"], document["reference"]["height"]) == (112.0, 61.0)
    assert document["reference"]["raw"]["width"] == pytest.approx(113.0, abs=1e-3)
    assert document["reference"]["raw"]["height"] == pytest.approx(60.0, abs=1e-3)
    assert [d["code"] for d in document["diagnostics"]] == ["duplicate-hole"]


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_declared_as_the_wrong_case_exits_two(tmp_path, capsys):
    doc = tmp_path / "tar.json"
    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    codes = [d["code"] for d in json.loads(doc.read_text())["diagnostics"]]
    assert "wrong-enclosure" in codes


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
