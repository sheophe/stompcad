"""The STEP emitter: registration and guards. Kernel-free by construction.

The kernel-backed cut and write tests live in ``test_step_cut.py``: this
file must import and run without OCP installed and without ``--hammond``,
since two of its tests exist specifically to prove that.
"""

from __future__ import annotations

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


def test_constructing_without_the_kernel_names_the_extra(monkeypatch):
    from stompdrill.cad import KernelUnavailable
    from stompdrill.emitters import step as step_module
    from stompdrill.emitters.step import StepEmitter, StepOptions
    from tests.test_clearance import FakeCase

    def absent() -> None:
        raise KernelUnavailable("the STEP features need the geometry kernel: "
                                "pip install 'stompdrill[step]'")

    monkeypatch.setattr(step_module, "require_kernel", absent)

    with pytest.raises(EmitterError, match=r"stompdrill\[step\]"):
        StepEmitter(StepOptions(model=FakeCase()))


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


def test_reslot_colours_leaves_a_colourless_payload_untouched():
    """Pure bytes-in bytes-out: no kernel needed, and no OCP model to fake.

    Stands in for "a genuinely colourless enclosure": no cached Hammond
    fixture is colourless, so this reasons the case through directly rather
    than building one — a payload with zero ``STYLED_ITEM`` chains and an
    ``expected`` of zero is exactly what a colourless document would count
    to, and must round trip rather than raise.
    """
    from stompdrill.emitters.step import _reslot_colours

    payload = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1 = SOMETHING();\nENDSEC;\n"

    assert _reslot_colours(payload, expected=0) == payload


def test_reslot_colours_raises_when_the_chain_count_does_not_match():
    """The guard the fix round added: a silent zero-chain match is a bug.

    Simulates ``_COLOUR_CHAIN`` drifting out of sync with what the writer
    actually produced (an OpenCASCADE upgrade reshaping the chain, a typo
    in the pattern) without needing OCP: a payload carrying no matchable
    chain, compared against a document that (per the source) assigns one
    colour, must raise rather than silently pass the mismatch through.
    """
    from stompdrill.emitters.step import _reslot_colours
    from stompmodel.errors import EmitterError

    payload = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1 = SOMETHING();\nENDSEC;\n"

    with pytest.raises(EmitterError, match=r"assigns 1 colour.*0 STYLED_ITEM"):
        _reslot_colours(payload, expected=1)
