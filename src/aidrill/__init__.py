"""aidrill — extract drill data from Adobe Illustrator artwork and emit it.

The package root carries what no registry can find for a caller. There is no
source registry and no stage registry — ``AiPdfSource`` and the stages are named
directly or not at all — so a root that exported the ``Source`` and ``Stage``
protocols without anything satisfying them would name two of the three roles a
library consumer then had no way to fill. Emitters are the exception that states
the rule: they *have* a registry, so a format is resolved through
``aidrill.emitters.get_emitter`` and named here no more than ``cli.py`` names one.

What stays in the subpackages is the material for changing the domain's answer
sets rather than for using them. ``METRIC_BANDS`` and ``FRACTIONAL_SIXTY_FOURTHS``
(``aidrill.pipeline``) generate the standards exported below and interest only
someone declaring a different series. Reference data a caller needs to *read* a
result is not in that class and is exported: ``DrillData.enclosure`` names a
footprint, and ``HAMMOND_1590`` is what turns that name into dimensions.

The quantisation phase is exported for the same reason, and it is the one part
of the flow with no protocol to stand in for it: ``quantise`` is a function, so a
consumer who has read a ``RawDrillData`` and cannot reach it has a measurement
and no way to turn it into the ``DrillData`` every stage and every emitter
takes. Its three quantisers come with it, because they are its arguments.

Both lists run in the order the flow runs: the data the roles pass, the roles,
the source, the quantisation phase, the stages, then what interprets the answer.
"""

from .model import (
    Diagnostic, DrillData, EnclosureMatch, Hole, Origin, ParameterValue, RawDrillData, RawHole,
    RawOutline, ReferenceOutline, Severity, SourceInfo, StageRun, Units,
)
from .protocols import Emitter, Pipeline, Source, Stage
from .sources import AiPdfSource
from .quantise import quantise
from .pipeline import (
    SnapPositions, SnapDiametersToDrillTable, Deduplicate, IdentifyHammondFootprint,
    CheckReferenceSize, ReviewGridTies, SortHoles, DrillStandard, DRILL_STANDARDS,
    DEFAULT_STANDARD,
)
from .enclosures import Enclosure, HAMMOND_1590, footprints
from .errors import (
    AidrillError, EmitterError, EmptyLayerError, LayerNotFoundError, SourceError,
)

__all__ = [
    "Diagnostic", "DrillData", "EnclosureMatch", "Hole", "Origin", "ParameterValue", "RawDrillData",
    "RawHole", "RawOutline", "ReferenceOutline", "Severity", "SourceInfo", "StageRun", "Units",
    "Emitter", "Pipeline", "Source", "Stage",
    "AiPdfSource",
    "quantise",
    "SnapPositions", "SnapDiametersToDrillTable", "Deduplicate", "IdentifyHammondFootprint",
    "CheckReferenceSize", "ReviewGridTies", "SortHoles", "DrillStandard", "DRILL_STANDARDS",
    "DEFAULT_STANDARD",
    "Enclosure", "HAMMOND_1590", "footprints",
    "AidrillError", "EmitterError", "EmptyLayerError", "LayerNotFoundError", "SourceError",
]
