"""The emitter registry's contract (``aidrill.emitters.base``).

The registry is what makes ``--emit FORMAT=PATH`` open/closed: adding a format
touches only the new emitter's own file. That bargain has three terms, and each
one is a refusal rather than a feature — an emitter without a name, or a second
emitter squatting on a name already taken, would corrupt the mapping the CLI
resolves through, and an unknown format must fail with the list of formats that
*would* have worked. Those refusals were the only untested lines in the module.

Every test here runs inside ``clean_registry``, which snapshots ``REGISTRY``
and puts it back afterwards: registering is a global side effect, and a test
that leaks one would change what every later test — and ``--help`` — sees.
"""

from __future__ import annotations

import pytest

from aidrill.emitters import base
from aidrill.emitters.base import available, get_emitter, register_emitter
from aidrill.errors import EmitterError


@pytest.fixture
def clean_registry():
    """Snapshot and restore the emitter registry around a test."""
    saved = dict(base.REGISTRY)
    try:
        yield base.REGISTRY
    finally:
        base.REGISTRY.clear()
        base.REGISTRY.update(saved)


def test_the_fixture_really_restores_the_registry(clean_registry):
    """Guard the guard: the leak-proofing is itself worth one assertion."""
    assert "registry-fixture-probe" not in available()

    @register_emitter
    class Probe:
        name = "registry-fixture-probe"

        def emit(self, data):
            return ""

    assert "registry-fixture-probe" in available()


def test_the_probe_did_not_leak():
    assert "registry-fixture-probe" not in available()


# ---------------------------------------------------------------------------
# registration refuses what would corrupt the mapping
# ---------------------------------------------------------------------------


def test_registering_a_class_without_a_name_is_a_type_error(clean_registry):
    before = available()

    with pytest.raises(TypeError) as failure:

        @register_emitter
        class Nameless:
            def emit(self, data):
                return ""

    assert "Nameless" in str(failure.value)
    assert "name" in str(failure.value)
    assert available() == before  # nothing was half-registered


@pytest.mark.parametrize("empty", ["", None])
def test_an_empty_name_is_no_name_at_all(clean_registry, empty):
    """``name = ""`` would register a format nobody can ask for."""
    with pytest.raises(TypeError):

        @register_emitter
        class Blank:
            name = empty

            def emit(self, data):
                return ""


def test_a_second_class_may_not_take_an_existing_name(clean_registry):
    @register_emitter
    class First:
        name = "registry-collision"

        def emit(self, data):
            return "first"

    with pytest.raises(TypeError) as failure:

        @register_emitter
        class Second:
            name = "registry-collision"

            def emit(self, data):
                return "second"

    message = str(failure.value)
    assert "registry-collision" in message
    assert "First" in message, "the error must name the incumbent, not just the loser"
    assert base.REGISTRY["registry-collision"] is First  # the incumbent survives


def test_a_registered_format_may_not_be_replaced_by_a_stranger(clean_registry):
    """The same refusal, aimed at a name that ships with the package."""
    existing = available()[0]

    with pytest.raises(TypeError):

        @register_emitter
        class Impostor:
            name = existing

            def emit(self, data):
                return "not the real thing"


def test_registering_the_same_class_twice_is_harmless(clean_registry):
    """Idempotent: a module imported twice must not explode."""

    class Repeat:
        name = "registry-idempotent"

        def emit(self, data):
            return ""

    assert register_emitter(Repeat) is Repeat
    assert register_emitter(Repeat) is Repeat
    assert base.REGISTRY["registry-idempotent"] is Repeat


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


def test_get_emitter_returns_the_registered_class(clean_registry):
    @register_emitter
    class Known:
        name = "registry-known"

        def emit(self, data):
            return ""

    assert get_emitter("registry-known") is Known


def test_unknown_format_raises_and_lists_what_is_available(clean_registry):
    with pytest.raises(EmitterError) as failure:
        get_emitter("dxf")

    message = str(failure.value)
    assert "dxf" in message
    for name in available():
        assert name in message, f"the error hides the available format {name!r}"


def test_available_is_sorted_and_complete(clean_registry):
    @register_emitter
    class Late:
        name = "registry-aaa-late"

        def emit(self, data):
            return ""

    names = available()
    assert names == tuple(sorted(names))
    assert names == tuple(sorted(base.REGISTRY))
