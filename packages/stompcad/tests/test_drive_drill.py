"""The drill half of the driver: composed in memory, matching stompdrill's own CLI.

Spec decision 7: stompcad calls each phase separately rather than through one
entry point per tool. This test is the byte-identity acceptance criterion
that promise rests on -- the orchestrator must add nothing and change
nothing an artefact's bytes could show, in every format stompdrill emits.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from stompcad import cases
from stompcad.drive import Driver, RunOptions, _model_part
from stompcad.plan import DRILL_AND_DOCK
from stompcad.present import NoTerminal, PlainWriter
from stompcad.settings import Settings
from stompdrill import cli as stompdrill_cli
from stompdrill.emitters import available
from stompdrill.pipeline import DEFAULT_STANDARD
from stompdrill.sources.ai_pdf import DEFAULT_FORM_DEPTH
from stompmodel.diagnostics import Severity
from stompmodel.model import CaseFace, DrillData, EnclosureMatch
from stompmodel.progress import track
from stompmodel.units import nm_from_mm
from tests.conftest import PANEL_REFERENCE, TAR_AI, NullSink, case_model

__all__: list[str] = []


def _tar_options(tmp_path: Path, **overrides: object) -> RunOptions:
    """The tar fixture's options, with whatever one test varies."""
    base = RunOptions(
        panel=TAR_AI,
        drill_layer="Drill",
        reference_layer="Background",
        form_depth=DEFAULT_FORM_DEPTH,
        case="1590B",
        case_model=None,
        case_face=CaseFace.BOX,
        case_margin_mm=1.0,
        grid_mm=0.25,
        grid_warn_mm=None,
        drill_standard=DEFAULT_STANDARD,
        drill_sizes=None,
        no_drill_sizes=None,
        title="",
        boards=(),
        panel_reference=PANEL_REFERENCE,
        match_tolerance_mm=None,
        seat_pitch_max_mm=2.0,
        seat_pitch_min_mm=0.05,
        targets=(("excellon", tmp_path / "tar-case.drl"),),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _drill(options: RunOptions, acquire: Callable[[str], Path]) -> DrillData:
    """One drill half, with the model acquired however the test says."""
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options, None, acquire)
    with track(NullSink()) as scope:
        return driver.run_drill(scope)


def _refuse(part: str) -> Path:
    """An acquisition that must not happen, named by what asked for it."""
    raise AssertionError(f"this run acquired a model for {part}")


def _model() -> Path:
    """The cached enclosure model this machine holds, or nothing to test with."""
    model = case_model()
    if model is None:
        pytest.skip("no cached 1590B model")
    return model


def _identified(candidates: tuple[str, ...] | None, selected: str | None) -> DrillData:
    """Drill data that identified these parts, or identified nothing at all."""
    if candidates is None:
        return DrillData()
    return DrillData(
        enclosure=EnclosureMatch(
            family="1590",
            length_nm=nm_from_mm(112.4),
            width_nm=nm_from_mm(60.5),
            candidates=candidates,
            selected_part=selected,
        )
    )


def test_the_drill_half_matches_stompdrill_byte_for_byte(tmp_path: Path) -> None:
    """The orchestrator adds nothing and changes nothing."""
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])

    _drill(_tar_options(tmp_path, targets=(("excellon", mine),)), _refuse)

    assert mine.read_bytes() == theirs.read_bytes()


def test_the_drill_half_matches_stompdrill_under_settings_defaults(tmp_path: Path) -> None:
    """``RunOptions.of`` must route every ``Settings`` default to the field
    stompdrill's own parser fills it from -- a field sent to the wrong place
    would not show in the test above, which states the defaults by hand.
    """
    mine, theirs = tmp_path / "mine.drl", tmp_path / "theirs.drl"

    stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--emit", f"excellon={theirs}",
    ])

    options = replace(
        RunOptions.of(Settings.of_defaults(TAR_AI)),
        case="1590B",
        targets=(("excellon", mine),),
    )
    _drill(options, _refuse)

    assert mine.read_bytes() == theirs.read_bytes()


@pytest.mark.hammond
def test_the_drill_half_matches_stompdrill_for_every_emitted_format(tmp_path: Path) -> None:
    """Every registered format, not just the one the acceptance test found easy.

    ``step`` is the only format that reads ``OutputSettings.case_model``, so
    driving every format with a real case model is what exercises the
    ``--case-model`` path through ``run_drill`` -- nothing else in this suite
    reaches it. A wrong ``OutputSettings`` field would show in exactly one
    format's bytes and nowhere else, which is why every format is compared.
    """
    model = _model()

    formats = available()
    assert set(formats) == {"drawing-pdf", "drawing-svg", "excellon", "json", "step"}

    theirs_args = [str(TAR_AI), "--case", "1590B", "--case-model", str(model)]
    theirs_paths: dict[str, Path] = {}
    for name in formats:
        path = tmp_path / f"theirs-{name}"
        theirs_paths[name] = path
        theirs_args += ["--emit", f"{name}={path}"]
    code = stompdrill_cli.main(theirs_args)
    assert code in (0, 1), f"the fixture run failed with exit {code}"

    mine_paths = {name: tmp_path / f"mine-{name}" for name in formats}
    _drill(
        _tar_options(
            tmp_path,
            case_model=model,
            targets=tuple((name, mine_paths[name]) for name in formats),
        ),
        _refuse,
    )

    for name in formats:
        mine_bytes = mine_paths[name].read_bytes()
        theirs_bytes = theirs_paths[name].read_bytes()
        assert mine_bytes == theirs_bytes, f"{name}: bytes differ"


def test_a_drill_only_run_acquires_nothing(tmp_path: Path) -> None:
    """The rule that keeps today's runs as they are: no boards, no drilled
    enclosure asked for, so no model and no clearance check."""
    _drill(_tar_options(tmp_path), _refuse)


@pytest.mark.hammond
def test_a_drilled_enclosure_target_acquires_the_model(tmp_path: Path) -> None:
    asked: list[str] = []

    def acquire(part: str) -> Path:
        asked.append(part)
        return _model()

    _drill(
        _tar_options(tmp_path, targets=(("step", tmp_path / "tar-case.stp"),)), acquire
    )
    assert asked == ["1590B"]


@pytest.mark.hammond
def test_a_supplied_model_bypasses_the_cache(tmp_path: Path) -> None:
    """The command line's escape hatch: this path, exactly as given."""
    _drill(
        _tar_options(
            tmp_path,
            case_model=_model(),
            targets=(("step", tmp_path / "tar-case.stp"),),
        ),
        _refuse,
    )


@pytest.mark.hammond
def test_a_supplied_model_is_loaded_with_no_drilled_enclosure_asked_for(tmp_path: Path) -> None:
    """A path the operator named costs no download, so needing one does not gate
    it: stompdrill given that flag checks clearance, and this must too. ``json``
    records the case registration and every stage run, so a clearance check this
    run skipped would show in the bytes."""
    model = _model()
    mine, theirs = tmp_path / "mine.json", tmp_path / "theirs.json"

    stompdrill_cli.main([
        str(TAR_AI), "--case", "1590B", "--case-model", str(model),
        "--emit", f"json={theirs}",
    ])

    _drill(_tar_options(tmp_path, case_model=model, targets=(("json", mine),)), _refuse)

    assert mine.read_bytes() == theirs.read_bytes()


@pytest.mark.hammond
def test_a_supplied_model_is_loaded_under_the_part_stompdrill_loads_it_under(
    tmp_path: Path,
) -> None:
    """A cache file is keyed by the part that fetched it, so identification is
    that file's identity; a path the operator supplied was named by nothing
    here, so it keeps stompdrill's rule -- the declaration, or the STEP product
    name where there is none. The 1590B model under a tied part's filename is
    what tells the two apart: the filename settles the tie, and ``json`` records
    the registration, so a model loaded under the identified part shows in the
    bytes and in what ``wrong-case-model`` would name.
    """
    supplied = tmp_path / "1590B2.stp"
    supplied.write_bytes(_model().read_bytes())
    mine, theirs = tmp_path / "mine.json", tmp_path / "theirs.json"

    stompdrill_cli.main([
        str(TAR_AI), "--case-model", str(supplied), "--emit", f"json={theirs}",
    ])

    _drill(
        _tar_options(tmp_path, case=None, case_model=supplied, targets=(("json", mine),)),
        _refuse,
    )

    assert mine.read_bytes() == theirs.read_bytes()


@pytest.mark.hammond
def test_a_retry_that_identifies_nothing_holds_no_model(tmp_path: Path) -> None:
    """Every attempt opens its own model. One left over from the attempt before
    would name a file for a part this panel has just been declared not to be."""
    options = _tar_options(
        tmp_path, case_model=_model(), targets=(("step", tmp_path / "tar-case.stp"),)
    )
    driver = Driver(DRILL_AND_DOCK, PlainWriter(io.StringIO()), options, None, _refuse)

    with track(NullSink()) as scope:
        driver.run_drill(scope)
        assert driver._case_model is not None, "the control: the first attempt opened one"
        again = driver.retry("quantise", replace(options, case="1590BB"), scope)

    assert again.worst_severity is Severity.ERROR, "the control: this attempt identified nothing"
    assert driver._case_model is None


def test_a_model_that_cannot_be_had_stops_the_run_and_names_the_part(tmp_path: Path) -> None:
    """Decision 7: an error before any artefact is written, saying why."""

    def fail(part: str) -> Path:
        raise cases.ModelUnavailable(f"https://example.invalid/{part}.zip could not be fetched")

    target = tmp_path / "tar-case.stp"
    data = _drill(_tar_options(tmp_path, targets=(("step", target),)), fail)
    reported = next(f for f in data.diagnostics if f.code == "case-model-unavailable")
    assert reported.severity is Severity.ERROR
    assert "1590B" in reported.message
    assert not target.exists()


def test_a_model_that_will_not_load_is_reported_the_same_way(tmp_path: Path) -> None:
    """A file can arrive whole and still be no enclosure: acquiring it is not
    evidence that it loads."""
    rubbish = tmp_path / "1590B.stp"
    rubbish.write_text("this is not a STEP file\n")
    target = tmp_path / "tar-case.stp"
    data = _drill(
        _tar_options(tmp_path, targets=(("step", target),)), lambda part: rubbish
    )
    assert any(f.code == "case-model-unavailable" for f in data.diagnostics)
    assert not target.exists()


def test_an_unanswered_tie_asks_before_it_acquires_anything(tmp_path: Path) -> None:
    """A pipe cannot answer a tie, so the run ends there -- and nothing is
    fetched for an enclosure nobody has chosen yet."""
    with pytest.raises(NoTerminal):
        _drill(
            _tar_options(
                tmp_path, case=None, targets=(("step", tmp_path / "tar-case.stp"),)
            ),
            _refuse,
        )


def test_a_declaration_names_the_model() -> None:
    assert _model_part("1590BB", _identified(("1590B",), selected=None)) == "1590BB"


def test_one_identified_part_names_the_model() -> None:
    """The case this feature adds: nobody declared it, the outline decided."""
    assert _model_part(None, _identified(("1590B",), selected=None)) == "1590B"


def test_a_selected_part_names_the_model() -> None:
    assert _model_part(None, _identified(("1590B", "1590BS"), selected="1590BS")) == "1590BS"


def test_a_footprint_several_parts_share_names_no_model() -> None:
    """Choosing the first would fetch an enclosure nobody asked for."""
    assert _model_part(None, _identified(("1590B", "1590BS"), selected=None)) is None


def test_a_panel_nothing_identified_names_no_model() -> None:
    assert _model_part(None, _identified(None, selected=None)) is None
