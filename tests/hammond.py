"""Real Hammond models for kernel tests, fetched on demand and never committed.

Models are opt-in: a standard suite run skips every test marked ``hammond``.
Run them with ``pytest --hammond``. Measurements here are the values kernel
tests assert against, cross-checked against aidrill's own catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from tools.fetch_case_model import cache_dir

__all__ = [
    "HammondModel", "MODELS", "BB_PROBES", "BB_RELIEF_MM",
    "cache_dir", "model_path", "require_model",
]


@dataclass(frozen=True, slots=True)
class HammondModel:
    """One enclosure's published dimensions and its measured plate thicknesses."""

    part: str
    footprint_mm: tuple[float, float]
    height_mm: float
    box_plate_mm: float
    lid_plate_mm: float


#: Measured from the distributed models, not guessed. Each part's box plate is
#: the gap between its outer drilled face and its inner floor; the lid's is its
#: own two faces. Footprint and height are cross-checked against aidrill's own
#: catalogue by ``test_every_model_matches_the_shipped_catalogue``.
MODELS: Mapping[str, HammondModel] = MappingProxyType(
    {
        "1590BB": HammondModel("1590BB", (119.5, 94.0), 34.0, 2.25, 2.0),
        "1590B": HammondModel("1590B", (112.4, 60.5), 31.0, 2.0, 2.0),
        "1590A": HammondModel("1590A", (92.6, 38.5), 31.0, 1.6, 2.0),
        "1590Y": HammondModel("1590Y", (92.0, 92.0), 42.0, 2.50, 3.2),
    }
)


#: Canonical face coordinates, in millimetres, of places on the 1590BB worth
#: aiming a test at. Derived by walking the distributed model's B-rep:
#:
#:   box inner floor   outer bound +/-55.33 x +/-42.58, with concave r=5.17 arcs
#:                     centred on the four boss axes at (+/-54.75, +/-42.00)
#:   box drilled face  114.97 x 89.47, inset from the 119.5 x 94.0 footprint
#:   lid inner face    +/-54.56 x +/-41.81, one bound, no notches
#:   cast lettering    13 inner bounds standing 0.50 mm proud of the box floor,
#:                     in two columns near x = 41.1 and x = 46.6
BB_PROBES: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        # Middle of the floor: clear of everything, on both box and lid.
        "clear": (0.0, 0.0),
        # Inside the play-area rectangle but inside a boss bite. This is the
        # point that separates THROUGH_BOSS from OFF_FACE: a hole here is on the
        # face yet meets metal, so a rule that only checked the outline passes it.
        "boss": (51.0, 38.5),
        # Beyond the floor's outline once the margin is taken off.
        "off_face": (55.0, 0.0),
        # On a cast letter. Must pass at margin 1.0 and fail at margin 0.4 —
        # the boundary a real model cannot place but a swept parameter can.
        "relief": (41.12, 7.12),
    }
)

#: How proud the cast lettering stands, in millimetres. The relief-versus-structure
#: threshold is the margin, so a margin either side of this value must flip the
#: classification. Sweeping the parameter replaces a fixture built to order.
BB_RELIEF_MM = 0.5


def model_path(part: str) -> Path | None:
    """The cached model for ``part``, or ``None``. Never downloads."""
    if part not in MODELS:
        raise ValueError(f"{part} is not a model these tests use")
    candidate = cache_dir() / f"{part}.stp"
    return candidate if candidate.is_file() else None


def require_model(part: str) -> Path:
    """The cached model, fetched if absent. Skips the test when unobtainable."""
    found = model_path(part)
    if found is not None:
        return found
    try:
        from tools.fetch_case_model import download, extract, url_for
    except ImportError:  # pragma: no cover - the helper is always present here
        pytest.skip(f"cannot fetch {part}: tools.fetch_case_model is unavailable")

    import tempfile

    try:
        payload = download(url_for(part))
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / f"{part}.zip"
            archive.write_bytes(payload)
            return extract(archive, part, cache_dir())
    except Exception as failure:  # noqa: BLE001 - any failure is a skip, not an error
        pytest.skip(f"cannot fetch {part}: {failure}")


@pytest.fixture(scope="session")
def hammond_bb() -> Path:
    """The 1590BB model, fetched once per session."""
    return require_model("1590BB")


@pytest.fixture(scope="session")
def hammond_b() -> Path:
    """The 1590B model, fetched once per session."""
    return require_model("1590B")


@pytest.fixture(scope="session")
def hammond_a() -> Path:
    """The 1590A model, fetched once per session."""
    return require_model("1590A")


@pytest.fixture(scope="session")
def hammond_y() -> Path:
    """The 1590Y model, fetched once per session."""
    return require_model("1590Y")
