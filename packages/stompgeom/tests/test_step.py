"""The reader's own contract, apart from any enclosure that uses it."""

from __future__ import annotations

from pathlib import Path

import pytest

from stompgeom.step import _EPOCH, bounding_box_mm, read_step, source_timestamp
from stompmodel.errors import DocumentError

from .xcaf import BODY_SIZE_MM, build_document


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
    document is a failure any member can have, so the base is shared.

    The message says "model", not "case model": an enclosure is one thing a
    caller might have been reading, and this layer knows about none of them.
    """
    with pytest.raises(DocumentError, match="no model at"):
        read_step(tmp_path / "absent.stp")


def test_reading_a_non_step_file_is_a_document_error(tmp_path: Path) -> None:
    """Not readable is distinct from not present, and both are the file's
    fault rather than the data's."""
    target = tmp_path / "rubbish.stp"
    target.write_bytes(b"this is not a STEP file at all\n")

    with pytest.raises(DocumentError, match="is not a readable STEP file"):
        read_step(target)


# ---------------------------------------------------------------------------
# The reader driven against a file this package wrote, needing no download
# ---------------------------------------------------------------------------


def _written(tmp_path: Path) -> Path:
    """A real STEP assembly, built in memory and written by this package."""
    from stompgeom.writer import write_step

    target = tmp_path / "round-trip.stp"
    write_step(
        build_document(),
        target,
        title="a round trip",
        timestamp="2020-01-02T03:04:05",
        originating_system="a supplied originating system 9.9",
    )
    return target


def test_read_step_returns_every_leaf_solid_and_no_assembly(tmp_path: Path) -> None:
    """``_collect`` recurses past an assembly label rather than recording it,
    so three components come back as three solids under their own names."""
    document = read_step(_written(tmp_path))

    assert len(document.solids) == 3
    assert {"body", "lid"} <= {solid.name for solid in document.solids}


def test_read_step_places_each_solid_in_assembly_coordinates(tmp_path: Path) -> None:
    """``_collect``'s central claim: reading the *component* label applies the
    placement its parent gave it. The lid is modelled at the origin like the
    body and lifted 5 mm by the assembly, so a reader taking the referred
    product label instead would hand it back sitting at zero."""
    document = read_step(_written(tmp_path))
    (body,) = document.named("body")
    (lid,) = document.named("lid")

    assert bounding_box_mm(body.shape)[2] == pytest.approx(0.0, abs=1e-6)
    assert bounding_box_mm(lid.shape)[2] == pytest.approx(5.0, abs=1e-6)


def test_bounding_box_mm_measures_a_solid_in_millimetres(tmp_path: Path) -> None:
    """The extent the document was built with, which is also what proves the
    reader's unit normalisation left a millimetre model alone."""
    (body,) = read_step(_written(tmp_path)).named("body")
    x0, y0, z0, x1, y1, z1 = bounding_box_mm(body.shape)

    assert (x1 - x0, y1 - y0, z1 - z0) == pytest.approx(BODY_SIZE_MM, abs=1e-6)


def test_a_file_this_package_wrote_reads_back_with_no_provenance(
    tmp_path: Path,
) -> None:
    """``source_timestamp``'s documented consequence, asserted rather than
    described: this writer emits no ``/* time_stamp */`` comment, so a file it
    produced carries a real header stamp the reader deliberately ignores."""
    target = _written(tmp_path)

    assert b"'2020-01-02T03:04:05'" in target.read_bytes()
    assert read_step(target).timestamp == _EPOCH
