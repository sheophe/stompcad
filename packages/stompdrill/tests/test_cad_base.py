"""The kernel-free case-model contract."""

from __future__ import annotations

import pytest

from stompdrill.cad import CaseModel, Rejection
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace
from stompmodel.units import Nanometre


class Stub:
    """Minimal structural implementation, to prove the protocol is satisfiable."""

    part = "1590BB"
    face = CaseFace.BOX
    model_name = "1590BB.stp"
    footprint_nm = (Nanometre(119_500_000), Nanometre(94_000_000))
    plate_nm = Nanometre(2_250_000)
    play_area_nm = (
        Nanometre(-50_000_000), Nanometre(-40_000_000),
        Nanometre(50_000_000), Nanometre(40_000_000),
    )
    margin_nm = Nanometre(1_000_000)
    frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-30_000_000)),
            u=(1.0, 0.0, 0.0), v=(0.0, -1.0, 0.0), w=(0.0, 0.0, -1.0),
        )
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
        face = CaseFace.BOX
        footprint_nm = (Nanometre(119_500_000), Nanometre(94_000_000))
        plate_nm = Nanometre(2_250_000)
        play_area_nm = (
            Nanometre(-50_000_000), Nanometre(-40_000_000),
            Nanometre(50_000_000), Nanometre(40_000_000),
        )
        margin_nm = Nanometre(1_000_000)
        frame = FaceFrame(
            basis=CoordinateFrame(
                origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-30_000_000)),
                u=(1.0, 0.0, 0.0), v=(0.0, -1.0, 0.0), w=(0.0, 0.0, -1.0),
            )
        )

    assert not isinstance(Incomplete(), CaseModel)


def test_every_case_face_has_a_step_keyword():
    """The lookup is total over the published vocabulary: nothing missing."""
    from stompdrill.cad.base import _STEP_KEYWORD

    assert set(_STEP_KEYWORD) == set(CaseFace)


def test_step_keyword_names_the_box_and_lid_products():
    from stompdrill.cad import step_keyword

    assert step_keyword(CaseFace.BOX) == "BOX"
    assert step_keyword(CaseFace.LID) == "LID"


def test_step_keyword_raises_rather_than_defaulting_for_anything_outside_the_vocabulary():
    """No ``.get(face, "LID")`` fallback: a face the enum does not hold is a
    lookup failure, never silently answered -- this is what closes the
    finding that ``cut_shape``'s old ternary was total where the selector's
    mapping was partial. A closed two-member enum cannot itself be handed a
    third member in a test, so this is proved on the lookup's own mechanism
    (plain ``dict`` indexing, no default) rather than by manufacturing one.
    """
    from stompdrill.cad import step_keyword

    with pytest.raises(KeyError):
        step_keyword("top")


def test_importing_stompdrill_does_not_import_the_kernel():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import stompdrill, sys; print('OCP' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False"


def test_importing_stompdrill_cli_does_not_import_the_kernel():
    """``import stompdrill`` is covered above; the CLI module has its own import
    graph (``.cad``, ``.emitters``, ``.pipeline``) and a module-level OCP
    import placed directly in ``cli.py`` would not be caught by that test
    alone."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import stompdrill.cli, sys; print('OCP' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False"
