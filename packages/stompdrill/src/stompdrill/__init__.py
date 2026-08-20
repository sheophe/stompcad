"""Extract, quantise, process, and emit drill data from Illustrator artwork.

The package root exposes the protocols, the concrete source, the quantisation
entry point and what it reads, the standard stages, and enclosure reference
data. The values themselves are ``stompmodel``'s; see ADR-0009.
"""

from .protocols import Emitter, Pipeline, Source, Stage
from .sources import AiPdfSource
from .quantise import RawDrillData, quantise
from .pipeline import (
    SnapPositions, SnapDiametersToDrillTable, Deduplicate, IdentifyHammondFootprint,
    CheckReferenceSize, ReviewGridTies, RouteHoles, DrillStandard, DRILL_STANDARDS,
    DEFAULT_STANDARD, CheckCaseClearance,
)
from .enclosures import Enclosure, HAMMOND_1590, footprints
from .cad import CaseModel, Frame, Rejection, load_case_model
from .errors import StompdrillError, EmptyLayerError, LayerNotFoundError, SourceError

__all__ = [
    "Emitter", "Pipeline", "Source", "Stage",
    "AiPdfSource",
    "RawDrillData", "quantise",
    "SnapPositions", "SnapDiametersToDrillTable", "Deduplicate", "IdentifyHammondFootprint",
    "CheckReferenceSize", "ReviewGridTies", "RouteHoles", "DrillStandard", "DRILL_STANDARDS",
    "DEFAULT_STANDARD", "CheckCaseClearance",
    "Enclosure", "HAMMOND_1590", "footprints",
    "CaseModel", "Frame", "Rejection", "load_case_model",
    "StompdrillError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
]
