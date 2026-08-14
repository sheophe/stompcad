"""aidrill — extract drill data from Adobe Illustrator artwork and emit it."""

from .model import (
    Diagnostic, DrillData, Hole, Origin, RawHole, ReferenceOutline,
    Severity, SourceInfo, Units,
)
from .protocols import Emitter, Pipeline, Source, Stage
from .errors import (
    AidrillError, EmitterError, EmptyLayerError, LayerNotFoundError, SourceError,
)

__version__ = "1.0.0"
__all__ = [
    "Diagnostic", "DrillData", "Hole", "Origin", "RawHole", "ReferenceOutline",
    "Severity", "SourceInfo", "Units", "Emitter", "Pipeline", "Source", "Stage",
    "AidrillError", "EmitterError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
    "__version__",
]
