"""Shared test helpers.

Four helpers lived in more than one test module, and two of them had already
drifted. ``clean_registry`` existed twice and the copies disagreed about what
they yield — one handed the test ``base.REGISTRY``, the other nothing — so a
test moved between files could stop compiling. ``make_data`` existed twice and
the copies disagreed about ``SourceInfo``, which means the two files were not
testing quite the same object. (``at`` was the one pair still byte-identical,
which is how divergence starts, not evidence against it.) One definition each,
here, so the next change lands in one place.
"""

from __future__ import annotations

import pytest

from aidrill.emitters import base
from aidrill.model import DrillData, Hole, ReferenceOutline, SourceInfo

__all__ = [
    "at",
    "clean_registry",
    "codes",
    "diameters",
    "holes",
    "make_data",
    "positions",
]


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


def at(x_nm: int, y_nm: int, diameter_nm: int = 7_000_000, *, index: int) -> Hole:
    """One quantised hole with an explicit identity.

    Nanometres, because that is the only unit a ``Hole`` holds: these helpers
    build the *output* side of the quantisation phase, never its input. A test
    that needs a measurement builds a ``RawHole`` itself, in millimetres, near
    the assertion that cares about it.

    ``index`` is keyword-only so a test can never pass it by accident where
    ``diameter_nm`` was meant.
    """
    return Hole.from_measurement(x_nm, y_nm, diameter_nm, index=index)


def holes(*specs: tuple[int, ...]) -> tuple[Hole, ...]:
    """Build holes from ``(x_nm, y_nm[, diameter_nm])`` triples, numbering them 0..n-1.

    Sequential numbering here is deterministic per call — no module-level
    counter, so a test's hole ids do not depend on which tests ran before it.

    It also makes ``index`` indistinguishable from array position, which is the
    coincidence this repo has been bitten by: an assertion about identity passes
    for position too. That is fine for the many tests that never mention an
    index, and wrong for any test that does — those must use ``at`` with
    deliberately out-of-order numbers instead of this.
    """
    return tuple(
        Hole.from_measurement(s[0], s[1], s[2] if len(s) > 2 else 7_000_000, index=i)
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


def codes(data: DrillData) -> list[str]:
    """The stable machine key of every diagnostic a stage raised, in order.

    Every diagnostic assertion in the pipeline tests matches on ``code``, never
    on ``message`` -- ``code`` is the stable API and the wording is not -- and
    this is what every one of those assertions goes through.
    """
    return [d.code for d in data.diagnostics]


def positions(data: DrillData) -> list[tuple[int, int]]:
    return [(h.x_nm, h.y_nm) for h in data.holes]


def diameters(data: DrillData) -> list[int]:
    return [h.diameter_nm for h in data.holes]
