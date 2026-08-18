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
