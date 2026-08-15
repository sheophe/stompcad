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

__all__ = [
    "Diagnostic", "DrillData", "EnclosureMatch", "Hole", "Origin", "ParameterValue", "RawHole", "RawOutline",
    "ReferenceOutline", "Severity", "SourceInfo", "StageRun", "Units",
    "Enclosure", "HAMMOND_1590", "footprints",
    "Emitter", "Pipeline", "Source", "Stage",
    "AidrillError", "EmitterError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
]
