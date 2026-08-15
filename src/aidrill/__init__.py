"""aidrill — extract drill data from Adobe Illustrator artwork and emit it."""

from .model import (
    Diagnostic, DrillData, EnclosureMatch, Hole, Origin, ParameterValue, RawHole, RawOutline,
    ReferenceOutline, Severity, SourceInfo, StageRun, Units,
)
from .enclosures import Enclosure, HAMMOND_1590, footprints
from .protocols import Emitter, Pipeline, Source, Stage
from .errors import (
    AidrillError, EmitterError, EmptyLayerError, LayerNotFoundError, SourceError,
)

# Tracks docs/SPEC.md, and the major is a promise about severity: in 1.0
# ``unknown-diameter`` was a WARNING and the hole kept its measured diameter,
# where in 2.0 it is an ERROR, the hole is dropped, and the run writes no
# artifacts at all. A consumer that built its handling from the 1.0 spec would
# treat a *dropped hole* as something merely worth logging, so this string and
# the one in ``pyproject.toml`` are the only way it can tell which contract it
# has. Keep the two in step.
__version__ = "2.0.0"
__all__ = [
    "Diagnostic", "DrillData", "EnclosureMatch", "Hole", "Origin", "ParameterValue", "RawHole", "RawOutline",
    "ReferenceOutline", "Severity", "SourceInfo", "StageRun", "Units",
    "Enclosure", "HAMMOND_1590", "footprints",
    "Emitter", "Pipeline", "Source", "Stage",
    "AidrillError", "EmitterError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
    "__version__",
]
