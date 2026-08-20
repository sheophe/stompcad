"""The workspace's error base, and what must remain true of it."""

from __future__ import annotations

import pytest

from stompmodel.errors import EmitterError, StompError


def test_an_emitter_error_is_a_stomp_error() -> None:
    assert issubclass(EmitterError, StompError)


def test_a_stomp_error_is_an_ordinary_exception() -> None:
    assert issubclass(StompError, Exception)


def test_the_base_carries_its_message() -> None:
    with pytest.raises(StompError, match="no drill number"):
        raise StompError("no drill number")
