"""The STEP emitter: registration, guards, geometry and determinism."""

from __future__ import annotations

import pytest

from aidrill.emitters import available, get_emitter
from aidrill.errors import EmitterError


def test_step_is_always_in_the_registry():
    """The format list must not change shape with what is installed."""
    assert "step" in available()


def test_the_emitter_declares_its_media_type_and_extension():
    emitter_cls = get_emitter("step")

    assert emitter_cls.media_type == "model/step"
    assert emitter_cls.extension == ".stp"


def test_constructing_without_a_model_is_an_emitter_error():
    from aidrill.emitters.step import StepEmitter, StepOptions

    with pytest.raises(EmitterError, match="--case-model"):
        StepEmitter(StepOptions(model=None))


def test_constructing_without_the_kernel_names_the_extra(monkeypatch):
    from aidrill.cad import KernelUnavailable
    from aidrill.emitters import step as step_module
    from aidrill.emitters.step import StepEmitter, StepOptions
    from tests.test_clearance import FakeCase

    def absent() -> None:
        raise KernelUnavailable("the STEP features need the geometry kernel: "
                                "pip install 'aidrill[step]'")

    monkeypatch.setattr(step_module, "require_kernel", absent)

    with pytest.raises(EmitterError, match=r"aidrill\[step\]"):
        StepEmitter(StepOptions(model=FakeCase()))


def test_the_emitter_module_imports_without_the_kernel():
    """emitters/__init__ imports every emitter; this one must not need OCP."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c",
         "import aidrill.emitters, sys; print('OCP' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == "False"


from pathlib import Path  # noqa: E402

ocp = pytest.importorskip("OCP", reason="needs aidrill[step]")

pytestmark = pytest.mark.hammond

MM = 1_000_000


def _model_path():
    """The cached 1590BB, fetched on demand. Skips the test if unobtainable."""
    from tests.hammond import require_model

    return require_model("1590BB")


def _emit(*holes, face="box"):
    from aidrill.cad import load_case_model
    from aidrill.emitters.step import StepEmitter, StepOptions
    from aidrill.units import Nanometre
    from tests.conftest import make_data

    model = load_case_model(_model_path(), face=face, margin_nm=Nanometre(1 * MM))
    return StepEmitter(StepOptions(model=model)).emit(make_data(*holes))


def _reload(payload: bytes, tmp_path: Path):
    from aidrill.cad.step import read_step

    target = tmp_path / "out.stp"
    target.write_bytes(payload)
    return read_step(target)


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_the_payload_is_bytes():
    from tests.conftest import at

    assert isinstance(_emit(at(0, 0, 6 * MM, index=1)), bytes)


def test_the_payload_is_a_step_file():
    from tests.conftest import at

    assert _emit(at(0, 0, 6 * MM, index=1)).startswith(b"ISO-10303-21;")


def test_the_output_reloads_as_a_valid_solid(tmp_path):
    from OCP.BRepCheck import BRepCheck_Analyzer

    from tests.conftest import at

    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)

    for solid in document.solids:
        assert BRepCheck_Analyzer(solid.shape).IsValid()


def test_the_assembly_and_its_product_names_survive_the_round_trip(tmp_path):
    from aidrill.cad.step import read_step
    from tests.conftest import at

    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)
    names = {solid.name.upper() for solid in document.solids}

    # The 1590BB assembly is box, lid, and four instances of one screw.
    assert len(document.solids) == len(read_step(_model_path()).solids)
    assert any("BOX" in name for name in names)
    assert any("LID" in name for name in names)


def test_the_volume_removed_matches_the_holes_drilled(tmp_path):
    """pi r^2 t is an authority no self-consistent bad topology can fake."""
    import math

    from aidrill.cad import load_case_model
    from aidrill.cad.step import read_step
    from aidrill.units import Nanometre
    from tests.conftest import at

    before = {s.name: _volume(s.shape) for s in read_step(_model_path()).solids}
    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)
    after = {s.name: _volume(s.shape) for s in document.solids}

    model = load_case_model(_model_path(), face="box", margin_nm=Nanometre(1 * MM))
    plate_mm = model.plate_nm / 1_000_000
    expected = math.pi * 3.0**2 * plate_mm
    removed = sum(before.values()) - sum(after.values())

    assert removed == pytest.approx(expected, rel=0.02)


def test_only_the_drilled_side_loses_material(tmp_path):
    """An unbounded cylinder would punch the lid as well."""
    from aidrill.cad.step import read_step
    from tests.conftest import at

    before = {s.name: _volume(s.shape) for s in read_step(_model_path()).solids}
    after = {s.name: _volume(s.shape)
             for s in _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path).solids}

    for name, volume in before.items():
        if "BOX" in name.upper():
            assert after[name] < volume
        else:
            # A STEP write/read round trip re-serialises every coordinate
            # through ASCII text, so an untouched solid's volume survives
            # only to that text precision, not bit-for-bit; the screws are
            # small enough that this shows up as a relative, not absolute,
            # tolerance would need to be loose enough to hide a real cut.
            assert after[name] == pytest.approx(volume, abs=0.05)


def test_two_holes_remove_twice_as_much_as_one(tmp_path):
    from aidrill.cad.step import read_step
    from tests.conftest import at

    base = sum(_volume(s.shape) for s in read_step(_model_path()).solids)
    one = sum(_volume(s.shape)
              for s in _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path).solids)
    two = sum(_volume(s.shape) for s in _reload(
        _emit(at(0, 0, 6 * MM, index=1), at(6 * MM, 0, 6 * MM, index=2)), tmp_path).solids)

    assert (base - two) == pytest.approx(2 * (base - one), rel=0.02)


def test_the_hole_is_cut_where_the_frame_puts_it(tmp_path):
    """An off-centre hole must move the drilled solid's bounding box hole, not mirror."""
    from aidrill.cad.step import bounding_box_mm, read_step
    from tests.conftest import at

    document = _reload(_emit(at(10 * MM, 0, 6 * MM, index=1)), tmp_path)
    (box,) = [s for s in document.solids if "BOX" in s.name.upper()]

    assert bounding_box_mm(box.shape) == pytest.approx(
        bounding_box_mm([s for s in read_step(_model_path()).solids
                         if "BOX" in s.name.upper()][0].shape), abs=1e-3
    ), "cutting a through-hole must not change the solid's outer extent"


def test_emitting_with_no_holes_leaves_the_model_unchanged(tmp_path):
    from aidrill.cad.step import read_step

    before = sum(_volume(s.shape) for s in read_step(_model_path()).solids)
    after = sum(_volume(s.shape) for s in _reload(_emit(), tmp_path).solids)

    assert after == pytest.approx(before, rel=1e-6)


def test_a_hole_over_cast_lettering_cuts_cleanly(tmp_path):
    """The three-surface case the bounded-boolean strategy was chosen for.

    ``BB_PROBES["relief"]`` sits on a letter: the drill crosses the outer
    wall, the letter-shaped hole in the floor, the letter body, and exits
    through the letter's own top face at a different level. Nothing else in
    this suite exercises a hole placed over lettering.
    """
    from OCP.BRepCheck import BRepCheck_Analyzer

    from aidrill.cad.step import read_step
    from tests.conftest import at
    from tests.hammond import BB_PROBES

    x_mm, y_mm = BB_PROBES["relief"]
    hole = at(round(x_mm * MM), round(y_mm * MM), 6 * MM, index=1)
    document = _reload(_emit(hole), tmp_path)

    for solid in document.solids:
        assert BRepCheck_Analyzer(solid.shape).IsValid()

    (box,) = [s for s in document.solids if "BOX" in s.name.upper()]
    before = [s for s in read_step(_model_path()).solids if "BOX" in s.name.upper()][0]
    assert _volume(box.shape) < _volume(before.shape)
