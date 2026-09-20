"""Shared paths, an inert sink and the ``--boards``/``--hammond`` flags.

Later tasks all need the same fixture paths, the same do-nothing progress
sink and two opt-in flags. The board fixture is committed; the case model is
not -- it lives in the machine-local cache, which is why ``stompdrill`` gates
such tests behind ``--hammond``. ``stompcad`` mirrors both flags rather than
inventing a third convention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stompcad import cases

__all__ = ["TAR_AI", "TAR_PCB", "PANEL_REFERENCE", "case_model", "NullSink"]

_ROOT = Path(__file__).resolve().parents[3]
TAR_AI = _ROOT / "packages/stompdrill/tests/fixtures/tar.ai"
TAR_PCB = _ROOT / "packages/stompcollider/tests/fixtures/tar-pcb.stp"
PANEL_REFERENCE = "RV*,SW*,D(3..4),!RV5"


def case_model(part: str = "1590B") -> Path | None:
    """The cached enclosure model, or ``None``. Never downloads."""
    return cases.cached(part, cases.cache_dir())


@pytest.fixture(autouse=True)
def no_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches the manufacturer. A local server stands in where a
    download is the subject, and anything else fails here rather than
    depending on this machine having a network."""
    real = cases.download

    def guarded(url: str) -> bytes:
        if not url.startswith(("http://127.0.0.1", "http://localhost")):
            raise AssertionError(f"a test tried to download {url}")
        return real(url)

    monkeypatch.setattr("stompcad.cases.download", guarded)


class NullSink:
    """A sink that records nothing, for a run whose output is the artefact."""

    def update(self, position: float, path: tuple[str, ...]) -> None:
        return None


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--boards",
        action="store_true",
        default=False,
        help="run tests that read the committed STEP board fixture",
    )
    parser.addoption(
        "--hammond",
        action="store_true",
        default=False,
        help="run tests that need a cached Hammond enclosure model",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "boards: reads the STEP board fixture")
    config.addinivalue_line("markers", "hammond: needs a cached Hammond model")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip opt-in tests unless their flag was given.

    Deliberately not an ``addopts`` deselection: this repository's documented
    commands pass ``-o addopts=``, which would blank one and silently run
    everything. Mirrors ``packages/stompcollider/tests/conftest.py``.
    """
    for flag in ("boards", "hammond"):
        if config.getoption(f"--{flag}"):
            continue
        skip = pytest.mark.skip(reason=f"needs --{flag}")
        for item in items:
            if flag in item.keywords:
                item.add_marker(skip)
