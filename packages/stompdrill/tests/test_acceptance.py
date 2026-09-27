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
from tests.conftest import FakeCase, at, build_pdf, circle_ops, make_data, registration_for
from tests.hammond import BB_PROBES, require_model

__all__: list[str] = []

FIXTURE = Path(__file__).parent / "fixtures" / "tar.ai"

#: The 1590BB's published top-view footprint (ADR-0007), matching the panel
#: builder in ``test_cli.py`` -- reproduced locally rather than imported
#: across test modules, which this plan has treated as coupling to avoid.
_BB_FOOTPRINT_MM = (119.5, 94.0)


def _pt_from_mm(mm: float) -> float:
    """Millimetres to PDF user-space points."""
    return mm * 72 / 25.4


def _panel_with_a_central_hole(tmp_path: Path) -> Path:
    """A hole in the clear middle of a 1590BB-sized floor: nothing rejects it."""
    x_mm, y_mm = BB_PROBES["clear"]
    width, height = (_pt_from_mm(size) for size in _BB_FOOTPRINT_MM)
    centre_x, centre_y = 10 + width / 2, 10 + height / 2
    return build_pdf(
        tmp_path / "clear.ai",
        {
            "Background": f"10 10 {width} {height} re f",
            "Drill": circle_ops(
                centre_x + _pt_from_mm(x_mm),
                centre_y + _pt_from_mm(y_mm),
                _pt_from_mm(3.0),
            ),
        },
    )


# ---------------------------------------------------------------------------
# rows 1 and 8: the source reads what the command line tells it to
# ---------------------------------------------------------------------------


def test_the_layer_flags_choose_which_layers_the_source_reads(tmp_path, capsys):
    """Both flags on one command line, against artwork whose layers are named
    nothing like the defaults. A default that happened to match would make a
    passing test say nothing.

    The synthetic panel matches no Hammond footprint, which is
    ``unknown-enclosure`` -- a warning, not a defect in the test -- so the
    run exits 1, never 0.
    """
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

    assert code == 1, capsys.readouterr().out
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
    second hole. The panel matches no Hammond footprint either
    (``unknown-enclosure``, a warning), so the run exits 1, never 0.
    """
    panel = build_pdf(
        tmp_path / "clip.pdf",
        {
            "Background": "10 10 300 200 re S",
            "Drill": circle_ops(50, 50, 30, paint="W* n") + " " + circle_ops(50, 50, 5),
        },
    )

    code = cli.main([str(panel), "--emit", f"json={tmp_path / 'out.json'}"])

    assert code == 1, capsys.readouterr().out
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


def _stub_ocp_case_model(*, document=None):
    """An ``OcpCaseModel`` standing in for a real parse, kernel-free geometry.

    ``StepEmitter`` now refuses any model that is not ``isinstance``
    ``OcpCaseModel`` at construction, so a bare ``FakeCase`` -- which
    satisfies only the clearance protocol -- can no longer stand in for one
    here. ``classify`` is overridden to the same plain bounds check
    ``FakeCase`` used, since no real kernel region is available; the
    footprint and play area mirror ``FakeCase``'s so a fixture built
    against it behaves the same way.
    """
    from stompdrill.cad import Rejection
    from stompdrill.cad.loader import OcpCaseModel

    class _Stub(OcpCaseModel):
        __slots__ = ()

        def classify(self, x_nm, y_nm, radius_nm):
            x0, y0, x1, y1 = self.play_area_nm
            if not (x0 <= x_nm - radius_nm and x_nm + radius_nm <= x1):
                return Rejection.OFF_FACE
            if not (y0 <= y_nm - radius_nm and y_nm + radius_nm <= y1):
                return Rejection.OFF_FACE
            return None

    return _Stub(
        part=FakeCase.part, face=FakeCase.face, model_name=FakeCase.model_name,
        footprint_nm=FakeCase.footprint_nm, plate_nm=FakeCase.plate_nm,
        play_area_nm=(
            Nanometre(-50_000_000), Nanometre(-40_000_000),
            Nanometre(50_000_000), Nanometre(40_000_000),
        ),
        frame=FakeCase.frame, margin_nm=Nanometre(1_000_000), axis=1,
        own_region=None, own_frame=FakeCase.frame,
        box_region=None, box_frame=None,
        drilled_position_mm=0.0, inner_position_mm=0.0,
        document=document, target_shape=None, document_timestamp="",
    )


def test_the_case_model_is_parsed_once_however_many_consumers_want_it(tmp_path, monkeypatch):
    """The clearance stage and the STEP emitter both need it. Parsing twice
    is not only slow: two parses are two chances to disagree, and every
    artefact of one invocation must describe one geometry.

    Ends in ``wrong-case-model``, so the STEP emitter is resolved (and reads
    the one object ``build_case_model`` produced into its options) but never
    asked to cut -- proving resolution alone, cheaply. The next test below
    completes a real run and checks the same claim past that point.
    """
    calls: list[Path] = []

    def counting_load(path, *, face, margin_nm, part):
        calls.append(path)
        return _stub_ocp_case_model()

    monkeypatch.setattr("stompdrill.cad.load_case_model", counting_load)

    code = cli.main([
        str(FIXTURE), "--case", "1590B",
        "--case-model", str(tmp_path / "fake.stp"),
        "--emit", f"step={tmp_path / 'panel.stp'}",
    ])

    assert code == 2
    assert len(calls) == 1


@pytest.mark.hammond
def test_the_case_model_is_parsed_once_across_a_completed_run(tmp_path, monkeypatch):
    """The fast test above ends at an error, so it never reaches an emitter.
    This one completes: clearance and the STEP emitter both consume the
    model, and it must still have been read from disk exactly once.
    """
    from stompdrill import cad

    real_load = cad.load_case_model
    calls: list[Path] = []

    def counting_load(path, *, face, margin_nm, part):
        calls.append(path)
        return real_load(path, face=face, margin_nm=margin_nm, part=part)

    monkeypatch.setattr("stompdrill.cad.load_case_model", counting_load)

    panel = _panel_with_a_central_hole(tmp_path)
    drl, stp = tmp_path / "o.drl", tmp_path / "o.stp"
    code = cli.main([
        str(panel), "--case", "1590BB", "--case-model", str(require_model("1590BB")),
        "--emit", f"excellon={drl}", "--emit", f"step={stp}",
    ])

    assert code == 0, "the run must complete for the emitter path to be reached at all"
    assert drl.exists() and stp.exists(), "both consumers must have actually run"
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
    routing check -- but not a downloaded Hammond model, so it carries no
    ``--hammond`` marker: the kernel is unconditional, needing no guard.
    """
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    from stompdrill.emitters.step import StepEmitter, StepOptions
    from stompmodel.errors import EmitterError

    app = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(document)

    model = _stub_ocp_case_model(document=document)
    unrouted = make_data(at(0, 0)).with_case(registration_for(model))

    with pytest.raises(EmitterError, match="no artifact can state a sequence"):
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
