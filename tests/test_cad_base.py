"""The kernel-free case-model contract."""

from __future__ import annotations

from aidrill.cad import CaseModel, Frame, KernelUnavailable, Rejection
from aidrill.errors import AidrillError
from aidrill.units import Nanometre


class Stub:
    """Minimal structural implementation, to prove the protocol is satisfiable."""

    part = "1590BB"
    face = "box"
    footprint_nm = (Nanometre(119_500_000), Nanometre(94_000_000))
    plate_nm = Nanometre(2_250_000)
    play_area_nm = (
        Nanometre(-50_000_000), Nanometre(-40_000_000),
        Nanometre(50_000_000), Nanometre(40_000_000),
    )
    frame = Frame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-30_000_000)),
        u=(1.0, 0.0, 0.0), v=(0.0, -1.0, 0.0), w=(0.0, 0.0, -1.0),
    )

    def classify(self, x_nm, y_nm, radius_nm):
        return None


def test_every_rejection_value_is_the_diagnostic_code_it_raises():
    assert Rejection.OFF_FACE.value == "hole-off-face"
    assert Rejection.THROUGH_BOSS.value == "hole-through-boss"
    assert Rejection.OBSTRUCTED.value == "hole-obstructed"


def test_rejection_codes_are_distinct():
    assert len({member.value for member in Rejection}) == len(Rejection)


def test_a_structural_implementation_satisfies_the_protocol():
    assert isinstance(Stub(), CaseModel)


def test_an_object_missing_classify_does_not_satisfy_the_protocol():
    class Incomplete:
        part = "x"
        face = "box"

    assert not isinstance(Incomplete(), CaseModel)


def test_the_frame_flattens_to_stagerun_safe_parameters():
    frame = Stub.frame
    keys = dict(frame.as_parameters())

    assert keys["frame_origin_nm"] == (0, 0, -30_000_000)
    assert keys["frame_u"] == (1.0, 0.0, 0.0)
    assert keys["frame_v"] == (0.0, -1.0, 0.0)
    assert keys["frame_w"] == (0.0, 0.0, -1.0)


def test_kernel_unavailable_is_an_aidrill_error():
    assert issubclass(KernelUnavailable, AidrillError)


def test_importing_aidrill_does_not_import_the_kernel():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import aidrill, sys; print('OCP' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False"
