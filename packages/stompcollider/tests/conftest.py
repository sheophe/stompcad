"""The ``--boards`` flag, and the marker it enables.

Modelled on ``stompdrill``'s ``--hammond``: a kernel-backed test that reads
the committed board fixture is opt-in, so a standard run stays quick. It is
not a kernel *availability* switch -- ``stompgeom`` is an unconditional
dependency, so a missing kernel is a failure here, never a silent pass.
"""

from __future__ import annotations

import pytest

__all__: list[str] = []


def pytest_addoption(parser) -> None:
    """Add --boards, which enables tests that read the STEP board fixture."""
    parser.addoption(
        "--boards",
        action="store_true",
        default=False,
        help="run tests that read the committed STEP board fixture through the kernel",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "boards: reads the STEP board fixture; run with --boards"
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Skip boards-marked tests unless --boards was given.

    Deliberately not an ``addopts`` deselection: this repository's documented
    commands pass ``-o addopts=``, which would blank one and silently
    re-enable every one of these.
    """
    if config.getoption("--boards"):
        return
    skip = pytest.mark.skip(reason="reads the STEP board fixture; run: pytest --boards")
    for item in items:
        if "boards" in item.keywords:
            item.add_marker(skip)
