"""The universal preprocessing stages (SPEC §5).

Snapping, diameter normalisation and deduplication happen **here**, once, before
any emitter sees the data. No emitter may re-derive them: that is the central
constraint of the design, and the reason an earlier version could emit a drawing
and a drill file that disagreed about how many hole sizes a panel had.

Every class here satisfies ``aidrill.protocols.Stage`` and is a pure function of
its input. None of them asserts anything about which stage ran before it — order
is chosen by the caller (``cli.py``), not by the stages.
"""

from .dedupe import Deduplicate
from .diameters import (
    ClusterDiameters,
    DiameterStrategy,
    NoNormalization,
    NormalizeDiameters,
    TableDiameters,
)
from .enclosure import IdentifyHammondFootprint, normalize_part_name
from .snap import SnapPositions
from .sort import SortHoles
from .validate import CheckReferenceSize

__all__ = [
    "SnapPositions",
    "NormalizeDiameters",
    "DiameterStrategy",
    "ClusterDiameters",
    "TableDiameters",
    "NoNormalization",
    "Deduplicate",
    "CheckReferenceSize",
    "SortHoles",
    "IdentifyHammondFootprint",
    "normalize_part_name",
]
