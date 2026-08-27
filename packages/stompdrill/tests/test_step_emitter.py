"""The STEP emitter: registration and guards. Kernel-free by construction.

The kernel-backed cut and write tests live in ``test_step_cut.py``: this
file must import and run without OCP installed and without ``--hammond``,
since two of its tests exist specifically to prove that.
"""

from __future__ import annotations

import re

import pytest

from stompdrill.emitters import available, get_emitter
from stompmodel.errors import EmitterError


def test_step_is_always_in_the_registry():
    """The format list must not change shape with what is installed."""
    assert "step" in available()


def test_the_emitter_declares_its_media_type_and_extension():
    emitter_cls = get_emitter("step")

    assert emitter_cls.media_type == "model/step"
    assert emitter_cls.extension == ".stp"


def test_constructing_without_a_model_is_an_emitter_error():
    from stompdrill.emitters.step import StepEmitter, StepOptions

    with pytest.raises(EmitterError, match="--case-model"):
        StepEmitter(StepOptions(model=None))


def test_a_missing_kernel_surfaces_as_an_emitter_error(monkeypatch):
    """``StepEmitter.__init__`` wraps a ``KernelUnavailable`` failure as
    ``EmitterError(str(failure))``. Asserts against the guard's own
    ``_INSTALL_HINT`` rather than a hand-rolled copy, so this tracks the
    real message instead of drifting from it.
    """
    from stompdrill.emitters.step import StepEmitter, StepOptions
    from stompgeom import kernel as kernel_module
    from stompgeom.kernel import _INSTALL_HINT, KernelUnavailable
    from tests.test_clearance import FakeCase

    def absent() -> None:
        raise KernelUnavailable(_INSTALL_HINT)

    monkeypatch.setattr(kernel_module, "require_kernel", absent)

    with pytest.raises(EmitterError, match=re.escape(_INSTALL_HINT)):
        StepEmitter(StepOptions(model=FakeCase()))


def test_a_case_model_satisfying_only_the_clearance_protocol_is_refused_at_construction():
    """The cutting path is typed against ``OcpCaseModel``, not ``CaseModel``.

    A fake that satisfies every clearance member but carries no live kernel
    document must be refused here, at construction -- never by reaching
    ``cut_shape`` and dying mid-emit on an undeclared ``model.document``.
    """
    from stompdrill.cad import CaseModel
    from stompdrill.emitters.step import StepEmitter, StepOptions
    from tests.conftest import FakeCase

    fake = FakeCase()
    assert isinstance(fake, CaseModel)  # satisfies every declared clearance member

    with pytest.raises(EmitterError, match="kernel-backed case model"):
        StepEmitter(StepOptions(model=fake))


def test_the_emitter_module_imports_without_the_kernel():
    """emitters/__init__ imports every emitter; this one must not need OCP."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c",
         "import stompdrill.emitters, sys; print('OCP' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip() == "False"
