"""Tests for CLI validation, pipeline assembly, registry dispatch and reports."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import ClassVar

import pytest

import stompmodel.protocols as protocols
from stompdrill import cli
from stompdrill.emitters.base import available, register_emitter
from stompdrill.errors import EmptyLayerError, LayerNotFoundError
from stompdrill.pipeline import DRILL_STANDARDS
from stompdrill.quantise import RawDrillData
from stompmodel.diagnostics import Diagnostic, Severity
from stompmodel.model import (
    DrillData,
    EnclosureMatch,
    Hole,
    RawHole,
    RawOutline,
    ReferenceOutline,
    SourceInfo,
    StageRun,
)
from stompmodel.units import Millimetre, Nanometre
from tests.conftest import build_pdf, circle_ops
from tests.hammond import BB_PROBES, require_model

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

#: The 1590BB's published top-view footprint (ADR-0007): what real artwork
#: draws the ``Background`` rectangle to, not the smaller drilled face.
_BB_FOOTPRINT_MM = (119.5, 94.0)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def read(
    *,
    holes=None,
    reference=RawOutline(Millimetre(99.6), Millimetre(50.4)),
    diagnostics=(),
) -> RawDrillData:
    """Return unquantised float-millimetre input.

    Defaults are on-grid with metric bits and a usable footprint, avoiding noise.
    """
    if holes is None:
        holes = (
            RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0)),
            RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(7.0)),
            RawHole(Millimetre(0.0), Millimetre(-18.75), Millimetre(5.0)),
        )
    return RawDrillData(
        source=SourceInfo(
            path="fake.ai",
            drill_layer="Drill",
            reference_layer="Background",
            layers_found=("Background", "Drill"),
        ),
        reference=reference,
        centre=(Millimetre(56.5), Millimetre(30.0)),
        holes=tuple(holes),
        diagnostics=tuple(diagnostics),
    )


def document(
    *,
    holes=None,
    reference=ReferenceOutline(Nanometre(112_000_000), Nanometre(61_000_000)),
    diagnostics=(),
    processing=(),
) -> DrillData:
    """A finished ``DrillData``, for the report renderers called directly."""
    if holes is None:
        holes = (
            Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(1),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(2),
            Hole.from_measurement(Nanometre(0), Nanometre(-18_750_000), Nanometre(5_000_000)).with_number(3),
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
    """The provenance ``SnapDiametersToDrillTable`` leaves behind."""
    return StageRun("snap-diameters", (("standard", standard), ("size_count", size_count)))


def _pt_from_mm(mm: float) -> float:
    """Millimetres to PDF user-space points, the way a drawing tool would."""
    return mm * 72 / 25.4


def _bb_panel(tmp_path: Path, name: str, x_mm: float, y_mm: float, diameter_mm: float) -> Path:
    """One drill circle on a ``Background`` drawn to the 1590BB's own footprint.

    Canonical coordinates are millimetres with Y up and the origin at the
    footprint's centre, which is exactly how ``build_pdf``'s page coordinates
    are used here: the rectangle's own centre is the origin the hole offset is
    measured from.
    """
    width, height = (_pt_from_mm(size) for size in _BB_FOOTPRINT_MM)
    centre_x, centre_y = 10 + width / 2, 10 + height / 2
    return build_pdf(
        tmp_path / name,
        {
            "Background": f"10 10 {width} {height} re f",
            "Drill": circle_ops(
                centre_x + _pt_from_mm(x_mm),
                centre_y + _pt_from_mm(y_mm),
                _pt_from_mm(diameter_mm / 2),
            ),
        },
    )


def _panel_with_a_hole_in_a_boss(tmp_path: Path) -> Path:
    """A ⌀4 mm hole inside the play area but inside a boss bite (THROUGH_BOSS)."""
    x, y = BB_PROBES["boss"]
    return _bb_panel(tmp_path, "boss.ai", x, y, 4.0)


def _panel_with_a_central_hole(tmp_path: Path) -> Path:
    """A ⌀6 mm hole in the clear middle of the floor: nothing rejects it."""
    x, y = BB_PROBES["clear"]
    return _bb_panel(tmp_path, "clear.ai", x, y, 6.0)


def _model_path() -> Path:
    """The cached 1590BB model, fetched if needed; skips when unobtainable."""
    return require_model("1590BB")


@pytest.fixture
def fake_source(monkeypatch):
    """Install a stand-in for ``AiPdfSource``. Returns an ``install`` callable."""

    def install(result):
        from stompdrill.sources import DEFAULT_FORM_DEPTH

        class FakeSource:
            def __init__(
                self,
                path,
                drill_layer="Drill",
                reference_layer="Background",
                form_depth=DEFAULT_FORM_DEPTH,
            ):
                self.path = path
                self.drill_layer = drill_layer
                self.reference_layer = reference_layer
                self.form_depth = form_depth

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


def test_a_registered_emitter_needing_options_this_cli_cannot_supply_exits_three(
    clean_registry, fake_source, tmp_path, capsys
):
    """The documented "New emitter" recipe, executed to the letter.

    Implement ``Emitter``, decorate with ``register_emitter``, skip the CLI
    edit because no flags are needed -- and give the options a required,
    no-default constructor parameter. The CLI cannot supply one, so this is a
    usage failure (exit 3), not the unhandled ``TypeError`` it used to be.
    """

    @dataclasses.dataclass(frozen=True, slots=True)
    class FooOptions:
        thing: str  # required, no default -- no CLI flags needed per the recipe

    @register_emitter
    class FooEmitter:
        name = "foo-needs-options"
        media_type = "text/plain"
        extension = ".foo"

        def __init__(self, options: FooOptions) -> None:
            self.options = options

        def emit(self, data):
            return self.options.thing.encode()

    fake_source(read())
    out = tmp_path / "out.foo"

    code = cli.main([str(FIXTURE), "--emit", f"foo-needs-options={out}"])

    assert code == 3
    assert not out.exists()
    err = capsys.readouterr().err
    assert "foo-needs-options" in err


def test_a_registered_emitter_with_defaulted_options_still_emits_normally(
    clean_registry, fake_source, tmp_path
):
    """The recipe's other lawful shape -- a constructor needing nothing -- is
    unaffected: the fix must not refuse a conforming extension wholesale."""

    @register_emitter
    class BareEmitter:
        name = "bare-needs-nothing"
        media_type = "text/plain"
        extension = ".bare"

        def __init__(self):
            pass

        def emit(self, data):
            return b"bare\n"

    fake_source(read())
    out = tmp_path / "out.bare"

    code = cli.main([str(FIXTURE), "--emit", f"bare-needs-nothing={out}"])

    assert code == 0
    assert out.read_bytes() == b"bare\n"


def test_an_unrelated_typeerror_from_an_emitters_own_emit_step_still_propagates(
    clean_registry, fake_source, tmp_path
):
    """Proves the narrowness: only construction is guarded. A ``TypeError``
    raised later, from ``emit`` itself, is a genuinely unexpected fault and
    must keep its traceback rather than being reclassified as usage error 3."""

    @register_emitter
    class BrokenEmitEmitter:
        name = "broken-emit"
        media_type = "text/plain"
        extension = ".broken"

        def __init__(self):
            pass

        def emit(self, data):
            raise TypeError("unrelated fault inside emit, not construction")

    fake_source(read())
    out = tmp_path / "out.broken"

    with pytest.raises(TypeError, match="unrelated fault inside emit"):
        cli.main([str(FIXTURE), "--emit", f"broken-emit={out}"])


def _docstring_constants(tree: ast.AST) -> set[int]:
    """``id()`` of every string-literal ``Constant`` node that is a docstring.

    A docstring is a plain identifying comment, indistinguishable in prose
    from an identifier such as ``StepOptions`` -- neither leaks into what the
    CLI prints or compares against, so a format name inside one is not the
    rule this test enforces.
    """
    ids = set()
    holders = [tree, *(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )]
    for holder in holders:
        body = getattr(holder, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


def test_cli_source_never_names_a_registered_format(clean_registry):
    """A format name may reach ``cli.py`` only through the registry.

    A whole-file substring search is a landmine now a format is named
    ``step``: this module is about pipeline *steps*, so an identifier like
    ``StepOptions`` would trip it by accident. Checking only string-literal
    ``Constant`` nodes, docstrings excluded, targets the real rule: no
    literal may dispatch on, or name, a format in help or an error message.
    """
    tree = ast.parse(Path(cli.__file__).read_text())
    excluded = _docstring_constants(tree)
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in excluded
    ]
    for name in available():
        assert not any(name in literal for literal in literals), (
            f"cli.py hardcodes the format name {name!r} in a string literal"
        )


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
    """The pipeline the CLI actually builds for ``argv``."""
    return cli.build_pipeline(cli.build_parser().parse_args(["panel.ai", *argv]))


def test_the_cli_fixes_the_stage_order():
    """The cli fixes the stage order."""
    assert [stage.name for stage in pipeline_for()] == [
        "deduplicate",
        "review-grid-ties",
        "route",
        "check-outline-containment",
    ]


def quantisers_for(*argv: str) -> cli.Quantisers:
    """The three quantisers the CLI actually builds for ``argv``."""
    return cli.build_quantisers(cli.build_parser().parse_args(["panel.ai", *argv]))


def test_the_cli_quantises_between_the_source_and_the_pipeline(fake_source, capsys):
    """The cli quantises between the source and the pipeline."""
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
    """``--grid 0.25`` is a quarter of a millimetre, not 0.25 nanometres."""
    assert quantisers_for().positions.grid_nm == 250_000
    assert quantisers_for("--grid", "0.5").positions.grid_nm == 500_000


@pytest.mark.parametrize("flag", ["--grid", "--grid-warn"])
def test_both_grid_flags_name_millimetres_in_their_help(flag):
    """The help states the unit the value is read in, not one it is measured against.

    A reader who takes the pitch for microns types ``--grid 250`` and gets a
    250 mm grid: every hole collapses onto the origin, and the run reports
    coincident holes rather than a bad unit. The help is the only thing
    standing between that and the operator, so the unit is asserted here.
    """
    action = next(a for a in cli.build_parser()._actions if flag in a.option_strings)

    assert action.metavar == "MM"
    assert action.help is not None
    # The preposition carries it: ``--grid``'s help legitimately also mentions
    # microns, so asserting the bare word would pass on "in microns, a whole
    # number of millimetres" -- the very transposition this guards against.
    assert "in millimetres" in action.help


class TestAGridThatIsNotANumberIsAUsageError:
    """Exit 3, not 1, and not an artefact full of ``XnanYnan``."""

    @pytest.mark.parametrize("argv", [["--grid", "nan"], ["--grid", "inf"]])
    def test_a_non_finite_grid_exits_three(self, fake_source, capsys, argv):
        fake_source(read())
        assert cli.main([str(FIXTURE), *argv]) == 3
        assert capsys.readouterr().err.startswith("stompdrill: error:")

    def test_a_non_finite_warning_threshold_exits_three(self, fake_source, capsys):
        fake_source(read())
        assert cli.main([str(FIXTURE), "--grid-warn", "nan"]) == 3
        assert capsys.readouterr().err.startswith("stompdrill: error:")

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
    """Clamp sub-micron grids but reject pitches not in whole microns."""

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
        assert err.startswith("stompdrill: error:"), err
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
    """The declared standard decides the bit.

    6.348 mm is nearer 1/4 inch than 6.3 mm, so the standards cannot agree.
    """
    fake_source(read(holes=[RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(6.348))]))

    assert cli.main([str(FIXTURE), "--drill-standard", "fractional"]) == 0

    assert '⌀1/4"' in capsys.readouterr().out


def test_an_unknown_standard_is_a_usage_error_that_names_the_ones_there_are(
    fake_source, capsys
):
    fake_source(read())
    assert cli.main([str(FIXTURE), "--drill-standard", "whitworth"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("stompdrill: error:"), err
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
    """With no 7 mm bit in the drawer, a 6.9998 mm hole is drilled with what is."""
    fake_source(read(holes=[RawHole(Millimetre(0.0), Millimetre(0.0), Millimetre(6.9998))]))

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
    assert err.startswith("stompdrill: error:"), err
    assert "3.33" in err


def test_a_metric_size_is_not_a_fractional_bit(fake_source, capsys):
    """The refusal is against the declared standard, not against drills at large."""
    fake_source(read())
    assert cli.main([str(FIXTURE), "--drill-standard", "fractional", "--drill-sizes", "3.2"]) == 3
    assert "fractional" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--drill-sizes", "--no-drill-sizes"])
@pytest.mark.parametrize("bad", ["", "3.2,fish", "3,nan", "3.2,0"])
def test_a_malformed_size_list_is_a_usage_error(fake_source, capsys, flag, bad):
    """A malformed size list is a usage error."""
    fake_source(read())
    assert cli.main([str(FIXTURE), flag, bad]) == 3

    err = capsys.readouterr().err
    assert err.startswith("stompdrill: error:"), err
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
    """Exit 2, reported, and no artefact left behind."""
    fake_source(read())
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    assert "[wrong-enclosure]" in capsys.readouterr().out
    assert not doc.exists(), "a document describing the wrong case reached the disk"


def test_an_order_code_is_not_told_it_drew_the_wrong_case(fake_source, capsys):
    """``1590BBBK`` is a real order code — BB body, BK black finish — and the single most
    likely thing an operator types.
    """
    fake_source(read())
    assert cli.main([str(FIXTURE), "--case", "1590BBBK"]) == 3

    err = capsys.readouterr().err
    assert err.startswith("stompdrill: error:"), err
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
    assert err.startswith("stompdrill: error:"), err
    assert "1590ZZ" in err


def test_a_panel_that_is_no_hammond_case_still_gets_its_drill_data(fake_source, capsys):
    """A folded-aluminium one-off, or any of the enclosures we do not stock."""
    fake_source(read(reference=RawOutline(Millimetre(200.0), Millimetre(100.0))))

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
    assert err.startswith("stompdrill: error:"), err
    assert "needs a part number" in err


def test_the_case_is_checked_before_the_file_is_even_opened(capsys):
    """A typo costs no PDF parse, and — the point — it is reported *as* a typo."""
    assert cli.main(["/no/such/panel.ai", "--case", "1590ZZ"]) == 3
    assert "1590ZZ" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --form-depth
# ---------------------------------------------------------------------------


def test_form_depth_defaults_to_the_sources_own_default():
    from stompdrill.sources import DEFAULT_FORM_DEPTH

    args = cli.build_parser().parse_args(["panel.ai"])

    assert args.form_depth == DEFAULT_FORM_DEPTH


def test_the_help_states_the_default_depth_it_will_apply():
    """One number, one authority: the help must not carry a second literal."""
    from stompdrill.sources import DEFAULT_FORM_DEPTH

    assert str(DEFAULT_FORM_DEPTH) in cli.build_parser().format_help()


def test_form_depth_reaches_the_source(monkeypatch):
    """Its own spy rather than ``fake_source``: the shared fixture stays a stub.

    A class attribute recording the last instance would be an ``attr-defined``
    error the moment anyone annotated that fixture's ``__init__``.
    """
    seen: dict[str, int] = {}

    class Spy:
        def __init__(self, path, drill_layer="Drill", reference_layer="Background", form_depth=0):
            seen["form_depth"] = form_depth

        def read(self):
            return read()

    monkeypatch.setattr(cli, "AiPdfSource", Spy)

    cli.main(["panel.ai", "--form-depth", "3"])

    assert seen["form_depth"] == 3


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_a_depth_below_one_level_is_a_usage_error(bad, capsys):
    assert cli.main([str(FIXTURE), "--form-depth", bad]) == 3

    assert "--form-depth" in capsys.readouterr().err


def test_a_depth_that_is_not_a_whole_number_is_a_usage_error():
    """argparse's own ``type=int`` rejects it; the exit code is still the contract."""
    assert cli.main([str(FIXTURE), "--form-depth", "1.5"]) == 3


def test_a_bad_depth_is_refused_before_the_panel_is_opened(tmp_path, capsys):
    """A file that would fail to parse must not be reached; the flag loses first."""
    unreadable = tmp_path / "not-a-pdf.ai"
    unreadable.write_text("this is not a PDF", encoding="utf-8")

    assert cli.main([str(unreadable), "--form-depth", "0"]) == 3

    assert "--form-depth" in capsys.readouterr().err


def test_truncated_nesting_exits_one_from_the_command_line(tmp_path, capsys):
    from tests.conftest import build_pdf, self_nesting_form

    panel = build_pdf(
        tmp_path / "deep.ai",
        {"Background": "0 0 m 300 0 l 300 200 l 0 200 l h S", "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], self_nesting_form()),
    )

    assert cli.main([str(panel), "--form-depth", "1"]) == 1

    out = capsys.readouterr().out
    assert "nesting-truncated" in out
    assert "stopped at Form XObject nesting depth 1" in out


def test_a_form_depth_beyond_the_interpreters_own_limit_exits_three(tmp_path, capsys):
    """A RecursionError from a pathological --form-depth is exit 3, not a traceback.

    CLAUDE.md's exit-code contract is 0/1/2/3; an uncaught RecursionError would
    fall outside it and outside main's own ``(UsageError, StompError, OSError)``.
    """
    from tests.conftest import build_pdf, self_nesting_form

    panel = build_pdf(
        tmp_path / "far-too-deep.ai",
        {"Background": "0 0 m 300 0 l 300 200 l 0 200 l h S", "Drill": "/Fm0 Do"},
        form=([1, 0, 0, 1, 10, 0], self_nesting_form()),
    )

    assert cli.main([str(panel), "--form-depth", "100000"]) == 3

    assert "error" in capsys.readouterr().err


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
    """The two rejections are told apart by shape, because nothing else does it."""
    fake_source(read())

    assert cli.main([str(FIXTURE), "--drill-sizes", "-3.2,7"]) == 3
    argparse_err = capsys.readouterr().err
    assert argparse_err.startswith("usage:")  # argparse's, never ours
    # Why ``startswith`` and not ``in`` — argparse says this too:
    assert "stompdrill: error:" in argparse_err
    assert "--drill-sizes" in argparse_err

    assert cli.main([str(FIXTURE), "--drill-sizes", "3.33"]) == 3
    ours = capsys.readouterr().err
    assert ours.startswith("stompdrill: error:")
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
    assert "Drill" in err, "the error omitted the missing layer name"
    assert "Background" in err, "the error omitted an available layer name"
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
    """All or nothing: a half-written output set is worse than no output set."""
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
    """The expensive failure, in the one artefact nobody reads with their eyes."""
    fake_source(
        read(
            holes=[
                RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0)),
                RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(30.0)),  # no bit makes this
                RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(5.0)),
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
    """Only ERROR withholds output; a warning-only run writes the requested file."""
    fake_source(read(diagnostics=[Diagnostic.warning("something", "watch out")]))
    doc = tmp_path / "panel.txt"

    assert cli.main([str(FIXTURE), "--emit", f"json={doc}"]) == 1
    assert doc.exists(), "the json artefact was not written despite a warnings-only exit"
    assert doc.read_text().strip(), "the json artefact was written but is empty"


def test_every_target_is_written_on_the_happy_path(fake_source, tmp_path, capsys):
    """Rendering to memory still writes every requested artefact."""
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


# ---------------------------------------------------------------------------
# one invocation, one transaction (ticket 22): a write-time IO failure at any
# target withholds every artefact of this invocation, not only the ones
# after the failure -- and never disturbs an artefact a previous, successful
# invocation already left at one of these same paths.
# ---------------------------------------------------------------------------


def _sabotage_write(monkeypatch, target: Path) -> None:
    """Make writing ``target``'s own staged temporary raise ``OSError``.

    Every other path's temporary is written normally, so this isolates the
    failure to exactly one target regardless of its position in ``--emit``.
    """
    marker = f".{target.name}."
    original_write_bytes = Path.write_bytes

    def write_bytes(self: Path, data: bytes) -> int:
        if self.parent == target.parent and self.name.startswith(marker):
            raise OSError(f"simulated write failure for {target}")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)


@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_a_write_failure_at_any_position_leaves_no_artefact_of_this_run(
    fake_source, tmp_path, capsys, monkeypatch, position
):
    """F3-04: the theme's class criterion, not just its reproduction.

    An IO failure writing one target must withhold every target of this
    invocation -- whichever position it happens to be at -- because the
    document's "any error withholds every requested artefact" rule is a
    fact about the whole invocation, not only about rendering.
    """
    fake_source(read())
    a = tmp_path / "a.json"
    b = tmp_path / "b.drl"
    c = tmp_path / "c.svg"
    targets = {"first": a, "middle": b, "last": c}
    _sabotage_write(monkeypatch, targets[position])

    exit_code = cli.main(
        [
            str(FIXTURE),
            "--emit",
            f"json={a}",
            "--emit",
            f"excellon={b}",
            "--emit",
            f"drawing-svg={c}",
        ]
    )

    assert exit_code == 3
    assert not a.exists(), "an earlier target survived a run that failed later"
    assert not b.exists()
    assert not c.exists(), "a later target was written before the failure was even reached"
    assert "Traceback" not in capsys.readouterr().err


def test_a_failed_run_leaves_a_previous_runs_artefacts_completely_untouched(
    fake_source, tmp_path, capsys, monkeypatch
):
    """The dangerous form: a stale artefact is worse than a missing one.

    With every target already holding a previous, successful run's bytes,
    a failed re-run must leave every one of them exactly as that previous
    run left it -- never this run's bytes, and never deleted outright.
    """
    fake_source(read())
    a = tmp_path / "a.json"
    b = tmp_path / "b.drl"
    c = tmp_path / "c.svg"
    argv = [
        str(FIXTURE),
        "--emit",
        f"json={a}",
        "--emit",
        f"excellon={b}",
        "--emit",
        f"drawing-svg={c}",
    ]

    assert cli.main(argv) == 0
    previous = {path: path.read_bytes() for path in (a, b, c)}

    # A different panel, so this run's bytes would visibly differ from the
    # previous run's if any of them reached disk.
    fake_source(
        read(
            holes=(RawHole(Millimetre(-10.0), Millimetre(10.0), Millimetre(5.0)),)
        )
    )
    _sabotage_write(monkeypatch, b)

    assert cli.main(argv) == 3

    for path in (a, b, c):
        assert path.exists(), f"{path} was deleted outright by the failed run"
        assert path.read_bytes() == previous[path], (
            f"{path} was replaced by the failed run's bytes instead of being "
            "left exactly as the previous run left it"
        )
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# ticket 29: the requested --emit target set is validated once, as a set,
# before anything is rendered -- a duplicate target or an existing target
# that is not a regular file is a usage error caught up front. Ticket 35:
# every other precondition a target must satisfy is the write mechanism's
# own (ADR-0005, enforced by stage_payload), not restated here, so it
# surfaces during staging instead -- still a clean usage error with
# nothing on disk, just after a render rather than before one. A
# commit-phase failure rolls back every target this same invocation had
# already replaced, not only the ones still unattempted. Ticket 40: the
# target set is compared under a case- and normalisation-folded key,
# because a filesystem may unify two spellings this command line would
# otherwise report as two artefacts.
# ---------------------------------------------------------------------------


def test_two_emit_specs_naming_one_path_are_a_usage_error(fake_source, tmp_path, capsys):
    """F2-02(b): two artefacts cannot share one path -- caught before rendering."""
    fake_source(read())
    out = tmp_path / "out.x"

    exit_code = cli.main([str(FIXTURE), "--emit", f"json={out}", "--emit", f"excellon={out}"])

    assert exit_code == 3
    assert not out.exists(), "a rejected invocation must not write the colliding path"
    err = capsys.readouterr().err
    assert str(out) in err
    assert "Traceback" not in err


def test_two_emit_targets_differing_only_in_case_are_a_usage_error(
    fake_source, tmp_path, capsys
):
    """The confirmed defect: on a case-insensitive volume these name one
    file, so the run printed a "wrote" line for an artefact the next
    commit then destroyed, and exited 1 rather than 3. The refusal is
    unconditional, so this also fails on a case-sensitive volume if the
    fold is dropped."""
    fake_source(read())
    lower = tmp_path / "out.json"
    upper = tmp_path / "OUT.json"

    exit_code = cli.main(
        [str(FIXTURE), "--emit", f"json={lower}", "--emit", f"drawing-svg={upper}"]
    )

    assert exit_code == 3
    assert not lower.exists() and not upper.exists()
    err = capsys.readouterr().err
    assert str(lower) in err and str(upper) in err
    assert "Traceback" not in err


def test_two_emit_targets_differing_only_in_normalisation_form_are_a_usage_error(
    fake_source, tmp_path, capsys
):
    """Case is not the only folding this repository's own APFS volume
    applies: NFC and NFD spellings of one name are two distinct Python
    strings and one file on disk. A ``casefold``-only repair passes the
    probe above and leaves this one destroying an artefact."""
    fake_source(read())
    nfc = tmp_path / unicodedata.normalize("NFC", "café.json")
    nfd = tmp_path / unicodedata.normalize("NFD", "café.json")
    # Fixture control: a probe that can pass by finding nothing is not
    # evidence. Were these already one string there would be no collision
    # to refuse and every assertion below would be vacuous.
    assert str(nfc) != str(nfd)

    exit_code = cli.main(
        [str(FIXTURE), "--emit", f"json={nfc}", "--emit", f"drawing-svg={nfd}"]
    )

    assert exit_code == 3
    assert not nfc.exists() and not nfd.exists()
    err = capsys.readouterr().err
    assert "Traceback" not in err


def test_two_ordinary_targets_one_character_apart_are_both_written(
    fake_source, tmp_path
):
    """A pair as close as two targets can be without folding -- one ASCII
    digit apart -- must still produce two artefacts. A fold that unified
    more than case and normalisation form, or a pre-flight that refused a
    repeated stem, fails here."""
    fake_source(read())
    a = tmp_path / "out-1.json"
    b = tmp_path / "out-2.json"

    assert cli.main(
        [str(FIXTURE), "--emit", f"json={a}", "--emit", f"excellon={b}"]
    ) == 0
    assert a.is_file() and b.is_file()
    assert a.read_bytes() != b.read_bytes()


def test_case_distinct_basenames_in_distinct_directories_are_both_written(
    fake_source, tmp_path
):
    """A fold applied to the basename alone would refuse this pair, which
    names two genuinely different files on every filesystem."""
    fake_source(read())
    left = tmp_path / "d1"
    right = tmp_path / "d2"
    left.mkdir()
    right.mkdir()
    a = left / "out.json"
    b = right / "OUT.json"

    assert cli.main(
        [str(FIXTURE), "--emit", f"json={a}", "--emit", f"excellon={b}"]
    ) == 0
    assert a.is_file() and b.is_file()
    assert a.read_bytes() != b.read_bytes()


def test_the_comparison_key_never_becomes_the_written_path(fake_source, tmp_path):
    """The fold decides only whether two targets collide. The bytes go to
    the spelling the caller typed: an upper-case target is created
    upper-case, not lower-cased into the comparison key. This bites on a
    case-insensitive volume too, because APFS is case- and
    normalisation-preserving -- the directory entry records the spelling
    the file was created with."""
    fake_source(read())
    target = tmp_path / "OUT.JSON"

    assert cli.main([str(FIXTURE), "--emit", f"json={target}"]) == 0
    assert "OUT.JSON" in os.listdir(tmp_path)
    assert json.loads(target.read_text())


def test_a_directory_at_one_target_withholds_the_whole_set(fake_source, tmp_path, capsys):
    """F2-02(a)/F3-03: a directory at one target must not let an earlier,
    otherwise-ordinary target commit first -- the whole set is validated
    before any of it is rendered, so nothing reaches disk at all."""
    fake_source(read())
    a = tmp_path / "a.json"
    outdir = tmp_path / "outdir"
    outdir.mkdir()

    exit_code = cli.main([str(FIXTURE), "--emit", f"json={a}", "--emit", f"excellon={outdir}"])

    assert exit_code == 3
    assert not a.exists(), (
        "a.json was committed even though this invocation overall failed -- the "
        "whole target set must be validated before anything is rendered"
    )
    assert "Traceback" not in capsys.readouterr().err


def test_the_target_set_is_checked_before_the_panel_is_even_opened(tmp_path, capsys):
    """Mirrors test_the_case_is_checked_before_the_file_is_even_opened: a
    colliding --emit pair is reported without a PDF parse being attempted."""
    dup = tmp_path / "dup.x"

    exit_code = cli.main(["/no/such/panel.ai", "--emit", f"json={dup}", "--emit", f"excellon={dup}"])

    assert exit_code == 3
    assert str(dup) in capsys.readouterr().err


def test_an_ordinary_writable_target_still_passes_the_domain_check(fake_source, tmp_path):
    """Control for the two domain-boundary tests below: an everyday target
    in a writable directory is unaffected by the new pre-flight."""
    fake_source(read())
    target = tmp_path / "out.json"

    assert cli.main([str(FIXTURE), "--emit", f"json={target}"]) == 0
    assert target.exists()


def test_a_target_whose_parent_is_not_writable_is_rejected_before_committing(
    fake_source, tmp_path, capsys
):
    """The target-domain decision (ADR-0005): a target whose parent
    directory cannot accept a new file is refused by ``stage_payload``
    itself, not restated in the pre-flight (ticket 35). The invocation
    still withholds the whole set with a clean usage error and nothing
    on disk -- it now costs a render first, which the pre-flight's own
    docstring states rather than hides."""
    fake_source(read())
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    if os.access(locked, os.W_OK):
        locked.chmod(0o700)
        pytest.skip("this account can write into a mode-0500 directory")
    target = locked / "out.json"

    try:
        exit_code = cli.main([str(FIXTURE), "--emit", f"json={target}"])
    finally:
        locked.chmod(0o700)

    assert exit_code == 3
    assert not target.exists()
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes on this platform")
def test_a_fifo_target_is_refused_by_the_preflight_without_being_opened(tmp_path, capsys):
    """Ticket 35: an existing target that is not a regular file -- a named
    pipe here -- is refused by ``_preflight_targets`` itself, by a raise,
    not a wait. ADR-0005 admits a FIFO to the write mechanism's own
    domain, but this command line's commit loop reads a target's prior
    bytes before replacing it, and nothing is writing to the other end of
    this pipe -- so a regression that dropped the check would hang this
    test rather than merely fail it. The input path does not exist, which
    proves the refusal happens before the panel is even opened, matching
    test_the_target_set_is_checked_before_the_panel_is_even_opened."""
    fifo = tmp_path / "out.drl"
    os.mkfifo(fifo)

    exit_code = cli.main(["/no/such/panel.ai", "--emit", f"excellon={fifo}"])

    assert exit_code == 3
    assert str(fifo) in capsys.readouterr().err


_DEV_NULL = Path("/dev/null")


def _dev_is_locked_down() -> bool:
    """True when /dev refuses a new sibling file for an unprivileged user --
    the precondition the narrowed-domain reproduction below needs."""
    probe = _DEV_NULL.with_name(".ticket29_dev_probe.tmp")
    try:
        probe.write_bytes(b"x")
    except OSError:
        return True
    else:
        probe.unlink()
        return False


@pytest.mark.skipif(not _DEV_NULL.exists(), reason="no /dev/null on this platform")
@pytest.mark.skipif(
    not _dev_is_locked_down(),
    reason="this account can create files directly in /dev -- narrowing precondition absent",
)
def test_dev_null_is_a_clean_usage_error_before_anything_renders(fake_source, capsys):
    """F3-02's transaction half: /dev's own directory cannot accept a
    sibling temporary, so /dev/null is refused by the pre-flight -- a
    clean usage error before rendering, not the mid-transaction
    PermissionError the mechanism silently narrowed to. The ability to
    write a device or pipe target itself is not restored by this ticket;
    see the target-domain paragraph this ticket adds to ADR-0005."""
    fake_source(read())

    exit_code = cli.main([str(FIXTURE), "--emit", f"excellon={_DEV_NULL}"])

    assert exit_code == 3
    assert "Traceback" not in capsys.readouterr().err


def test_a_commit_phase_failure_rolls_back_every_already_replaced_target(
    fake_source, tmp_path, monkeypatch, capsys
):
    """F6-01: a failure part-way through the commit loop -- after an
    earlier target has already been swapped to this run's bytes -- must
    restore that earlier target too, not merely discard the ones still
    unattempted. Sabotages the *second* call to ``os.replace`` (the
    commit loop's own primitive), a distinct failure point from the
    staging-write sabotage the tests above this section already cover.
    """
    fake_source(read())
    a = tmp_path / "a.json"
    b = tmp_path / "b.svg"
    a.write_text("OLD-A")
    b.write_text("OLD-B")

    real_replace = os.replace
    calls = {"n": 0}

    def sabotage_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated commit-phase failure on the 2nd target")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", sabotage_replace)

    exit_code = cli.main([str(FIXTURE), "--emit", f"json={a}", "--emit", f"drawing-svg={b}"])

    assert exit_code == 3
    assert a.read_bytes() == b"OLD-A", (
        "target a should have been rolled back to what the previous run left, "
        "but its os.replace (call #1) had already landed this run's new bytes"
    )
    assert b.read_bytes() == b"OLD-B"
    assert "Traceback" not in capsys.readouterr().err


class _SimulatedFailure(Exception):
    """Marks a failure this test injects, distinct from a real OSError."""


@pytest.mark.parametrize(
    ("position", "kind"),
    [
        (position, kind)
        for position in ("first", "middle", "last")
        for kind in ("staging", "the pre-commit read", "the commit")
    ],
)
def test_every_position_and_failure_kind_leaves_no_temporary_behind(
    position: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 1 (ticket 35): the leak is closed at every position and
    every failure kind. Three real targets, seeded with distinct prior
    bytes so "restored" is distinguishable from "never written", swept
    across {first, middle, last} x {staging fails, the pre-commit read
    fails, the commit fails}. After the raise, the directory holds
    exactly the three target names -- no temporary of any shape -- and
    every target holds its seeded prior bytes. Supersedes the falsify
    suite's F2-01/F3-01 leak reproductions; see report-35 for both
    falsifiers this test was run against.
    """
    index = {"first": 0, "middle": 1, "last": 2}[position]
    names = ["a.json", "b.drl", "c.svg"]
    prior = [b"OLD-A", b"OLD-B", b"OLD-C"]
    new_text = ["NEW-A", "NEW-B", "NEW-C"]
    targets = [tmp_path / name for name in names]
    for target, data in zip(targets, prior):
        target.write_bytes(data)

    class _FakeEmitter:
        name: ClassVar[str] = "fake"
        media_type: ClassVar[str] = "text/plain"
        extension: ClassVar[str] = "txt"

        def emit(self, data: DrillData) -> protocols.Payload:
            raise NotImplementedError("this fake never renders; payloads are supplied directly")

    rendered: list[tuple[cli.Emitter[DrillData], Path, protocols.Payload]] = [
        (_FakeEmitter(), target, new_text[i]) for i, target in enumerate(targets)
    ]
    failing = targets[index]

    if kind == "staging":
        real_stage = cli.stage_payload

        def fake_stage(path: Path, payload: protocols.Payload) -> protocols.StagedWrite:
            if path == failing:
                raise _SimulatedFailure("staging")
            return real_stage(path, payload)

        monkeypatch.setattr(cli, "stage_payload", fake_stage)
        with pytest.raises(_SimulatedFailure):
            cli._stage(rendered)
    else:
        staged = cli._stage(rendered)
        if kind == "the pre-commit read":
            real_read_bytes = Path.read_bytes

            def fake_read_bytes(self: Path, *args: object, **kwargs: object) -> bytes:
                if self == failing:
                    raise _SimulatedFailure("read")
                return real_read_bytes(self, *args, **kwargs)

            monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
        else:
            real_commit = cli.commit_staged

            def fake_commit(written: protocols.StagedWrite) -> int:
                if written.path == failing:
                    raise _SimulatedFailure("commit")
                return real_commit(written)

            monkeypatch.setattr(cli, "commit_staged", fake_commit)

        with pytest.raises(_SimulatedFailure):
            cli._commit(staged)

    # Undo the patches before inspecting the result: the assertions below
    # read the same targets and must see the real filesystem, not the
    # injected failure.
    monkeypatch.undo()

    assert sorted(p.name for p in tmp_path.iterdir()) == names, (
        f"a temporary survived the {kind!r} failure at the {position} position"
    )
    for target, data in zip(targets, prior):
        assert target.read_bytes() == data, (
            f"{target} was not restored to its seeded prior bytes after the "
            f"{kind!r} failure at the {position} position"
        )


def test_re_running_over_existing_targets_leaves_no_backup_files_behind(fake_source, tmp_path):
    """A normal successful re-run over its own previous outputs must leave
    nothing behind beyond the requested target itself -- the backup this
    loop makes while committing is cleaned up once the whole set succeeds."""
    fake_source(read())
    a = tmp_path / "a.json"

    assert cli.main([str(FIXTURE), "--emit", f"json={a}"]) == 0
    first = a.read_bytes()

    assert cli.main([str(FIXTURE), "--emit", f"json={a}"]) == 0

    assert a.read_bytes() == first
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json"], (
        "a successful commit over an existing target left a stray file behind"
    )


# ---------------------------------------------------------------------------
# ticket 26: the CLI writes an artefact's bytes through the one published
# mechanism (stompmodel.protocols.stage_payload / commit_staged /
# discard_staged), never by re-implementing it. Naming each function's
# production caller directly, rather than only its observable effect, is
# what F1-01/F2-01/F3-04/F5-01 asked for and what criterion 2 demands.
# ---------------------------------------------------------------------------


def test_control_spies_detect_a_real_call_to_each_write_function(tmp_path):
    """Control: prove the spy mechanism the next test relies on actually
    catches a call, before trusting it to prove an absence."""
    calls: list[str] = []
    original_stage, original_commit = protocols.stage_payload, protocols.commit_staged

    def spy_stage(path, payload):
        calls.append("stage")
        return original_stage(path, payload)

    def spy_commit(staged):
        calls.append("commit")
        return original_commit(staged)

    target = tmp_path / "control.bin"
    written = spy_commit(spy_stage(target, b"hello"))

    assert calls == ["stage", "commit"]
    assert written == 5
    assert target.read_bytes() == b"hello"


def test_the_cli_write_path_calls_stage_payload_then_commit_staged(fake_source, tmp_path, monkeypatch):
    """F1-01/F2-01/F3-04/F5-01, migrated: a full ``--emit`` run must call the
    published mechanism, not re-implement it (``write_payload`` no longer
    exists; the design verdict deletes it outright). Patched on ``cli``, not
    on ``stompmodel.protocols``: ``cli.py`` imports both names directly, so
    a caller must patch the reference the CLI actually holds.
    """
    fake_source(read())
    calls: list[str] = []
    original_stage, original_commit = cli.stage_payload, cli.commit_staged

    def spy_stage(path, payload):
        calls.append(("stage", path))
        return original_stage(path, payload)

    def spy_commit(staged):
        calls.append(("commit", staged.path))
        return original_commit(staged)

    monkeypatch.setattr(cli, "stage_payload", spy_stage)
    monkeypatch.setattr(cli, "commit_staged", spy_commit)

    out = tmp_path / "out.json"
    code = cli.main([str(FIXTURE), "--emit", f"json={out}"])

    assert code in (0, 1)
    assert out.exists() and out.read_text(encoding="utf-8").strip() != ""
    assert calls == [("stage", out), ("commit", out)], (
        "the CLI's write path did not call stompmodel.protocols.stage_payload "
        f"then commit_staged, in that order, for {out}: saw {calls}"
    )


def test_a_write_failure_calls_discard_staged_on_every_temporary_it_abandons(
    fake_source, tmp_path, monkeypatch
):
    """``discard_staged``'s production caller, named directly: a failure at
    one target must discard every *other* staged write through the
    published function, not through a caller-local ``tmp.unlink``. Patched
    on ``cli`` for the same reason as the test above.
    """
    fake_source(read())
    a = tmp_path / "a.json"
    b = tmp_path / "b.drl"
    discarded: list[Path] = []
    original_discard = cli.discard_staged

    def spy_discard(staged):
        discarded.append(staged.path)
        original_discard(staged)

    monkeypatch.setattr(cli, "discard_staged", spy_discard)
    _sabotage_write(monkeypatch, b)

    code = cli.main([str(FIXTURE), "--emit", f"json={a}", "--emit", f"excellon={b}"])

    assert code == 3
    assert not a.exists() and not b.exists()
    # ``a`` staged successfully and was then discarded when ``b``'s own
    # staging failed; ``b`` never reached ``discard_staged`` because it
    # never produced a ``StagedWrite`` to discard in the first place.
    assert discarded == [a]


def test_a_successful_runs_report_lines_stay_in_emit_order(fake_source, tmp_path, capsys):
    """A successful run's per-artefact sentences print in ``--emit`` order."""
    fake_source(read())
    a = tmp_path / "a.json"
    b = tmp_path / "b.drl"
    c = tmp_path / "c.svg"

    assert (
        cli.main(
            [
                str(FIXTURE),
                "--emit",
                f"json={a}",
                "--emit",
                f"excellon={b}",
                "--emit",
                f"drawing-svg={c}",
            ]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert out.index(str(a)) < out.index(str(b)) < out.index(str(c))


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
    assert "Drill" in out, "the report omitted the drill layer name"
    assert "Background" in out, "the report omitted the reference layer name"
    # 100 × 50, not the 99.6 × 50.4 the artwork measured: the enclosure is
    # identified on every panel, and the report states the catalogue's own
    # figures because those are what the holes are positioned against.
    assert "100.000" in out, "the report omitted the catalogue width"
    assert "50.000" in out, "the report omitted the catalogue height"
    assert "7.000" in out, "the report omitted the first hole diameter"  # hole diameters
    assert "5.000" in out, "the report omitted the second hole diameter"  # hole diameters
    assert "T1" in out, "the report omitted the first tool"  # tool summary
    assert "T2" in out, "the report omitted the second tool"  # tool summary
    assert "something" in out, "the report omitted the diagnostic code"
    assert "watch out" in out, "the report omitted the diagnostic message"


def report_diagnostic_groups(out: str) -> dict[str, list[str]]:
    """``{"error": ["unknown-diameter"], …}`` — the DIAGNOSTICS block as printed."""
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
    """One finding of each severity, one rendering of each."""
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
    assert "  error (1)" in out, "the diagnostics header omitted the error count"
    assert "  warning (1)" in out, "the diagnostics header omitted the warning count"
    assert "  info (1)" in out, "the diagnostics header omitted the info count"
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
    """The ``xN`` column is ``DrillData.tool_counts()``, not a third re-count."""
    calls = []

    class SpyData(DrillData):
        def tool_counts(self):
            calls.append(tuple(self.tools()))
            return {diameter: 99 for diameter in self.tools()}

    data = SpyData(
        holes=document().holes,
        reference=ReferenceOutline(Nanometre(112_000_000), Nanometre(61_000_000)),
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
    """Distinct close nominals receive enough precision to remain distinct."""
    data = document(
        holes=[
            Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(6_999_800)).with_number(6),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(2),
        ]
    )
    assert len(data.tools()) == 2  # the fixture must actually pose the problem

    printed = report_tool_diameters(cli.format_tools(data))

    assert len(printed) == 2
    assert len(set(printed)) == 2, f"two tools printed the same diameter: {printed}"


def test_the_tools_report_keeps_its_usual_three_decimals():
    """Ordinary non-colliding diameters retain three decimals."""
    assert report_tool_diameters(cli.format_tools(document())) == ["5.000", "7.000"]


def test_the_tools_block_spells_a_bit_the_way_the_standard_that_ran_spells_it():
    """The spelling comes from provenance, exactly as the drawing's schedule takes it,
    because a fractional bit has no honest millimetre name.
    """
    data = document(
        holes=[
            Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(7_143_750)).with_number(3),
            Hole.from_measurement(Nanometre(0), Nanometre(-18_750_000), Nanometre(5_159_375)).with_number(1),
        ],
        processing=[quantised_against("fractional", size_count=64)],
    )

    assert report_tool_labels(cli.format_tools(data)) == {1: '⌀13/64"', 2: '⌀9/32"'}


def test_a_recorded_standard_the_registry_does_not_hold_is_not_a_standard():
    """Unknown or absent recorded standards fall back to millimetres."""
    assert report_tool_labels(cli.format_tools(document())) == {
        1: "⌀5.000 mm",
        2: "⌀7.000 mm",
    }

    data = document(processing=[quantised_against("whitworth")])

    assert report_tool_labels(cli.format_tools(data)) == {1: "⌀5.000 mm", 2: "⌀7.000 mm"}


def test_a_standards_own_spelling_still_may_not_print_one_diameter_as_two_tools():
    """A standard's spelling may not print one diameter as two tools."""
    data = document(
        holes=[
            Hole.from_measurement(Nanometre(-20_000_000), Nanometre(18_000_000), Nanometre(6_999_800)).with_number(6),
            Hole.from_measurement(Nanometre(20_000_000), Nanometre(18_000_000), Nanometre(7_000_000)).with_number(2),
        ],
        processing=[quantised_against("metric")],
    )

    printed = report_tool_labels(cli.format_tools(data))

    assert len(set(printed.values())) == 2, f"two tools printed the same diameter: {printed}"


def test_report_shows_raw_values_beside_nominal(fake_source, capsys):
    fake_source(read(holes=[RawHole(Millimetre(-19.9906), Millimetre(18.0021), Millimetre(6.9998))]))
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
    """The report separates measured and snapped outlines.

    Four raw decimals and three nominal decimals prevent the values printing alike.
    """
    fake_source(read())

    assert cli.main([str(FIXTURE)]) == 0

    reference = report_field(capsys.readouterr().out, "reference")
    assert "100.000 x 50.000 mm" in reference
    assert "99.6000 x 50.4000 mm" in reference


def test_the_report_states_which_enclosure_the_panel_was_identified_as(fake_source, capsys):
    """The report names the enclosure carried by the sheet and JSON document."""
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
    """The question the list asks has been answered, so the report answers it — the same
    rule the drawing's title block follows. A turned panel says so, because the
    catalogue's own orientation is what is printed beside it.
    """
    data = dataclasses.replace(
        document(),
        enclosure=EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(119_500_000),
            width_nm=Nanometre(94_000_000),
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


def test_the_hole_table_numbers_follow_the_route_not_the_artwork_order(fake_source, capsys):
    """The ``No.`` column is ``Hole.index``: the drill sequence ``RouteHoles``
    assigns, the same identity the diagnostics and the drawing's balloons use —
    not the order the circles were drawn in.
    """
    fake_source(
        read(
            holes=[
                RawHole(Millimetre(20.0), Millimetre(18.0), Millimetre(7.0)),
                RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0)),
                RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(7.0)),
            ]
        )
    )
    cli.main([str(FIXTURE)])
    rows = [
        line.split()
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("  ") and line.split() and line.split()[0].isdigit()
    ]
    numbers = [int(row[0]) for row in rows]
    xs = [row[2] for row in rows]

    assert numbers == [1, 2, 3]
    assert xs == ["-20.000", "0.000", "20.000"], "route order, not the drawn order 20, -20, 0"


def test_verbose_reports_every_stage_the_cli_built(fake_source, capsys):
    """Verbose output enumerates every stage returned by ``build_pipeline``."""
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
    """The phase is where holes are dropped and most findings are made."""
    fake_source(
        read(
            holes=[
                RawHole(Millimetre(-20.0), Millimetre(18.0), Millimetre(7.0)),
                RawHole(Millimetre(0.0), Millimetre(18.0), Millimetre(30.0)),  # no bit makes this
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
    """``--verbose`` must not be a second, divergent fold."""
    args = cli.build_parser().parse_args(["panel.ai", "--grid", "0.5"])
    pipeline = cli.build_pipeline(args)
    data = document()

    plain = cli.run_pipeline(pipeline, data)
    traced = cli.run_pipeline(pipeline, data, trace=lambda *_: None)

    assert traced.processing == plain.processing
    assert [run.name for run in traced.processing] == [stage.name for stage in pipeline]
    assert traced.last_run("route") is not None


def test_the_grid_reaches_the_drawing_through_the_quantiser_not_the_options(
    fake_source, tmp_path
):
    """``--grid`` is handed to ``SnapPositions``, and to nothing else."""
    fake_source(read())
    svg = tmp_path / "out.svg"
    # 1, not 0: a 0.5 mm grid moves a hole far enough to raise ``off-grid``.
    assert cli.main([str(FIXTURE), "--grid", "0.5", "--emit", f"drawing-svg={svg}"]) == 1
    text = svg.read_text()
    # Three decimals, like every other length on the sheet and in the drill
    # file: the micron floor is justified by both artifacts printing three, so
    # the stamp has to be one of them.
    assert "GRID 0.500 mm" in text
    assert "GRID 0.250 mm" not in text


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
    """``[(no, x, y, diameter, tool)]`` from the drawing's hole schedule."""
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
    """Two renderings of one tool table, parsed back out of what was printed."""
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
    """Two artefacts, one run, parsed back as text: they must say the same thing."""
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
    # holes by ``Hole.index`` — the drill sequence ``RouteHoles`` assigns, 1..n
    # over the routed, deduplicated holes, not the artwork's traversal order.
    # The position join below is the real cross-artifact check: it proves the
    # two artifacts agree on which physical hole each number names, not merely
    # that both count 1..7.
    assert balloons == [number for number, *_ in rows] == [1, 2, 3, 4, 5, 6, 7]
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
# end to end against the fixture
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

    assert drl.exists(), "the excellon artefact was not written"
    assert svg.exists(), "the drawing-svg artefact was not written"
    assert doc.exists(), "the json artefact was not written"
    assert drl.read_text().startswith("M48")
    ET.fromstring(svg.read_text())  # parses as XML

    document = json.loads(doc.read_text())
    assert len(document["holes"]) == 7
    assert len(document["tools"]) == 2
    assert sorted(t["diameter_nm"] for t in document["tools"]) == [5_000_000, 7_000_000]

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
    assert str(drl) in out, "the report omitted the excellon path"
    assert str(svg) in out, "the report omitted the drawing-svg path"


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
    """The fixture identifies as 1590B while retaining its measurement.

    113 × 60 mm artwork differs from the 112.40 × 60.50 mm catalogue footprint.
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
    """The fixture panel undeclared is refused and writes nothing."""
    doc = tmp_path / "tar.json"

    assert cli.main([str(FIXTURE), "--emit", f"json={doc}"]) == 2

    out = capsys.readouterr().out
    assert "[ambiguous-enclosure]" in out
    assert "1590BS" in out, "the ambiguous-enclosure report omitted the 1590BS candidate"
    assert "1590B2" in out, "the ambiguous-enclosure report omitted the 1590B2 candidate"
    assert not doc.exists(), "a document naming one of two enclosures reached the disk"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_fixture_panel_declared_as_a_case_it_does_not_fit_exits_two(tmp_path, capsys):
    """The real fixture, end to end: exit 2 and nothing on disk to load."""
    doc = tmp_path / "tar.json"
    assert cli.main([str(FIXTURE), "--case", "1590BB", "--emit", f"json={doc}"]) == 2

    assert "[unmatched-enclosure]" in capsys.readouterr().out
    assert not doc.exists()


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_the_pdf_format_is_offered_and_writes_a_pdf(tmp_path, capsys):
    """--emit resolves through the registry; the CLI never names a format."""
    out = tmp_path / "panel.pdf"

    code = cli.main([str(FIXTURE), "--case", "1590B", "--emit", f"drawing-pdf={out}"])

    assert code in (0, 1)
    assert out.read_bytes().startswith(b"%PDF-1.7")
    assert "drawing-pdf" in capsys.readouterr().out


def test_the_pdf_emitter_receives_the_title_from_the_command_line():
    from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter

    emitter = cli.make_emitter("drawing-pdf", cli.OutputSettings(title="TAR PANEL"))

    assert isinstance(emitter, DrawingPdfEmitter)
    assert emitter.options.text.title == "TAR PANEL"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture missing")
def test_an_error_run_withholds_the_pdf_like_every_other_artefact(tmp_path, capsys):
    """Any error withholds every requested artefact; ADR-0001."""
    out = tmp_path / "panel.pdf"

    # No --case, so tar.ai is ambiguous-enclosure, which is an error.
    code = cli.main([str(FIXTURE), "--emit", f"drawing-pdf={out}"])

    assert code == 2
    assert not out.exists()
    assert "wrote nothing" in capsys.readouterr().out


def test_the_help_lists_the_pdf_format():
    parser = cli.build_parser()

    assert "drawing-pdf" in parser.format_help()


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
    """Two faults, two remedies. Paths that are not circles are a drawing problem, and
    telling that operator to add a stroke sends them to the wrong place.
    """
    error = EmptyLayerError("Drill", path_count=1)
    assert error.path_count == 1
    message = str(error)
    assert "1 path" in message
    assert "circle" in message
    assert "stroke" not in message


def test_the_two_empty_layer_causes_do_not_read_alike():
    assert str(EmptyLayerError("Drill")) != str(EmptyLayerError("Drill", path_count=3))


# ---------------------------------------------------------------------------
# the case model: flags, pipeline composition and the report
# ---------------------------------------------------------------------------


def test_case_face_accepts_only_box_or_lid():
    from stompdrill.cli import UsageError, parse_face
    from stompmodel.model import CaseFace

    assert parse_face("box") is CaseFace.BOX
    assert parse_face("LID") is CaseFace.LID
    with pytest.raises(UsageError, match="box"):
        parse_face("flange")


def test_emitting_step_without_a_case_model_is_a_usage_error(tmp_path, capsys):
    from stompdrill.cli import main

    code = main(["panel.ai", "--emit", f"step={tmp_path / 'o.stp'}"])

    assert code == 3
    assert "--case-model" in capsys.readouterr().err


def test_an_unreadable_case_model_is_a_usage_error(tmp_path, capsys):
    from stompdrill.cli import main

    code = main(["panel.ai", "--case-model", str(tmp_path / "absent.stp")])

    assert code == 3


def test_a_negative_case_margin_is_a_usage_error(tmp_path, capsys):
    from stompdrill.cli import main

    code = main(["panel.ai", "--case-model", "x.stp", "--case-margin", "-1"])

    assert code == 3
    assert "--case-margin" in capsys.readouterr().err


def test_the_case_margin_default_is_one_millimetre():
    from stompdrill.cli import build_parser

    args = build_parser().parse_args(["panel.ai"])

    assert args.case_margin == 1.0


def test_the_case_face_default_is_box():
    from stompdrill.cli import build_parser

    args = build_parser().parse_args(["panel.ai"])

    assert args.case_face == "box"


def test_a_case_model_appends_the_clearance_stage_last():
    from stompdrill.cli import build_parser, build_pipeline
    from tests.conftest import FakeCase

    args = build_parser().parse_args(["panel.ai"])
    args.case_model_object = FakeCase()

    assert [stage.name for stage in build_pipeline(args)][-1] == "check-case-clearance"


def test_containment_runs_after_deduplication_so_a_repeat_is_reported_once():
    """Ordering is the one thing a stage cannot self-declare; assert it here."""
    names = [stage.name for stage in pipeline_for()]

    assert names.index("deduplicate") < names.index("check-outline-containment")


def test_a_panel_whose_holes_are_all_inside_still_exits_clean(fake_source, capsys):
    """The other half of the pair: the stage must not warn about every panel."""
    fake_source(read())

    assert cli.main(["panel.ai"]) == 0

    assert "hole-outside-outline" not in capsys.readouterr().out


def test_a_hole_outside_the_outline_exits_one_and_still_writes_the_artefact(
    fake_source, tmp_path, capsys
):
    """A warning, so the drill file is written.

    ``read()``'s default 99.6 x 50.4 outline quantises to the catalogue's
    100 x 50 mm and raises nothing at all, so the containment finding is the
    only thing between this run and exit 0. The hole overshoots x by 1.5 mm.
    """
    fake_source(read(holes=(RawHole(Millimetre(48.0), Millimetre(0.0), Millimetre(7.0)),)))
    target = tmp_path / "out.drl"

    assert cli.main(["panel.ai", "--emit", f"excellon={target}"]) == 1

    assert "hole-outside-outline" in capsys.readouterr().out
    assert target.exists()


def _case_checked_document():
    """A ``DrillData`` carrying the two carriers a real ``--case-model`` run
    produces: the typed ``CaseRegistration`` and the clearance stage's own
    ``StageRun`` provenance -- not a stand-in that shares field names by
    construction.
    """
    from stompdrill.pipeline import CheckCaseClearance
    from tests.conftest import FakeCase, at, make_data

    stage = CheckCaseClearance(FakeCase())
    data = stage.apply(
        make_data(
            at(-1_000_000, 2_000_000, 5_000_000, index=1),
            at(3_000_000, -4_000_000, 4_000_000, index=2),
        )
    )
    return data.with_processing(stage.describe())


def test_the_report_names_the_model_face_and_play_area():
    """``format_case`` reads identity from ``.case`` and plate/play area from
    the clearance stage's own provenance -- the two carriers a real run
    produces -- rather than a live ``CaseModel`` handle.
    """
    from stompdrill.cli import format_case

    lines = "\n".join(format_case(_case_checked_document()))

    assert "CASE MODEL" in lines
    assert "1590BB" in lines
    assert "box" in lines
    assert "plate" in lines
    assert "play area" in lines


def test_report_is_byte_identical_after_a_codec_round_trip_with_a_case():
    """The report the live pipeline result prints and the report a document
    round-tripped through the codec prints must agree byte for byte -- the
    behaviour lock cannot see this, since it excludes standard output, so
    this equality is what protects a report regression instead.
    """
    from stompdrill.cli import format_report
    from stompmodel.codec import from_document, to_document

    live = _case_checked_document()
    restored = from_document(to_document(live))

    live_report = format_report(live)
    restored_report = format_report(restored)

    assert live_report == restored_report
    assert "CASE MODEL" in live_report
    assert "1590BB" in live_report


def test_the_report_states_the_rotated_panels_reframed_play_area():
    """A rotated panel's play area line states the frame ``apply()`` actually
    checked holes against -- the clearance stage's own reframed provenance
    (ADR-0007, ticket 19) -- not the live model's permanently unrotated
    ``play_area_nm``. The two genuinely disagree for a rotated panel; per
    progress.md Phase 7 ruling R1, a changed line here is ticket 19 finally
    reaching the report, not this ticket regressing it. Fix-round-1 finding:
    the byte-identical round-trip test above never exercised a rotated panel
    (``_case_checked_document`` supplies no enclosure, so ``apply()`` takes
    the identity fast path), so nothing pinned this number before now.
    """
    from stompdrill.cli import format_case
    from stompdrill.pipeline import CheckCaseClearance
    from tests.conftest import FakeCase, at, make_data

    model = FakeCase()  # play_area_nm = (-50mm, -40mm, 50mm, 40mm)
    rotated = EnclosureMatch(
        family="Hammond 1590",
        length_nm=Nanometre(94_000_000),
        width_nm=Nanometre(119_500_000),
        candidates=(model.part,),
        selected_part=model.part,
        rotated=True,
    )
    stage = CheckCaseClearance(model)
    data = stage.apply(
        make_data(
            at(0, 0, 5_000_000, index=1),
            reference=ReferenceOutline(Nanometre(94_000_000), Nanometre(119_500_000)),
        ).with_enclosure(rotated)
    )
    data = data.with_processing(stage.describe())

    lines = "\n".join(format_case(data))

    # The reframed rectangle swaps axes relative to the model's own, still
    # unrotated ``model.play_area_nm``: 80 x 100 mm (x -40..40, y -50..50),
    # not the model's native 100 x 80 mm (x -50..50, y -40..40).
    assert model.play_area_nm == (
        Nanometre(-50_000_000),
        Nanometre(-40_000_000),
        Nanometre(50_000_000),
        Nanometre(40_000_000),
    )
    assert "80.000 x 100.000 mm" in lines
    assert "x -40.000…40.000" in lines
    assert "y -50.000…50.000" in lines
    # The falsified claim: the live model's own, unrotated rectangle must not
    # appear -- that would mean the report went back to the live handle.
    assert "100.000 x 80.000 mm" not in lines
    assert "x -50.000…50.000" not in lines


def test_format_report_reads_the_case_from_a_registration_alone():
    """A ``DrillData`` carrying only ``.case``, with no clearance provenance at
    all (e.g. hand-built, or a document from a tool that never ran the
    clearance stage), still states identity -- it must not require the live
    ``CaseModel`` handle ``format_report`` no longer accepts.

    Reproduces .scratch/architecture-review/falsify/tests/test_f2_02_case_report_from_data.py.
    """
    from stompdrill.cli import format_report
    from stompmodel.frames import CoordinateFrame, FaceFrame
    from stompmodel.model import CaseFace, CaseRegistration, DrillData

    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    registration = CaseRegistration("1590BB", CaseFace.BOX, "1590BB.stp", face)
    data = DrillData().with_case(registration)

    report = format_report(data)

    assert "CASE MODEL" in report


def test_format_report_states_the_case_a_restored_document_carries():
    """A document round-tripped through the codec, carrying a registration
    but no clearance provenance (the shape a second tool receives, per
    ADR-0009), still states identity and never raises -- it degrades to
    fewer lines, not an exception.

    Reproduces .scratch/architecture-review/falsify/tests/test_f2_02_case_report_blind.py.
    """
    from stompdrill.cli import format_report
    from stompmodel.codec import from_document, to_document
    from stompmodel.frames import CoordinateFrame, FaceFrame
    from stompmodel.model import CaseFace, CaseRegistration, DrillData

    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    registered = DrillData().with_case(CaseRegistration("1590BB", CaseFace.BOX, "1590BB.stp", face))
    data = from_document(to_document(registered))

    assert data.case is not None
    assert data.case.part == "1590BB"

    report = format_report(data)

    assert "CASE MODEL" in report
    assert "1590BB" in report
    # Identity only: no clearance stage ran, so there is no plate or play
    # area to state.
    assert "plate" not in report
    assert "play area" not in report


def test_case_plate_guard_ignores_a_value_of_the_wrong_shape():
    """``plate_nm`` is checked elementwise by ``StageRun``'s whole-nanometre
    guard (ADR-0004), which only inspects a *tuple* value's own elements --
    so a tuple where a scalar is expected is legitimately constructible, and
    ``format_case``'s own guard, not the type, must be what rejects it.
    """
    from stompdrill.cli import format_case
    from stompdrill.pipeline import CheckCaseClearance
    from stompmodel.frames import CoordinateFrame, FaceFrame
    from stompmodel.model import CaseFace, CaseRegistration, DrillData, StageRun

    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    registration = CaseRegistration("1590BB", CaseFace.BOX, "1590BB.stp", face)
    run = StageRun(
        CheckCaseClearance.name,
        (
            ("plate_nm", (2_250_000,)),
            ("play_area_nm", (-50_000_000, -40_000_000, 50_000_000, 40_000_000)),
        ),
    )
    data = DrillData(case=registration, processing=(run,))

    lines = "\n".join(format_case(data))

    assert "CASE MODEL" in lines
    assert "plate" not in lines
    assert "play area" in lines


def test_case_play_area_guard_ignores_a_value_of_the_wrong_shape():
    """A ``play_area_nm`` of the wrong length passes ``StageRun``'s
    elementwise nanometre check (every element is still a whole nanometre)
    but is the wrong shape to unpack as four corners, and only
    ``format_case``'s own guard catches that.
    """
    from stompdrill.cli import format_case
    from stompdrill.pipeline import CheckCaseClearance
    from stompmodel.frames import CoordinateFrame, FaceFrame
    from stompmodel.model import CaseFace, CaseRegistration, DrillData, StageRun

    face = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
            u=(1.0, 0.0, 0.0),
            v=(0.0, 1.0, 0.0),
            w=(0.0, 0.0, 1.0),
        )
    )
    registration = CaseRegistration("1590BB", CaseFace.BOX, "1590BB.stp", face)
    run = StageRun(
        CheckCaseClearance.name,
        (
            ("plate_nm", 2_250_000),
            ("play_area_nm", (-50_000_000, -40_000_000, 50_000_000)),
        ),
    )
    data = DrillData(case=registration, processing=(run,))

    lines = "\n".join(format_case(data))

    assert "CASE MODEL" in lines
    assert "plate" in lines
    assert "play area" not in lines


# ---------------------------------------------------------------------------
# case flags are validated unconditionally, whether or not a model was given
# ---------------------------------------------------------------------------


def test_an_invalid_case_face_is_a_usage_error_with_no_case_model(capsys):
    """A typo in --case-face must not wait for --case-model to be caught."""
    code = cli.main([str(FIXTURE), "--case", "1590B", "--case-face", "flange"])

    assert code == 3
    assert "--case-face" in capsys.readouterr().err


def test_a_negative_case_margin_is_a_usage_error_with_no_case_model(capsys):
    code = cli.main([str(FIXTURE), "--case", "1590B", "--case-margin", "-5"])

    assert code == 3
    assert "--case-margin" in capsys.readouterr().err


def test_a_zero_case_margin_is_a_usage_error_with_no_case_model(capsys):
    code = cli.main([str(FIXTURE), "--case", "1590B", "--case-margin", "0"])

    assert code == 3
    assert "--case-margin" in capsys.readouterr().err


def test_an_invalid_case_face_is_caught_before_the_file_is_even_opened(capsys):
    """The panel need not exist: the flag is wrong regardless of the input."""
    code = cli.main(["/no/such/panel.ai", "--case-face", "flange"])

    assert code == 3
    assert "--case-face" in capsys.readouterr().err


def test_an_unreadable_case_model_is_caught_before_the_file_is_even_opened(capsys):
    code = cli.main(["/no/such/panel.ai", "--case-model", "/nonexistent.stp"])

    assert code == 3
    assert "--case-model" in capsys.readouterr().err


def test_emitting_step_without_a_model_is_caught_before_the_file_is_even_opened(capsys):
    code = cli.main(["/no/such/panel.ai", "--emit", "step=x.stp"])

    assert code == 3
    assert "--case-model" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# end to end: a real Hammond model, through the whole command line
# ---------------------------------------------------------------------------


@pytest.mark.hammond
def test_a_clearance_error_withholds_every_artefact(tmp_path, capsys):
    """Any error withholds every requested artefact, including the drill file."""
    from stompdrill.cli import main

    panel = _panel_with_a_hole_in_a_boss(tmp_path)
    drl, stp = tmp_path / "o.drl", tmp_path / "o.stp"
    code = main([
        str(panel), "--case", "1590BB", "--case-model", str(_model_path()), "--case-face", "box",
        "--emit", f"excellon={drl}", "--emit", f"step={stp}",
    ])

    assert code == 2
    assert not drl.exists()
    assert not stp.exists()
    assert "wrote nothing" in capsys.readouterr().out


@pytest.mark.hammond
def test_a_clean_run_writes_both_artefacts(tmp_path):
    from stompdrill.cli import main

    panel = _panel_with_a_central_hole(tmp_path)
    drl, stp = tmp_path / "o.drl", tmp_path / "o.stp"
    code = main([
        str(panel), "--case", "1590BB", "--case-model", str(_model_path()),
        "--emit", f"excellon={drl}", "--emit", f"step={stp}",
    ])

    assert code == 0
    assert drl.exists(), "the excellon artefact was not written"
    assert stp.exists(), "the step artefact was not written"


@pytest.mark.hammond
def test_a_case_model_without_any_step_emit_still_checks_clearance(tmp_path, capsys):
    from stompdrill.cli import main

    panel = _panel_with_a_hole_in_a_boss(tmp_path)
    code = main([str(panel), "--case", "1590BB", "--case-model", str(_model_path())])

    assert code == 2
    assert "hole-through-boss" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# F3-03 / T21 -- a diameter that moves far is reported, and still drilled
# ---------------------------------------------------------------------------


def _panel_with_one_hole(tmp_path: Path, name: str, diameter_mm: float) -> Path:
    """A real 1590B backplate (CLAUDE.md) with one centred drill circle.

    112.40 x 60.50 mm is within tolerance of both 1590B/1590B2 and 1590BS,
    hence the explicit ``--case`` every caller of this helper must pass.
    """
    width, height = _pt_from_mm(112.40), _pt_from_mm(60.50)
    return build_pdf(
        tmp_path / name,
        {
            "Background": f"0 0 {width} {height} re S",
            "Drill": circle_ops(width / 2, height / 2, _pt_from_mm(diameter_mm) / 2),
        },
        media=(0, 0, width + 20, height + 20),
    )


def test_imperial_hardware_under_the_default_metric_standard_is_reported_not_silent(tmp_path):
    """A 7/8" (22.225 mm) hole drilled 22.0 mm under the default metric standard.

    Before F3-03/T21: exit 0, an empty ``diagnostics`` array, and a hole cut
    0.225 mm undersize with nothing anywhere stating it moved. That silence
    was the defect -- see ``.scratch/architecture-review/issues/
    36-the-tool-says-how-far-it-moved-the-diameter.md``.
    """
    panel = _panel_with_one_hole(tmp_path, "pedal.ai", 22.225)
    out_json = tmp_path / "out.json"

    exit_code = cli.main([str(panel), "--case", "1590B", "--emit", f"json={out_json}"])

    doc = json.loads(out_json.read_text())
    diagnostics = doc["diagnostics"]
    hole = doc["holes"][0]

    # The hole is still drilled: still one hole, still numbered, still the
    # nearest stocked size -- a reported hole is not a rejected one.
    assert exit_code == 1, "a departure this loud is a warning, not a clean exit"
    assert hole["diameter_nm"] == 22_000_000
    assert hole["index"] == 1
    assert abs(hole["raw"]["diameter"] - 22.225) < 1e-6

    assert [d["code"] for d in diagnostics] == ["off-size"]
    finding = diagnostics[0]
    assert finding["severity"] == "warning"
    assert finding["data"]["moved_nm"] == -225_000, "undersize is negative"


def test_the_reported_hole_still_reaches_the_toolpath(tmp_path):
    """The warned hole is cut: it is one of the tool definitions in the drill file."""
    panel = _panel_with_one_hole(tmp_path, "pedal2.ai", 22.225)
    drl = tmp_path / "out.drl"

    exit_code = cli.main([str(panel), "--case", "1590B", "--emit", f"excellon={drl}"])

    assert exit_code == 1
    lines = drl.read_text().splitlines()
    assert "T1C22.000" in lines, "the drilled 22.0 mm bit has a tool definition"
    assert lines.count("T1") == 1, "the one hole reaches the toolpath under that tool"
