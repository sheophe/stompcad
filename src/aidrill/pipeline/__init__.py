"""The universal preprocessing, in its two halves (SPEC §5).

Whatever this subpackage holds happens **once**, before any emitter sees the
data. No emitter may re-derive any of it: that is the central constraint of the
design, and the reason an earlier version could emit a drawing and a drill file
that disagreed about how many hole sizes a panel had.

The two halves are not the same kind of thing, and the module split follows the
difference rather than the topic:

* **The quantisers** — ``SnapPositions``, ``SnapDiametersToDrillTable`` and
  ``IdentifyHammondFootprint`` — turn measurements into values the domain
  already holds. They are not ``Stage``s: they answer about one measurement at a
  time, they run in an order that is not the caller's to choose, and one of them
  can stop the run. ``aidrill.quantise`` composes them and is the only thing
  that does.
* **The stages** — ``Deduplicate``, ``SortHoles`` and ``CheckReferenceSize`` —
  are ``DrillData → DrillData``, satisfy ``aidrill.protocols.Stage``, and are
  pure functions of their input. None of them asserts anything about which stage
  ran before it; order is chosen by the caller (``cli.py``), not by the stages.

The two are composed in that order, and dedupe is why: it collapses holes that
share a position and a diameter *exactly*, which it can only do once something
else has decided that 6.9998 and 7.0002 are one size and that −39.9906 and −40.0
are one place.
"""

from .dedupe import Deduplicate
from .diameters import (
    DEFAULT_STANDARD,
    DRILL_STANDARDS,
    FRACTIONAL_SIXTY_FOURTHS,
    METRIC_BANDS,
    DrillStandard,
    SnapDiametersToDrillTable,
)
from .enclosure import CATALOGUE, IdentifyHammondFootprint, normalize_part_name
from .snap import SnapPositions
from .sort import SortHoles
from .validate import CheckReferenceSize

__all__ = [
    "SnapPositions",
    "SnapDiametersToDrillTable",
    "DrillStandard",
    "DRILL_STANDARDS",
    "DEFAULT_STANDARD",
    "METRIC_BANDS",
    "FRACTIONAL_SIXTY_FOURTHS",
    "Deduplicate",
    "CheckReferenceSize",
    "SortHoles",
    "IdentifyHammondFootprint",
    "normalize_part_name",
    "CATALOGUE",
]
