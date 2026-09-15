"""The workbench: eight places, one key model, and a run that happens inside it.

Spec decision 1. On a terminal ``stompcad`` opens full screen and the user
stays in it; a run is an event in the app rather than the app's exit. The
split inside this package is deliberate: ``session`` holds every rule with
no Textual in it, so the rules can be driven headless, and the modules that
import Textual draw that state and feed keys back into it.
"""

from __future__ import annotations

from .keys import Place
from .session import Session

__all__ = ["Place", "Session"]
