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


def test_pipeline_order_is_fixed_by_the_cli():
    args = cli.build_parser().parse_args(["panel.ai", "--true-size", "113x60"])
    assert [stage.name for stage in cli.build_pipeline(args)] == [
        "snap",
        "normalize-diameters",
        "deduplicate",
        "check-reference-size",
        "sort",
    ]


def test_validate_stage_only_present_with_true_size():
    args = cli.build_parser().parse_args(["panel.ai"])
    assert "check-reference-size" not in [s.name for s in cli.build_pipeline(args)]


def test_grid_warn_defaults_are_left_to_the_stage():
    """The grid/4 rule lives in SnapPositions; the CLI must not restate it."""
    args = cli.build_parser().parse_args(["panel.ai", "--grid", "1.0"])
    snap = cli.build_pipeline(args)[0]
    assert snap.grid == 1.0
    assert snap.warn_over == pytest.approx(0.25)

    args = cli.build_parser().parse_args(["panel.ai", "--grid", "1.0", "--grid-warn", "0.4"])
    assert cli.build_pipeline(args)[0].warn_over == pytest.approx(0.4)


def test_diameter_strategy_selection():
    build = lambda argv: cli.build_pipeline(cli.build_parser().parse_args(argv))[1].strategy

    assert type(build(["panel.ai"])).__name__ == "ClusterDiameters"
    assert build(["panel.ai"]).tolerance == pytest.approx(0.05)
    assert build(["panel.ai", "--diameter-tolerance", "0.2"]).tolerance == pytest.approx(0.2)

    table = build(["panel.ai", "--diameters", "table", "--drill-sizes", "3.2,5,7"])
    assert type(table).__name__ == "TableDiameters"
    assert table.sizes == (3.2, 5.0, 7.0)
    assert table.tolerance == pytest.approx(0.15)  # the table default, not cluster's

    assert type(build(["panel.ai", "--diameters", "none"])).__name__ == "NoNormalization"


def test_dedupe_tolerance_reaches_the_stage():
    args = cli.build_parser().parse_args(["panel.ai", "--dedupe-tolerance", "0.3"])
    assert cli.build_pipeline(args)[2].tolerance == pytest.approx(0.3)


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


def test_table_diameters_without_drill_sizes_is_a_usage_error(fake_source, capsys):
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--diameters", "table"]) == 3
    err = capsys.readouterr().err
    assert "--drill-sizes" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("text", ["112.4", "112.4x", "axb", "112.4x60.5x3", "", "-5x60"])
def test_malformed_true_size_is_a_usage_error(fake_source, capsys, text):
    fake_source(make_data())
    assert cli.main([str(FIXTURE), "--true-size", text]) == 3
    assert "--true-size" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text,expected",
    [
        ("112.4x60.5", (112.4, 60.5)),
        ("113X60", (113.0, 60.0)),
        ("113×60", (113.0, 60.0)),
        (" 113 x 60 ", (113.0, 60.0)),
    ],
)
def test_true_size_parsing(text, expected):
    assert cli.parse_true_size(text) == pytest.approx(expected)


def test_true_size_feeds_the_reference_check(fake_source, capsys):
    fake_source(make_data())  # reference is 113 x 60
    assert cli.main([str(FIXTURE), "--true-size", "112.4x60.5"]) == 1
    assert "reference-size-mismatch" in capsys.readouterr().out


def test_malformed_drill_sizes_is_a_usage_error(fake_source, capsys):
    fake_source(make_data())
    code = cli.main([str(FIXTURE), "--diameters", "table", "--drill-sizes", "3.2,fish"])
    assert code == 3
    assert "--drill-sizes" in capsys.readouterr().err


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
    assert "113.000" in out and "60.000" in out
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


def test_report_shows_raw_values_beside_nominal(fake_source, capsys):
    hole = Hole.from_measurement(-19.9906, 18.0021, 6.9998, index=0)
    fake_source(make_data(holes=[hole]))
    cli.main([str(FIXTURE)])
    out = capsys.readouterr().out
    assert "-20.000" in out  # nominal, after snapping
    assert "-19.9906" in out  # raw provenance
    assert "6.9998" in out


def test_verbose_adds_per_stage_detail(fake_source, capsys):
    fake_source(make_data())
    cli.main([str(FIXTURE)])
    quiet = capsys.readouterr().out
    assert "deduplicate" not in quiet

    fake_source(make_data())
    cli.main([str(FIXTURE), "-v"])
    loud = capsys.readouterr().out
    for stage in ("snap", "normalize-diameters", "deduplicate", "sort"):
        assert stage in loud
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
def test_true_size_mismatch_on_the_fixture(tmp_path, capsys):
    doc = tmp_path / "tar.json"
    assert cli.main([str(FIXTURE), "--true-size", "112.4x60.5", "--emit", f"json={doc}"]) == 1
    codes = [d["code"] for d in json.loads(doc.read_text())["diagnostics"]]
    assert "reference-size-mismatch" in codes
