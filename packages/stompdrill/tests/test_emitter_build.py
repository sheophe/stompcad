"""Tests for building emitters from published settings, without the CLI."""

from __future__ import annotations


def test_an_emitter_is_built_without_importing_the_cli() -> None:
    """stompcad builds emitters from the library, not from argparse."""
    from stompdrill import OutputSettings, make_emitter

    emitter = make_emitter("excellon", OutputSettings())
    assert emitter.name == "excellon"
