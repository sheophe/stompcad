"""The writer's identity contract and its colour-chain guard."""

from __future__ import annotations

import pytest

from stompgeom import writer
from stompmodel.errors import EmitterError


def test_the_wrapper_product_name_is_the_workspace_not_a_package() -> None:
    """It is load-bearing, not cosmetic: ``_normalise`` strips the volatile
    counter appended to exactly this prefix, so the setter, the pattern and
    the replacement must all read one constant."""
    assert writer._PRODUCT_NAME == "stompcad"


def test_normalise_erases_the_translator_version_suffix() -> None:
    """Two writes of one document must not differ by a process counter."""
    payload = b"#1 = PRODUCT('stompcad 1.2','stompcad 1.2',' ',(#2));\n"

    assert b"'stompcad'" in writer._normalise(payload)
    assert b"stompcad 1.2" not in writer._normalise(payload)


def test_normalise_renumbers_assembly_usage_occurrences_from_one() -> None:
    """The NAUO counter is process-global and has no resettable key."""
    payload = (
        b"#9 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('417','','',#1,#2,$);\n"
        b"#10 = NEXT_ASSEMBLY_USAGE_OCCURRENCE('418','','',#1,#3,$);\n"
    )
    normalised = writer._normalise(payload)

    assert b"OCCURRENCE('1'" in normalised
    assert b"OCCURRENCE('2'" in normalised


def test_a_colour_chain_count_mismatch_is_refused() -> None:
    """Reordering nothing looks identical to reordering correctly unless the
    count is checked, which is what a kernel upgrade would silently break."""
    with pytest.raises(EmitterError, match="likely needs updating"):
        writer._reslot_colours(b"", expected=3)


def test_the_mismatch_message_names_this_module() -> None:
    """The remedy has to point at the pattern that needs the edit."""
    with pytest.raises(EmitterError, match=r"stompgeom\.writer"):
        writer._reslot_colours(b"", expected=1)
