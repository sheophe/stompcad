"""The user-facing orchestrator over ``stompdrill`` and ``stompcollider``.

Composes both tools as libraries into one run. It computes no geometry of
its own and reaches no kernel layer directly; every clash and drill result
it reports is produced by one of the two tools it wraps. See ADR-0008 and
ADR-0009.
"""

from __future__ import annotations

__all__: list[str] = []
