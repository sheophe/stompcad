"""Emitter construction from output settings, without argument parsing.

Moved out of ``cli.py`` so a library caller can build an emitter without
importing an argparse module. See ADR-0009 and CLAUDE.md's purpose note.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_args, get_type_hints

from stompmodel.model import DrillData
from stompmodel.protocols import Emitter

from ..cad import OcpCaseModel
from ..errors import UsageError
from . import DrawingOptions, ExcellonOptions, JsonOptions, PdfDrawingOptions, StepOptions, get_emitter
from .drawing.build import SheetText

__all__ = ["OutputSettings", "make_emitter"]


@dataclass(frozen=True, slots=True)
class OutputSettings:
    """Command-line values from which emitter-specific options are built."""

    title: str = ""
    case_model: OcpCaseModel | None = None


#: Keyed by options **class**, never by format name. An emitter whose options
#: type is not listed — including one this file has never seen — is constructed
#: with its own defaults.
_OPTION_BUILDERS: dict[type, Callable[[OutputSettings], Any]] = {
    ExcellonOptions: lambda s: ExcellonOptions(title=s.title),
    # Drawing options contain presentation values only; grid pitch and panel
    # dimensions come from canonical processing results. Both sheets' other
    # ISO 7200 fields have no command-line source yet; a caller using the
    # library supplies them directly, through ``SheetText``.
    DrawingOptions: lambda s: DrawingOptions(text=SheetText(title=s.title)),
    PdfDrawingOptions: lambda s: PdfDrawingOptions(text=SheetText(title=s.title)),
    JsonOptions: lambda s: JsonOptions(),
    # The model is resolved before the input file is opened; the emitter only
    # cuts what quantisation and the pipeline already agreed on.
    StepOptions: lambda s: StepOptions(model=s.case_model, title=s.title),
}


def _options_for(emitter_cls: type, settings: OutputSettings) -> Any | None:
    """Build the options object ``emitter_cls`` declares, or ``None``."""
    # Narrow, and deliberately so: these three are what an unresolvable
    # annotation actually raises. A bare ``except Exception`` here would also
    # swallow a genuine fault inside a third-party emitter and hand it its
    # defaults, so the emitter would write a file with the wrong options rather
    # than the run failing.
    # ``getattr_static`` rather than ``emitter_cls.__init__``: the attribute is
    # wanted as the function this class declares, not as whatever the descriptor
    # protocol would bind, and a type checker cannot know the plain access is
    # safe on an arbitrary ``type``.
    try:
        hints = get_type_hints(inspect.getattr_static(emitter_cls, "__init__"))
    except (NameError, TypeError, AttributeError):  # pragma: no cover - unresolvable hints
        return None
    for name, hint in hints.items():
        if name == "return":
            continue
        for candidate in get_args(hint) or (hint,):
            builder = _OPTION_BUILDERS.get(candidate)
            if builder is not None:
                return builder(settings)
    return None


def make_emitter(name: str, settings: OutputSettings) -> Emitter[DrillData]:
    """Resolve ``name`` through the registry and give it its options.

    A registered emitter is a conforming extension by definition; one whose
    constructor needs more than this CLI can supply is a usage failure, not an
    unexpected fault, so only the construction call itself is guarded — an
    emitter's later ``emit`` step keeps its own tracebacks.
    """
    emitter_cls = get_emitter(name)  # raises EmitterError for an unknown format
    options = _options_for(emitter_cls, settings)
    try:
        return emitter_cls() if options is None else emitter_cls(options)
    except TypeError as failure:
        raise UsageError(f"--emit {name}=...: cannot construct this emitter: {failure}") from failure
