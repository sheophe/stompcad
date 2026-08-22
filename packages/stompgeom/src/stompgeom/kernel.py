"""Whether the geometry kernel is present, and how to say that it is not."""

from __future__ import annotations

from .errors import StompgeomError

__all__ = ["KernelUnavailable", "require_kernel"]

#: Names the distribution, never a consumer of this package. A hint that told
#: one tool's user to reinstall another tool's extra would be the defect
#: ADR-0009 removed from ``SourceInfo.producer``.
_INSTALL_HINT = (
    "the geometry kernel is missing: reinstall the cadquery-ocp dependency "
    "(uv sync --all-packages), or run the environment doctor"
)


class KernelUnavailable(StompgeomError):
    """The geometry kernel is a hard dependency and did not import."""


def require_kernel() -> None:
    """Raise a helpful error when OpenCASCADE is not importable."""
    try:
        import OCP  # noqa: F401
    except ImportError as failure:
        raise KernelUnavailable(_INSTALL_HINT) from failure
