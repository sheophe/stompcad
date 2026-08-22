"""The kernel guard: it names the dependency, and it names no consumer."""

from __future__ import annotations

import pytest

from stompgeom import kernel
from stompgeom.errors import StompgeomError
from stompmodel.errors import StompError


def test_kernel_unavailable_is_a_stompgeom_error() -> None:
    """Each package's errors stay identifiable beneath the shared base."""
    assert issubclass(kernel.KernelUnavailable, StompgeomError)


def test_stompgeom_error_is_a_stomp_error() -> None:
    """``except StompError`` must be a complete catch across the workspace."""
    assert issubclass(StompgeomError, StompError)


def test_require_kernel_passes_when_the_kernel_imports() -> None:
    """The kernel is a hard dependency, so the guard is quiet in a real env."""
    assert kernel.require_kernel() is None  # type: ignore[func-returns-value]


def test_require_kernel_raises_when_the_kernel_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure names the missing distribution."""
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "OCP":
            raise ImportError("no OCP here")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(kernel.KernelUnavailable, match="cadquery-ocp"):
        kernel.require_kernel()


def test_the_hint_names_no_consumer() -> None:
    """A shared component never bakes in the identity of a package above it.

    ADR-0009 made this rule for ``SourceInfo.producer``; an install hint that
    told a stompcollider user to reinstall stompdrill is the same defect.
    """
    from stompgeom.kernel import _INSTALL_HINT

    assert "stompdrill" not in _INSTALL_HINT
    assert "stompcollider" not in _INSTALL_HINT
    assert "stompcad" not in _INSTALL_HINT
