"""Emitter registry.

The registry exists so that adding an output format touches the new emitter's own
module plus one import line in ``emitters/__init__.py``, and nothing else.
``cli.py`` resolves ``--emit FORMAT=PATH`` through ``get_emitter``/``available``
and never names a concrete class. That is the open/closed principle made
checkable: a test asserts the CLI can dispatch to an emitter it has never heard
of.

**The promise covers dispatch, not configuration, and the difference is not a
quibble.** ``cli.py`` still names the three *options* classes in its
``_OPTION_BUILDERS`` table, keyed by options class rather than by format name, so
an emitter this registry has never seen is constructed with its own defaults and
works. But an emitter that wants a value off the command line needs a flag, and a
flag is an ``argparse`` line plus an entry in that table — a ``cli.py`` edit.
ADR-0001 Decision 2 records that limit (amended 2026-08-15), SPEC 2.1 states it,
and an unqualified claim here would be the file a contributor opens first telling
them something the other three deny. Letting a registry entry contribute its own
option factory would close the gap and has not been done.
"""

from __future__ import annotations

from typing import TypeVar

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
