"""The command-line contract, driven end to end.

Every test here goes through ``cli.main`` and asserts an exit code, because
the codes are a contract: 0 clean, 1 warnings, 2 errors, 3 usage or IO.
A diagnostic that exists but reaches no exit code is a rule the operator
never meets. Two rows -- the STEP refusal and the A1 sheet choice -- name a
claim about an emitter's own behaviour rather than a code the CLI reports,
so those two drive the emitter directly, matching how the existing suite
already tests each (``test_step_emitter.py``, ``test_drawing_sheet.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stompdrill import cli
from stompmodel.units import Nanometre
from tests.conftest import FakeCase, at, build_pdf, circle_ops, make_data

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

# ---------------------------------------------------------------------------
# rows 1 and 8: the source reads what the command line tells it to
# ---------------------------------------------------------------------------


def test_the_layer_flags_choose_which_layers_the_source_reads(tmp_path, capsys):
    """Both flags on one command line, against artwork whose layers are named
    nothing like the defaults. A default that happened to match would make a
    passing test say nothing."""
    panel = build_pdf(
        tmp_path / "panel.pdf",
        {
            "Cuts": circle_ops(50, 50, 3.5) + " " + circle_ops(80, 50, 3.5),
            "Card": "10 10 300 200 re S",
        },
    )

    code = cli.main([
        str(panel), "--drill-layer", "Cuts", "--reference-layer", "Card",
        "--emit", f"json={tmp_path / 'out.json'}",
    ])

    assert code in (0, 1), capsys.readouterr().out
    assert len(json.loads((tmp_path / "out.json").read_text())["holes"]) == 2


def test_naming_a_layer_that_is_not_there_is_a_usage_failure(tmp_path):
    """The other half: the flag is read, not ignored."""
    panel = build_pdf(tmp_path / "panel.pdf", {"Cuts": circle_ops(50, 50, 3.5)})

    assert cli.main([str(panel), "--drill-layer", "Nope"]) == 3


def test_an_even_odd_clip_is_not_geometry_either(tmp_path, capsys):
    """``W`` is covered at ``test_ai_pdf.py:226``. ``W*`` is the same rule with
    the other fill sense, and ``n`` -- not ``W`` -- is what makes a path
    invisible, so the two operators must be handled alike.

    The clip marker is itself a circle, not a rectangle: a rectangle wrongly
    let through would still be dropped as non-circular, proving nothing about
    ``W*``. A circle wrongly let through survives that filter and counts as a
    second hole, so the assertion below actually depends on ``W*`` clipping.
    """
    panel = build_pdf(
        tmp_path / "clip.pdf",
        {
            "Background": "10 10 300 200 re S",
            "Drill": circle_ops(50, 50, 30, paint="W* n") + " " + circle_ops(50, 50, 5),
        },
    )

    code = cli.main([str(panel), "--emit", f"json={tmp_path / 'out.json'}"])

    assert code in (0, 1), capsys.readouterr().out
    # the small circle is real geometry; the large one only ever marks a clip
    assert len(json.loads((tmp_path / "out.json").read_text())["holes"]) == 1


# ---------------------------------------------------------------------------
# row 9: every resolvable flag is judged before the file is opened
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--drill-standard", "whitworth"],
        ["--drill-sizes", "3.2,3.33"],
        ["--grid", "nan"],
        ["--grid-warn", "nan"],
        ["--case", "1590ZZ"],
        ["--case-face", "sideways"],
        ["--emit", "no-such-format=/tmp/x"],
    ],
    ids=lambda a: a[0],
)
def test_every_resolvable_flag_is_judged_before_the_input_file_is_opened(argv, capsys):
    """A bad flag is a usage error whatever the panel is, so it must be
    reported without the file ever being read -- otherwise an operator with a
    typo in a flag is told about the file instead. Every case below fails for
    the reason its own flag names, not merely with exit 3 for some other
    reason -- verified against ``cli.build_parser`` and each error message
    before this table was written; none of the seven messages names the
    panel path, so the second assertion holds for all of them."""
    assert cli.main(["/no/such/panel.ai", *argv]) == 3

    assert "/no/such/panel.ai" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# rows 2, 3, 4 and 10: the enclosure and clearance errors
# ---------------------------------------------------------------------------


def test_an_obstructed_hole_reaches_exit_two_and_withholds_everything(tmp_path, monkeypatch):
    """``hole-through-boss`` is driven to exit 2 by the hammond suite;
    ``hole-obstructed`` is a different rule with a different cause and had
    never reached a code."""
    fake = FakeCase(behind=((-40_000_000, 18_000_000, 1),))
    # Matches the fixture's identified 1590B footprint exactly, so the
    # cross-check stays silent and the obstruction is the only error: two
    # causes at once would not prove this row fails for its own reason.
    fake.footprint_nm = (Nanometre(112_400_000), Nanometre(60_500_000))
    monkeypatch.setattr(cli, "build_case_model", lambda args: fake)
    out = tmp_path / "panel.json"

    code = cli.main([str(FIXTURE), "--case", "1590B", "--emit", f"json={out}"])

    assert code == 2
    assert not out.exists()


def test_a_model_of_the_wrong_case_reaches_exit_two(tmp_path, monkeypatch):
    """The panel identifies one part and the supplied model is another. This
    gates an exit-2 error withholding every artefact, which is why
    ``_cross_check`` compares at exact nanometres."""
    # FakeCase's own footprint is the 1590BB catalogue size; the fixture
    # identifies as 1590B, so the two disagree without any override.
    monkeypatch.setattr(cli, "build_case_model", lambda args: FakeCase())
    out = tmp_path / "panel.json"

    code = cli.main([str(FIXTURE), "--case", "1590B", "--emit", f"json={out}"])

    assert code == 2
    assert not out.exists()


def test_a_declared_case_with_no_outline_to_check_it_against_reaches_exit_two(tmp_path):
    """``unverifiable-enclosure``. A declared case is always verified, so
    artwork with no reference outline cannot satisfy the declaration -- and
    silently proceeding would drill to an unchecked footprint.

    The reference layer must exist -- an absent layer is ``LayerNotFoundError``,
    a usage error, exit 3 -- but hold no non-circular path, so the source
    itself reports no outline rather than the layer lookup failing outright.
    """
    panel = build_pdf(
        tmp_path / "panel.pdf", {"Background": "", "Drill": circle_ops(50, 50, 3.5)}
    )

    assert cli.main([str(panel), "--case", "1590B"]) == 2


def test_the_case_model_is_parsed_once_however_many_consumers_want_it(tmp_path, monkeypatch):
    """The clearance stage and the STEP emitter both need it. Parsing twice
    is not only slow: two parses are two chances to disagree, and every
    artefact of one invocation must describe one geometry.

    The run below ends in ``wrong-case-model``, so the STEP emitter is
    resolved (and reads the shared model into its options) but never
    actually asked to cut -- which is enough to prove both consumers reach
    one object, without needing OCP to cut a fake model's absent geometry.
    """
    calls: list[Path] = []

    def counting_load(path, *, face, margin_nm, part):
        calls.append(path)
        return FakeCase()

    monkeypatch.setattr("stompdrill.cad.load_case_model", counting_load)

    code = cli.main([
        str(FIXTURE), "--case", "1590B",
        "--case-model", str(tmp_path / "fake.stp"),
        "--emit", f"step={tmp_path / 'panel.stp'}",
    ])

    assert code == 2
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# rows 5, 6 and 7: the emitters
# ---------------------------------------------------------------------------


def test_an_error_run_withholds_the_svg_like_every_other_artefact(tmp_path):
    """ADR-0001: any error withholds every requested artefact. Asserted for
    the PDF at ``test_cli.py:1617``; the SVG is a different emitter reached
    through a different branch, so it is a separate claim."""
    out = tmp_path / "panel.svg"

    # No --case, so tar.ai is ambiguous-enclosure, which is an error.
    code = cli.main([str(FIXTURE), "--emit", f"drawing-svg={out}"])

    assert code == 2
    assert not out.exists()


def test_the_step_emitter_refuses_data_that_was_never_routed():
    """Every other emitter's refusal is tested; this one's was not. A STEP
    file of unrouted data would cut real holes with no drill sequence behind
    them.

    Needs the kernel to construct a real (if empty) XCAF document -- without
    one, ``cut_shape`` fails on the document access that precedes the
    routing check, before the refusal under test is even reached -- but not
    a downloaded Hammond model, so this is ``importorskip`` only, matching
    how the kernel-only tests in ``test_cad_step.py`` are guarded.
    """
    pytest.importorskip("OCP", reason="needs stompdrill[step]")
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    from stompdrill.emitters.step import StepEmitter, StepOptions
    from stompmodel.errors import EmitterError

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    model = FakeCase()
    model.document = document
    unrouted = make_data(at(0, 0))

    with pytest.raises(EmitterError):
        StepEmitter(StepOptions(model=model)).emit(unrouted)


def test_a_panel_too_large_for_a2_is_drawn_on_a1(tmp_path):
    """ISO 5457 §4.1 fixes each size's orientation, so the only choice the
    emitter makes is which candidate. A1 sits between two sizes that are both
    chosen by existing tests, and was the one never reached. The same panel
    grown reaches A0 and shrunk falls back to A2, so this pins a boundary
    rather than one lucky value."""
    from stompdrill.emitters.drawing_pdf import DrawingPdfEmitter
    from stompmodel.model import ReferenceOutline

    def sheet_for(width_mm: float, height_mm: float) -> str:
        mm = 1_000_000
        reference = ReferenceOutline(
            width_nm=Nanometre(int(width_mm * mm)), height_nm=Nanometre(int(height_mm * mm))
        )
        data = make_data(reference=reference)
        return DrawingPdfEmitter().layout(data).sheet.name

    assert sheet_for(700, 450) == "A1"
    assert sheet_for(900, 600) == "A0"
    assert sheet_for(350, 225) == "A2"
