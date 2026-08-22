"""The reader's own contract, apart from any enclosure that uses it."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompgeom.step import _EPOCH, source_timestamp
from stompmodel.errors import DocumentError


def test_source_timestamp_reads_the_comment_marker(tmp_path: Path) -> None:
    """ST-Developer's comment above FILE_NAME, not the FILE_NAME field."""
    target = tmp_path / "stamped.stp"
    target.write_bytes(b"ISO-10303-21;\n/* time_stamp */ '2020-01-02T03:04:05'\n")

    assert source_timestamp(target) == "2020-01-02T03:04:05"


def test_source_timestamp_falls_back_to_the_epoch(tmp_path: Path) -> None:
    """Never a clock reading: determinism does not depend on the file
    carrying a stamp, only on every write copying the same value."""
    target = tmp_path / "bare.stp"
    target.write_bytes(b"ISO-10303-21;\n")

    assert source_timestamp(target) == _EPOCH


def test_reading_a_missing_file_is_a_document_error(tmp_path: Path) -> None:
    """A stompgeom reader cannot raise a stompdrill error; refusing a foreign
    document is a failure any member can have, so the base is shared."""
    from stompgeom.step import read_step

    with pytest.raises(DocumentError, match="no case model at"):
        read_step(tmp_path / "absent.stp")


def test_reading_a_non_step_file_is_a_document_error(tmp_path: Path) -> None:
    """Not readable is distinct from not present, and both are the file's
    fault rather than the data's."""
    from stompgeom.step import read_step

    target = tmp_path / "rubbish.stp"
    target.write_bytes(b"this is not a STEP file at all\n")

    with pytest.raises(DocumentError, match="is not a readable STEP file"):
        read_step(target)
