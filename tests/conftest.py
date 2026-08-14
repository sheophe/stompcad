"""Shared test helpers.

``clean_registry`` and the hole builders were defined identically in two and
three files respectively, and the ``at()`` copies had already drifted apart.
"""

from __future__ import annotations

import pytest

from aidrill.emitters import base
from aidrill.model import DrillData, Hole, ReferenceOutline, SourceInfo

__all__ = ["at", "holes", "make_data"]


@pytest.fixture
def clean_registry():
    """Snapshot and restore the emitter registry around a test.

    Registering is a global side effect, and a test that leaked one would change
    what every later test — and ``--help`` — sees.
    """
    saved = dict(base.REGISTRY)
    try:
        yield base.REGISTRY
    finally:
        base.REGISTRY.clear()
        base.REGISTRY.update(saved)


def at(x: float, y: float, diameter: float = 7.0, *, index: int) -> Hole:
    """One hole with an explicit identity. ``index`` is keyword-only so a test
    can never pass it by accident where ``diameter`` was meant."""
    return Hole.from_measurement(x, y, diameter, index=index)


def holes(*specs: tuple[float, ...]) -> tuple[Hole, ...]:
    """Build holes from ``(x, y[, diameter])`` triples, numbering them 0..n-1.

    Sequential numbering here is deterministic per call — no module-level
    counter, so a test's hole ids do not depend on which tests ran before it.
    """
    return tuple(
        Hole.from_measurement(s[0], s[1], s[2] if len(s) > 2 else 7.0, index=i)
        for i, s in enumerate(specs)
    )


def make_data(*given: Hole, reference: ReferenceOutline | None = None) -> DrillData:
    """A ``DrillData`` around some holes, with provenance filled in.

    The two copies of this had diverged only in their ``SourceInfo``, and no
    test asserted on either version's, so the richer one wins.
    """
    return DrillData(
        holes=tuple(given),
        reference=reference,
        diagnostics=(),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )
