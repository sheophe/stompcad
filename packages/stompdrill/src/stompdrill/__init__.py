"""Extract, quantise, process, and emit drill data from Illustrator artwork.

The package root exposes the public data model, protocols, concrete source,
quantisation entry point, standard stages, and enclosure reference data.
"""

from stompmodel.errors import EmitterError

from .model import (
    Diagnostic, DrillData, EnclosureMatch, Hole, Origin, ParameterValue, RawDrillData, RawHole,
    RawOutline, ReferenceOutline, Severity, SourceInfo, StageRun,
)
from .protocols import Emitter, Pipeline, Source, Stage
from .sources import AiPdfSource
from .quantise import quantise
from .pipeline import (
    SnapPositions, SnapDiametersToDrillTable, Deduplicate, IdentifyHammondFootprint,
    CheckReferenceSize, ReviewGridTies, RouteHoles, DrillStandard, DRILL_STANDARDS,
    DEFAULT_STANDARD, CheckCaseClearance,
)
from .enclosures import Enclosure, HAMMOND_1590, footprints
from .cad import CaseModel, Frame, Rejection, load_case_model
from .errors import StompdrillError, EmptyLayerError, LayerNotFoundError, SourceError

__all__ = [
    "Diagnostic", "DrillData", "EnclosureMatch", "Hole", "Origin", "ParameterValue", "RawDrillData",
    "RawHole", "RawOutline", "ReferenceOutline", "Severity", "SourceInfo", "StageRun",
    "Emitter", "Pipeline", "Source", "Stage",
    "AiPdfSource",
    "quantise",
    "SnapPositions", "SnapDiametersToDrillTable", "Deduplicate", "IdentifyHammondFootprint",
    "CheckReferenceSize", "ReviewGridTies", "RouteHoles", "DrillStandard", "DRILL_STANDARDS",
    "DEFAULT_STANDARD", "CheckCaseClearance",
    "Enclosure", "HAMMOND_1590", "footprints",
    "CaseModel", "Frame", "Rejection", "load_case_model",
    "StompdrillError", "EmitterError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
]
