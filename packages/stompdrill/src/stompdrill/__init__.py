"""Extract, quantise, process, and emit drill data from Illustrator artwork.

The package root exposes the one protocol that is this package's own, the
concrete source, the quantisation entry point and what it reads, the standard
stages, enclosure reference data, the supplied-case types, and this package's
own errors -- including every type a root-exported signature names, so a
caller never has to guess a submodule. The values themselves and the generic
pipeline contracts are ``stompmodel``'s; see ADR-0009.
"""

from .protocols import Source
from .sources import DEFAULT_FORM_DEPTH, AiPdfSource
from .quantise import RawDrillData, quantise
from .pipeline import (
    SnapPositions, SnapDiametersToDrillTable, Deduplicate, IdentifyHammondFootprint,
    CheckReferenceSize, ReviewGridTies, RouteHoles, DrillStandard, DRILL_STANDARDS,
    DEFAULT_STANDARD, CheckCaseClearance, CheckOutlineContainment,
)
from .enclosures import Enclosure, HAMMOND_1590, footprints
from .cad import CaseModel, OcpCaseModel, Rejection, load_case_model
from .errors import StompdrillError, EmptyLayerError, LayerNotFoundError, SourceError

__all__ = [
    "Source",
    "AiPdfSource", "DEFAULT_FORM_DEPTH",
    "RawDrillData", "quantise",
    "SnapPositions", "SnapDiametersToDrillTable", "Deduplicate", "IdentifyHammondFootprint",
    "CheckReferenceSize", "ReviewGridTies", "RouteHoles", "DrillStandard", "DRILL_STANDARDS",
    "DEFAULT_STANDARD", "CheckCaseClearance", "CheckOutlineContainment",
    "Enclosure", "HAMMOND_1590", "footprints",
    "CaseModel", "OcpCaseModel", "Rejection", "load_case_model",
    "StompdrillError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
]
