"""Tests for reaching the dock composition phases without the CLI."""

from __future__ import annotations


def test_the_dock_composes_without_the_cli() -> None:
    """Every phase stompcad drives is reachable from the package, not argparse."""
    import stompcollider

    for name in (
        "registration", "docked", "derived_tolerance", "admit",
        "board_geometry", "build_pipeline", "parse_filter",
    ):
        assert hasattr(stompcollider, name), name
        assert name in stompcollider.__all__, name
