"""The workspace's error base, and what must remain true of it."""

from __future__ import annotations

import pytest

from stompmodel.errors import DocumentError, EmitterError, StompError


def test_an_emitter_error_is_a_stomp_error() -> None:
    assert issubclass(EmitterError, StompError)


def test_a_document_error_is_a_stomp_error() -> None:
    """One base, so a caller composing two tools catches one type."""
    assert issubclass(DocumentError, StompError)


def test_a_refused_document_is_not_an_emitter_failure() -> None:
    """Nothing was being emitted, so catching one must not catch the other."""
    assert not issubclass(DocumentError, EmitterError)
    assert not issubclass(EmitterError, DocumentError)


def test_a_stomp_error_is_an_ordinary_exception() -> None:
    assert issubclass(StompError, Exception)


def test_the_base_carries_its_message() -> None:
    with pytest.raises(StompError, match="no drill number"):
        raise StompError("no drill number")
