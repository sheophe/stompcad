"""The writer's identity contract and its colour-chain guard."""

from __future__ import annotations

import inspect

import pytest

from stompgeom import writer
from stompmodel.errors import EmitterError


def test_the_wrapper_product_name_is_the_workspace_not_a_package() -> None:
    """It is load-bearing, not cosmetic: ``_normalise`` strips the volatile
    counter appended to exactly this prefix, so the setter, the pattern and
    the replacement must all read one constant."""
    assert writer._PRODUCT_NAME == "stompcad"


def test_write_step_defaults_no_identity() -> None:
    """A default here would give a second consumer's assembly provenance
    from a tool that never touched it -- the whole reason this moved."""
    parameters = inspect.signature(writer.write_step).parameters

    assert parameters["title"].default is inspect.Parameter.empty
    assert parameters["originating_system"].default is inspect.Parameter.empty
    assert parameters["replaced_labels"].default == frozenset()


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


def test_normalise_rejoins_a_wrapped_product_entity_onto_one_line() -> None:
    """The writer's own line-wrap column tracks the volatile counter's digit
    count that call, so a rejoin-less rewrite would leak process history
    back into otherwise-identical bytes. Modelled on a genuine long product
    name (SC530's screw) found in a real written STEP artefact, wrapped here
    the way a longer line from this translator would be."""
    payload = (
        b"#7 = PRODUCT('SC530 (screw #6-32X 1_2'''' FH)',\n"
        b"  'SC530 (screw #6-32X 1_2'''' FH)','',(#8));\n"
    )
    normalised = writer._normalise(payload)

    assert b"\n  'SC530" not in normalised
    assert (
        b"#7 = PRODUCT('SC530 (screw #6-32X 1_2'''' FH)',"
        b"'SC530 (screw #6-32X 1_2'''' FH)','',(#8));"
    ) in normalised


def test_a_colour_chain_count_mismatch_is_refused() -> None:
    """Reordering nothing looks identical to reordering correctly unless the
    count is checked, which is what a kernel upgrade would silently break."""
    with pytest.raises(EmitterError, match="likely needs updating"):
        writer._reslot_colours(b"", expected=3)


def test_the_mismatch_message_names_this_module() -> None:
    """The remedy has to point at the pattern that needs the edit."""
    with pytest.raises(EmitterError, match=r"stompgeom\.writer"):
        writer._reslot_colours(b"", expected=1)


def test_the_mismatch_message_puts_each_count_in_its_own_place() -> None:
    """The two counts must land where they came from, not swapped.

    A mutation exchanging ``expected`` and ``len(chains)`` in the f-string
    would read exactly backwards -- "assigns 0 colour(s), but 1 STYLED_ITEM"
    for this input -- and send a real kernel-upgrade debugging session in
    the wrong direction. Only pinning both numbers together catches that;
    the two tests above each check one substring independently and pass
    under the swap.
    """
    with pytest.raises(EmitterError, match=r"assigns 1 colour.*0 STYLED_ITEM"):
        writer._reslot_colours(b"", expected=1)


#: Two complete nine-entity chains, modelled on the genuine chains a real
#: write of this code path produces (a screw's colour and its lid's colour,
#: found back to back at the tail of a written STEP file). The *first* chain
#: in file order (ids 100-108) colours the *higher* shape id (#500); the
#: second (ids 109-117) colours the lower (#200) -- content-sorted order
#: therefore swaps which content occupies which slot, which is the behaviour
#: under test. Each chain's own nine ids are contiguous, as the writer always
#: emits them; the shape and representation-context ids they refer to (#500,
#: #200, #999, #998) are deliberately outside both chains' own id ranges, so
#: a correct implementation leaves them untouched while an incorrect one that
#: shifted every id, not just each chain's own, would corrupt them.
_CHAIN_COLOURING_500 = (
    b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#101),#999);\n"
    b"#101 = STYLED_ITEM('color',(#102),#500);\n"
    b"#102 = PRESENTATION_STYLE_ASSIGNMENT((#103));\n"
    b"#103 = SURFACE_STYLE_USAGE(.BOTH.,#104);\n"
    b"#104 = SURFACE_SIDE_STYLE('',(#105));\n"
    b"#105 = SURFACE_STYLE_FILL_AREA(#106);\n"
    b"#106 = FILL_AREA_STYLE('',(#107));\n"
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
    b"#108 = COLOUR_RGB('',1.,0.,0.);\n"
)
_CHAIN_COLOURING_200 = (
    b"#109 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#110),#998);\n"
    b"#110 = STYLED_ITEM('color',(#111),#200);\n"
    b"#111 = PRESENTATION_STYLE_ASSIGNMENT((#112));\n"
    b"#112 = SURFACE_STYLE_USAGE(.BOTH.,#113);\n"
    b"#113 = SURFACE_SIDE_STYLE('',(#114));\n"
    b"#114 = SURFACE_STYLE_FILL_AREA(#115);\n"
    b"#115 = FILL_AREA_STYLE('',(#116));\n"
    b"#116 = FILL_AREA_STYLE_COLOUR('',#117);\n"
    b"#117 = COLOUR_RGB('',0.,1.,0.);\n"
)


def test_reslot_colours_swaps_content_by_the_shape_id_it_colours() -> None:
    """The slot each chain lands in is fixed by file position; which
    *content* fills that slot is fixed by the shape id it colours, sorted
    ascending -- not by the order the writer happened to emit the chains in.
    """
    payload = _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200

    # Grounding: confirm the payload is genuinely matched, not vacuously
    # accepted the way an empty payload would be.
    assert len(list(writer._COLOUR_CHAIN.finditer(payload))) == 2

    reslotted = writer._reslot_colours(payload, expected=2)

    # The first slot's own ids (100-108) are unmoved, but now carry the
    # content that colours #200 -- the chain that was originally second.
    assert b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#101),#998);" in reslotted
    assert b"#101 = STYLED_ITEM('color',(#102),#200);" in reslotted
    assert b"#108 = COLOUR_RGB('',0.,1.,0.);" in reslotted

    # The second slot's own ids (109-117) are unmoved, but now carry the
    # content that colours #500 -- the chain that was originally first.
    assert b"#109 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#110),#999);" in reslotted
    assert b"#110 = STYLED_ITEM('color',(#111),#500);" in reslotted
    assert b"#117 = COLOUR_RGB('',1.,0.,0.);" in reslotted

    # The pre-reslot pairing (slot 100-108 colouring #500) must be gone --
    # otherwise the assertions above could pass by accident on an identity
    # no-op that never actually reordered anything.
    assert b"STYLED_ITEM('color',(#102),#500);" not in reslotted
    assert b"STYLED_ITEM('color',(#111),#200);" not in reslotted


def test_reslot_colours_leaves_a_single_chain_unchanged() -> None:
    """Fewer than two chains means nothing to reorder -- the shortcut before
    any renumbering runs at all."""
    payload = _CHAIN_COLOURING_500

    assert len(list(writer._COLOUR_CHAIN.finditer(payload))) == 1
    assert writer._reslot_colours(payload, expected=1) == payload
