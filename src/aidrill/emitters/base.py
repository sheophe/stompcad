"""Emitter registry.

The registry exists so that adding an output format touches exactly one file —
the new emitter's own. ``cli.py`` resolves ``--emit FORMAT=PATH`` through
``get_emitter``/``available`` and never names a concrete class. That is the
open/closed principle made checkable: a test asserts the CLI can dispatch to an
emitter it has never heard of.
"""

from __future__ import annotations

from typing import Callable, Mapping, TypeVar

from ..errors import EmitterError

__all__ = ["register_emitter", "get_emitter", "available", "REGISTRY"]

REGISTRY: dict[str, type] = {}

T = TypeVar("T", bound=type)


def register_emitter(cls: T) -> T:
    """Class decorator. Registers under ``cls.name``."""
    name = getattr(cls, "name", None)
    if not name:
        raise TypeError(f"{cls.__name__} must define a non-empty class attribute 'name'")
    if name in REGISTRY and REGISTRY[name] is not cls:
        raise TypeError(f"emitter name {name!r} already registered by {REGISTRY[name].__name__}")
    REGISTRY[name] = cls
    return cls


def get_emitter(name: str) -> type:
    try:
        return REGISTRY[name]
    except KeyError:
        raise EmitterError(
            f"unknown output format {name!r}; available: {', '.join(available())}"
        ) from None


def available() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))
