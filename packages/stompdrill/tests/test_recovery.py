"""The recoveries' own tests, and the gate that keeps them independent."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.recovery.excellon import read_excellon
from tests.recovery.facts import nm_from_decimal

__all__: list[str] = []

RECOVERY = Path(__file__).resolve().parent / "recovery"

#: A minimal file with every statement kind the emitter can write.
SAMPLE = """\
M48
;DRILL file for panel.ai
;ORIGIN=lower-left corner of the reference outline, X56.200 Y30.250 from its centre
FMAT,2
METRIC,TZ
T1C5.000
T2C7.000
%
G90
G05
T1
X37.200Y11.500
T2
X16.200Y48.250
T0
M30
"""


def test_the_reader_recovers_positions_as_exact_nanometres():
    panel = read_excellon(SAMPLE)

    assert [(c.x_nm, c.y_nm) for c in panel.circles] == [
        (37_200_000, 11_500_000),
        (16_200_000, 48_250_000),
    ]


def test_the_reader_recovers_the_tool_number_the_library_would_have_dropped():
    """The one fact this artefact most needs checked; see ``parsers.md``."""
    panel = read_excellon(SAMPLE)

    assert [c.tool for c in panel.circles] == [1, 2]


def test_the_reader_recovers_each_tools_declared_diameter():
    panel = read_excellon(SAMPLE)

    assert [c.diameter_nm for c in panel.circles] == [5_000_000, 7_000_000]


def test_the_reader_numbers_hits_in_file_order_because_the_format_states_no_number():
    """Excellon carries the drill sequence as position and nothing else, so
    position is the file's own claim here rather than a recomputed one."""
    panel = read_excellon(SAMPLE)

    assert [c.number for c in panel.circles] == [1, 2]


def test_the_reader_recovers_the_header_comments():
    panel = read_excellon(SAMPLE)

    assert panel.comments[0] == "DRILL file for panel.ai"


def test_the_reader_reports_the_origin_comment_that_states_the_frame():
    """The half-extents live only in this comment; nothing else in the file
    says which corner the coordinates are measured from."""
    panel = read_excellon(SAMPLE)

    assert "X56.200 Y30.250 from its centre" in panel.comments[1]


def test_excellon_states_no_outline():
    """The format carries none. Reporting ``None`` keeps a comparison from
    silently checking nothing."""
    assert read_excellon(SAMPLE).outline_nm is None


def test_a_file_without_the_m48_header_is_refused():
    with pytest.raises(ValueError, match="no M48 header"):
        read_excellon("G90\nX1.0Y1.0\n")


def test_a_file_with_no_header_terminator_is_refused():
    with pytest.raises(ValueError, match="no header terminator"):
        read_excellon("M48\nFMAT,2\nMETRIC,TZ\n")


def test_an_inch_file_is_refused_rather_than_read_in_the_wrong_unit():
    """The failure mode this guards is the dangerous one: a plausible number
    at 25.4x the intended position."""
    with pytest.raises(ValueError, match="unsupported units"):
        read_excellon(SAMPLE.replace("METRIC,TZ", "INCH,LZ"))


def test_a_coordinate_before_any_tool_selection_is_refused():
    with pytest.raises(ValueError, match="no tool selected"):
        read_excellon(SAMPLE.replace("T1\nX37.200Y11.500", "X37.200Y11.500"))


def test_an_unknown_body_statement_is_refused_rather_than_skipped():
    """A reader that skipped what it does not model would pass an emitter
    change by omission."""
    with pytest.raises(ValueError, match="unhandled Excellon statement"):
        read_excellon(SAMPLE.replace("T0\nM30", "G85\nT0\nM30"))


def test_an_unknown_header_statement_is_refused_too():
    with pytest.raises(ValueError, match="unhandled Excellon header"):
        read_excellon(SAMPLE.replace("FMAT,2", "FMAT,2\nICI,ON"))


def test_a_coordinate_finer_than_a_nanometre_is_refused():
    with pytest.raises(ValueError, match="whole number of nanometres"):
        nm_from_decimal("1.0000001")


def test_a_whole_number_of_nanometres_is_exact_at_six_decimals():
    """The boundary the refusal above sits on, so the refusal is not simply
    rejecting every fractional value."""
    assert nm_from_decimal("1.000001") == 1_000_001


# ---------------------------------------------------------------------------
# independence
# ---------------------------------------------------------------------------


def imported_roots(source: str) -> set[str]:
    """Every absolute import root in ``source``. Relative imports cannot leave
    the subpackage, so they need no check."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def recovery_modules() -> list[Path]:
    """Every module in the subpackage, sorted so a failure names a stable one."""
    return sorted(p for p in RECOVERY.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_scanner_finds_an_emitter_import():
    """The gate is only worth its line if it fires; this is the proof it does."""
    assert "stompdrill" in imported_roots("from stompdrill.emitters.excellon import _value")


def test_the_scanner_finds_a_plain_package_import_too():
    """``import x`` and ``from x import y`` are the same edge, differently spelt."""
    assert "stompdrill" in imported_roots("import stompdrill.emitters.drawing_pdf")


def test_no_recovery_imports_the_package_whose_output_it_reads():
    """A recovery that inverts its emitter's own transform proves the emitter
    self-consistent and nothing more. The failure this must catch is a
    transform wrong in both directions, which self-consistency cannot see.
    """
    offenders = {
        str(module.relative_to(RECOVERY)): sorted(
            root for root in imported_roots(module.read_text(encoding="utf-8"))
            if root == "stompdrill"
        )
        for module in recovery_modules()
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_scan_reaches_every_recovery_module():
    """An empty or narrowed walk would pass the gate above by finding nothing."""
    scanned = {str(module.relative_to(RECOVERY)) for module in recovery_modules()}

    assert scanned >= {"__init__.py", "facts.py", "excellon.py"}
