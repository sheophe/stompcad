"""Cut the accepted holes into a supplied enclosure model and write STEP.

Presentation only in the sense that matters: every hole, its position and its
diameter were decided before this module ran. The kernel is imported inside
the methods, so importing the emitter registry stays free of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from ..cad.base import KernelUnavailable
from ..errors import EmitterError
from ..model import DrillData
from .base import register_emitter

__all__ = ["StepOptions", "StepEmitter"]


def require_kernel() -> None:
    """Indirection so a test can simulate an absent kernel."""
    from ..cad.step import require_kernel as check

    check()


@dataclass(frozen=True, slots=True)
class StepOptions:
    """The supplied case model to cut, and the title recorded in the header."""

    model: Any | None = None
    title: str = ""


@register_emitter
class StepEmitter:
    """Emit the supplied enclosure with this panel's holes drilled through it."""

    name: ClassVar[str] = "step"
    media_type: ClassVar[str] = "model/step"
    extension: ClassVar[str] = ".stp"

    def __init__(self, options: StepOptions | None = None) -> None:
        self.options = options if options is not None else StepOptions()
        if self.options.model is None:
            raise EmitterError("the step emitter needs a case model; pass --case-model PATH")
        try:
            require_kernel()
        except KernelUnavailable as failure:
            raise EmitterError(str(failure)) from failure

    def emit(self, data: DrillData) -> bytes:
        raise NotImplementedError("Task 12 implements the cut")
