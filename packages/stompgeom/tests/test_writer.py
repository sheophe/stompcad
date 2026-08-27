"""The writer's identity contract, its colour-chain guard, and one real write."""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from stompgeom import writer
from stompmodel.errors import EmitterError

from .xcaf import build_document


def test_the_writer_no_longer_defines_its_own_name_rule() -> None:
    """One name rule lives in ``stompgeom.step``; a duplicate here would let
    the reader and the writer disagree about what a name is."""
    assert not hasattr(writer, "label_name")
    assert "label_name" not in writer.__all__


def test_write_step_is_gone_not_kept_as_a_wrapper() -> None:
    """Its only production caller stops needing it once ``render_step``
    returns bytes directly; a wrapper with no callers concentrates nothing."""
    assert not hasattr(writer, "write_step")
    assert "write_step" not in writer.__all__


def test_the_wrapper_product_name_is_the_workspace_not_a_package() -> None:
    """It is load-bearing, not cosmetic: ``_normalise`` strips the volatile
    counter appended to exactly this prefix, so the setter, the pattern and
    the replacement must all read one constant."""
    assert writer._PRODUCT_NAME == "stompcad"


def test_render_step_defaults_no_identity() -> None:
    """A default here would give a second consumer's assembly provenance
    from a tool that never touched it -- the whole reason this moved."""
    parameters = inspect.signature(writer.render_step).parameters

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
    with pytest.raises(EmitterError, match="needs updating"):
        writer._reslot_colours(b"", expected=3)


def test_the_mismatch_message_names_the_fixable_pattern() -> None:
    """The remedy has to point at the pattern that needs the edit -- one of
    two candidate causes now that a route the census does not walk is the
    other, so the message must still name the fixable symbol either way."""
    with pytest.raises(EmitterError, match=r"_COLOUR_CHAIN"):
        writer._reslot_colours(b"", expected=1)


def test_the_mismatch_message_names_the_other_candidate_cause_too() -> None:
    """A widened census can undercount just as easily as ``_COLOUR_CHAIN`` can
    fall behind a kernel upgrade; the message must not blame only one."""
    with pytest.raises(EmitterError, match=r"route the census does not walk"):
        writer._reslot_colours(b"", expected=1)


def test_the_mismatch_message_puts_each_count_in_its_own_place() -> None:
    """The two counts must land where they came from, not swapped.

    A mutation exchanging ``expected`` and ``len(chains)`` in the f-string
    would read exactly backwards -- "assigns 0 colour(s), but 1 colour
    chain(s)" for this input -- and send a real kernel-upgrade debugging
    session in the wrong direction. Only pinning both numbers together
    catches that; the two tests above each check one substring
    independently and pass under the swap.
    """
    with pytest.raises(EmitterError, match=r"assigns 1 colour.*0 colour chain"):
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


#: The four ids the two chains below reference but never define: each
#: chain's own shape (#500, #200) and its own representation context
#: (#999, #998). A real file defines these elsewhere; this test's payload
#: is only the colour-chain tail, so it stubs them in, or the integrity
#: check added for the corruption this test's own history exposed would
#: read every one of them as a dangling reference.
_EXTERNAL_STUBS = (
    b"#500 = ADVANCED_FACE('',(),#501,.T.);\n"
    b"#200 = ADVANCED_FACE('',(),#201,.T.);\n"
    b"#999 = ADVANCED_BREP_SHAPE_REPRESENTATION('',(),#1);\n"
    b"#998 = ADVANCED_BREP_SHAPE_REPRESENTATION('',(),#1);\n"
)


def test_reslot_colours_swaps_content_by_the_shape_id_it_colours() -> None:
    """The slot each chain lands in is fixed by file position; which
    *content* fills that slot is fixed by the shape id it colours, sorted
    ascending -- not by the order the writer happened to emit the chains in.
    """
    payload = _EXTERNAL_STUBS + _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200

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


#: A minimal presentation entity of a kind ``_COLOUR_CHAIN`` does not match
#: -- modelled on the ``CURVE_STYLE``/``DRAUGHTING_PRE_DEFINED_CURVE_FONT``
#: pair a real board interspersed between surface-colour chains.
_FOREIGN_ENTITY_BETWEEN_CHAINS = (
    b"#150 = CURVE_STYLE('',#151,POSITIVE_LENGTH_MEASURE(0.1),#152);\n"
    b"#151 = DRAUGHTING_PRE_DEFINED_CURVE_FONT('continuous');\n"
    b"#152 = COLOUR_RGB('',0.1,0.1,0.1);\n"
)


def test_a_foreign_entity_between_chains_is_refused() -> None:
    """This module cannot re-seat an entity that belongs to no chain of its
    own; its id is exactly as allocator-dependent as a colour chain's, so
    silently keeping it would make the output non-deterministic again --
    precisely the class of document Task 8 must go back to refusing.
    """
    payload = (
        _EXTERNAL_STUBS
        + _CHAIN_COLOURING_500
        + _FOREIGN_ENTITY_BETWEEN_CHAINS
        + _CHAIN_COLOURING_200
    )

    assert writer._foreign_entity_in_gaps(
        payload, list(writer._COLOUR_CHAIN.finditer(payload))
    )
    with pytest.raises(EmitterError, match="foreign entities"):
        writer._reslot_colours(payload, expected=2)


def test_a_clean_gap_between_chains_is_accepted() -> None:
    """The control beside the probe above: whitespace alone between two
    chains must not trip the detector, or every ordinary write -- this
    exact payload, minus the foreign entity -- would be refused too."""
    payload = _EXTERNAL_STUBS + _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200

    assert not writer._foreign_entity_in_gaps(
        payload, list(writer._COLOUR_CHAIN.finditer(payload))
    )
    writer._reslot_colours(payload, expected=2)  # must not raise


def test_reslot_colours_leaves_a_single_chain_unchanged() -> None:
    """Fewer than two chains means nothing to reorder -- the shortcut before
    any renumbering runs at all."""
    payload = _CHAIN_COLOURING_500

    assert len(list(writer._COLOUR_CHAIN.finditer(payload))) == 1
    assert writer._reslot_colours(payload, expected=1) == payload


#: A wrapper-bearing chain (9 ids) colouring the *higher* shape id, and a
#: bare, reused-colour chain (7 ids -- no wrapper, no own ``COLOUR_RGB``)
#: colouring the *lower* one, in that file order. Content-sorted order
#: swaps them, and their lengths differ, which is exactly the combination
#: a per-chain delta cannot survive: pairing a 9-id slot with 7-id content
#: (or the reverse) either drops a wrapper outright or duplicates ids
#: across the boundary. The stubs give the shape ids and the wrapper's own
#: representation context somewhere to resolve, matching a real file where
#: they are defined outside this tail region.
_UNSORTED_VARIABLE_LENGTH_STUBS = (
    b"#200 = ADVANCED_FACE('',(),#201,.T.);\n"
    b"#500 = ADVANCED_FACE('',(),#501,.T.);\n"
    b"#345 = ADVANCED_BREP_SHAPE_REPRESENTATION('',(),#1);\n"
)
_CHAIN_WITH_WRAPPER_COLOURING_500 = (
    b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"
    b"('',(#101,#108),#345);\n"
    b"#101 = STYLED_ITEM('color',(#102),#500);\n"
    b"#102 = PRESENTATION_STYLE_ASSIGNMENT((#103));\n"
    b"#103 = SURFACE_STYLE_USAGE(.BOTH.,#104);\n"
    b"#104 = SURFACE_SIDE_STYLE('',(#105));\n"
    b"#105 = SURFACE_STYLE_FILL_AREA(#106);\n"
    b"#106 = FILL_AREA_STYLE('',(#107));\n"
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
    b"#108 = COLOUR_RGB('',1.,0.,0.);\n"
)
_BARE_CHAIN_REUSING_500S_COLOUR_COLOURING_200 = (
    b"#109 = STYLED_ITEM('color',(#110),#200);\n"
    b"#110 = PRESENTATION_STYLE_ASSIGNMENT((#111));\n"
    b"#111 = SURFACE_STYLE_USAGE(.BOTH.,#112);\n"
    b"#112 = SURFACE_SIDE_STYLE('',(#113));\n"
    b"#113 = SURFACE_STYLE_FILL_AREA(#114);\n"
    b"#114 = FILL_AREA_STYLE('',(#115));\n"
    b"#115 = FILL_AREA_STYLE_COLOUR('',#108);\n"
)


def test_reslot_colours_does_not_dangle_a_reused_colour_across_a_reorder() -> None:
    """A reused colour must follow its owner wherever the reorder puts it.

    The wrapper-bearing chain (9 ids) colours the higher shape id and the
    bare, reused-colour chain (7 ids) colours the lower one, so a
    content-sort reorder swaps their positions while their lengths differ
    -- exactly the shape a per-chain delta cannot renumber correctly,
    since it assumes every chain owns the same count of contiguous ids.
    """
    payload = (
        _UNSORTED_VARIABLE_LENGTH_STUBS
        + _CHAIN_WITH_WRAPPER_COLOURING_500
        + _BARE_CHAIN_REUSING_500S_COLOUR_COLOURING_200
    )

    assert len(list(writer._COLOUR_CHAIN.finditer(payload))) == 2

    # A clean return is itself part of the assertion: _reslot_colours's own
    # integrity check would have refused the dangling reference this exact
    # payload produced under the pre-fix implementation (confirmed by hand
    # while building this test), so reaching the line below already proves
    # that defect is gone for this shape of input.
    reslotted = writer._reslot_colours(payload, expected=2)

    # Both chains must end up pointing at the *same* final colour id --
    # the reused-colour chain's own reference must follow the wrapper
    # chain's colour to wherever it landed, not linger on its pre-reslot id.
    after = list(writer._COLOUR_CHAIN.finditer(reslotted))
    by_shape = {match.group(3): match for match in after}
    assert by_shape[b"200"].group(4) == by_shape[b"500"].group(4)

    # And that shared id must actually be defined, as the wrapper chain's
    # own colour, with the literal this fixture gave it.
    final_colour_id = by_shape[b"500"].group(4)
    assert (
        b"#" + final_colour_id + b" = COLOUR_RGB('',1.,0.,0.);"
    ) in reslotted


#: One colour shared by two chains, written the two ways the kernel
#: alternates between: the payloads differ only in which chain carries the
#: inline ``COLOUR_RGB`` and in the slot order that goes with it, since
#: ``STEPCAFControl_Writer`` hands the definition to whichever chain of a
#: shared colour it writes first. Measured on a five-solid document whose
#: solids all share one colour: six fresh interpreters produced four
#: distinct files, differing in nothing else. Both must reslot to one
#: answer, which is true only once ownership is decided by content.
_SHARED_COLOUR_OWNED_BY_500 = (
    b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#101),#999);\n"
    b"#101 = STYLED_ITEM('color',(#102),#500);\n"
    b"#102 = PRESENTATION_STYLE_ASSIGNMENT((#103));\n"
    b"#103 = SURFACE_STYLE_USAGE(.BOTH.,#104);\n"
    b"#104 = SURFACE_SIDE_STYLE('',(#105));\n"
    b"#105 = SURFACE_STYLE_FILL_AREA(#106);\n"
    b"#106 = FILL_AREA_STYLE('',(#107));\n"
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
    b"#108 = COLOUR_RGB('',1.,0.,0.);\n"
    b"#109 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#110),#998);\n"
    b"#110 = STYLED_ITEM('color',(#111),#200);\n"
    b"#111 = PRESENTATION_STYLE_ASSIGNMENT((#112));\n"
    b"#112 = SURFACE_STYLE_USAGE(.BOTH.,#113);\n"
    b"#113 = SURFACE_SIDE_STYLE('',(#114));\n"
    b"#114 = SURFACE_STYLE_FILL_AREA(#115);\n"
    b"#115 = FILL_AREA_STYLE('',(#116));\n"
    b"#116 = FILL_AREA_STYLE_COLOUR('',#108);\n"
)
_SHARED_COLOUR_OWNED_BY_200 = (
    b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#101),#998);\n"
    b"#101 = STYLED_ITEM('color',(#102),#200);\n"
    b"#102 = PRESENTATION_STYLE_ASSIGNMENT((#103));\n"
    b"#103 = SURFACE_STYLE_USAGE(.BOTH.,#104);\n"
    b"#104 = SURFACE_SIDE_STYLE('',(#105));\n"
    b"#105 = SURFACE_STYLE_FILL_AREA(#106);\n"
    b"#106 = FILL_AREA_STYLE('',(#107));\n"
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
    b"#108 = COLOUR_RGB('',1.,0.,0.);\n"
    b"#109 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#110),#999);\n"
    b"#110 = STYLED_ITEM('color',(#111),#500);\n"
    b"#111 = PRESENTATION_STYLE_ASSIGNMENT((#112));\n"
    b"#112 = SURFACE_STYLE_USAGE(.BOTH.,#113);\n"
    b"#113 = SURFACE_SIDE_STYLE('',(#114));\n"
    b"#114 = SURFACE_STYLE_FILL_AREA(#115);\n"
    b"#115 = FILL_AREA_STYLE('',(#116));\n"
    b"#116 = FILL_AREA_STYLE_COLOUR('',#108);\n"
)


def test_which_chain_of_a_shared_colour_defines_it_is_settled_by_content() -> None:
    """Two chains sharing a colour must not depend on the kernel's choice.

    Renumbering alone cannot reach this: the chains' own *structure*
    differs between the two payloads, one carrying a definition the other
    only references, so the id map derived from them differs too. Moving
    the definition onto the chain content order puts first is what makes
    the two collapse onto one answer.
    """
    first = _EXTERNAL_STUBS + _SHARED_COLOUR_OWNED_BY_500
    second = _EXTERNAL_STUBS + _SHARED_COLOUR_OWNED_BY_200

    # Grounding: an identity claim over two equal -- or two unmatched --
    # payloads would hold whatever _reslot_colours did with them.
    assert first != second
    assert len(list(writer._COLOUR_CHAIN.finditer(first))) == 2
    assert len(list(writer._COLOUR_CHAIN.finditer(second))) == 2

    reslotted = writer._reslot_colours(first, expected=2)

    assert reslotted == writer._reslot_colours(second, expected=2)
    # The definition landed on the chain colouring the lower shape id --
    # the first in content order -- and there is still exactly one of it.
    assert b"#101 = STYLED_ITEM('color',(#102),#200);" in reslotted
    assert (
        b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
        b"#108 = COLOUR_RGB('',1.,0.,0.);"
    ) in reslotted
    assert reslotted.count(b"COLOUR_RGB") == 1


#: Two chains colouring one shape (#500) through structurally identical
#: heads, so their id-free signatures tie and the colour each resolves to
#: is the only component of the sort key left to order them by. Written
#: red first, blue second; blue's literal sorts first, so an order that
#: read only the shape id would leave them exactly as written.
_ONE_SHAPE_COLOURED_RED_THEN_BLUE = (
    b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#101),#999);\n"
    b"#101 = STYLED_ITEM('color',(#102),#500);\n"
    b"#102 = PRESENTATION_STYLE_ASSIGNMENT((#103));\n"
    b"#103 = SURFACE_STYLE_USAGE(.BOTH.,#104);\n"
    b"#104 = SURFACE_SIDE_STYLE('',(#105));\n"
    b"#105 = SURFACE_STYLE_FILL_AREA(#106);\n"
    b"#106 = FILL_AREA_STYLE('',(#107));\n"
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n"
    b"#108 = COLOUR_RGB('',1.,0.,0.);\n"
    b"#109 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#110),#999);\n"
    b"#110 = STYLED_ITEM('color',(#111),#500);\n"
    b"#111 = PRESENTATION_STYLE_ASSIGNMENT((#112));\n"
    b"#112 = SURFACE_STYLE_USAGE(.BOTH.,#113);\n"
    b"#113 = SURFACE_SIDE_STYLE('',(#114));\n"
    b"#114 = SURFACE_STYLE_FILL_AREA(#115);\n"
    b"#115 = FILL_AREA_STYLE('',(#116));\n"
    b"#116 = FILL_AREA_STYLE_COLOUR('',#117);\n"
    b"#117 = COLOUR_RGB('',0.,0.,1.);\n"
)


def test_the_resolved_literal_orders_two_chains_colouring_one_shape() -> None:
    """The control for the sort key's second component.

    Without it the key reads the shape id alone, two chains colouring one
    shape tie, and a stable sort hands them back in the order the kernel
    happened to write them -- which is the freedom this whole pass exists
    to remove.
    """
    payload = _EXTERNAL_STUBS + _ONE_SHAPE_COLOURED_RED_THEN_BLUE
    parsed = [
        writer._parse_colour_chain(found)
        for found in writer._COLOUR_CHAIN.finditer(payload)
    ]

    # Grounding: the other two components of the key are equal here, so the
    # resolved literal is the only one that can decide the order.
    assert len(parsed) == 2
    assert parsed[0].shape == parsed[1].shape
    assert writer._signature(parsed[0].head) == writer._signature(parsed[1].head)

    reslotted = writer._reslot_colours(payload, expected=2)

    # b"0.,0.,1." sorts before b"1.,0.,0.", so blue takes the first slot --
    # the reverse of the order the two chains were written in.
    assert b"#108 = COLOUR_RGB('',0.,0.,1.);" in reslotted
    assert b"#117 = COLOUR_RGB('',1.,0.,0.);" in reslotted
    assert b"#108 = COLOUR_RGB('',1.,0.,0.);" not in reslotted


#: Two chains colouring one shape (#500) in one colour, so shape id and
#: resolved literal both tie and only the id-free content signature is
#: left to order them by. The bare chain is written first; the
#: wrapper-bearing one's signature sorts ahead of it (``M`` before ``S``
#: once the ids are gone), so an order blind to content leaves them as
#: written.
_ONE_SHAPE_AND_COLOUR_BARE_THEN_WRAPPED = (
    b"#100 = STYLED_ITEM('color',(#101),#500);\n"
    b"#101 = PRESENTATION_STYLE_ASSIGNMENT((#102));\n"
    b"#102 = SURFACE_STYLE_USAGE(.BOTH.,#103);\n"
    b"#103 = SURFACE_SIDE_STYLE('',(#104));\n"
    b"#104 = SURFACE_STYLE_FILL_AREA(#105);\n"
    b"#105 = FILL_AREA_STYLE('',(#106));\n"
    b"#106 = FILL_AREA_STYLE_COLOUR('',#107);\n"
    b"#107 = COLOUR_RGB('',1.,0.,0.);\n"
    b"#108 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(#109),#999);\n"
    b"#109 = STYLED_ITEM('color',(#110),#500);\n"
    b"#110 = PRESENTATION_STYLE_ASSIGNMENT((#111));\n"
    b"#111 = SURFACE_STYLE_USAGE(.BOTH.,#112);\n"
    b"#112 = SURFACE_SIDE_STYLE('',(#113));\n"
    b"#113 = SURFACE_STYLE_FILL_AREA(#114);\n"
    b"#114 = FILL_AREA_STYLE('',(#115));\n"
    b"#115 = FILL_AREA_STYLE_COLOUR('',#107);\n"
)


def test_the_content_signature_orders_two_chains_agreeing_on_shape_and_colour() -> None:
    """The control for the sort key's third component.

    Without it two chains agreeing on shape and colour tie, and a stable
    sort returns the kernel's own order -- and since ownership is handed to
    whichever chain that order puts first, an unordered tie decides which
    chain carries the definition too.
    """
    payload = _EXTERNAL_STUBS + _ONE_SHAPE_AND_COLOUR_BARE_THEN_WRAPPED
    parsed = [
        writer._parse_colour_chain(found)
        for found in writer._COLOUR_CHAIN.finditer(payload)
    ]
    literals = {chain.colour: chain.literal for chain in parsed if chain.literal}

    # Grounding: the other two components of the key are equal here, so the
    # signature is the only one that can decide the order -- and it differs.
    assert len(parsed) == 2
    assert parsed[0].shape == parsed[1].shape
    assert literals[parsed[0].colour] == literals[parsed[1].colour]
    assert writer._signature(parsed[0].head) != writer._signature(parsed[1].head)

    reslotted = writer._reslot_colours(payload, expected=2)

    # The wrapper-bearing chain takes the first slot, and the definition
    # with it, though it was written second and owned nothing.
    assert (
        b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"
        b"('',(#101),#999);"
    ) in reslotted
    assert b"#109 = STYLED_ITEM('color',(#110),#500);" in reslotted
    assert b"#100 = STYLED_ITEM" not in reslotted


#: Two chains defining one RGB literal at two different ids -- a shape
#: ``STEPCAFControl_Writer`` never writes, since it defines a colour once
#: and reuses it. Canonical ownership cannot express it: moving the
#: definition to the first chain in content order leaves the second's own
#: definition owning nothing, dropping an entity the region held.
_TWO_DEFINITIONS_OF_ONE_COLOUR = _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200.replace(
    b"COLOUR_RGB('',0.,1.,0.)", b"COLOUR_RGB('',1.,0.,0.)"
)


def test_two_definitions_of_one_colour_are_refused_not_silently_merged() -> None:
    """Ownership is permuted among the chains, never added to or dropped.

    The guard is what proves that of the run rather than of the argument:
    a merge would look like a successful canonicalisation while quietly
    emitting one entity fewer than the kernel wrote.
    """
    payload = _EXTERNAL_STUBS + _TWO_DEFINITIONS_OF_ONE_COLOUR

    assert payload.count(b"COLOUR_RGB('',1.,0.,0.)") == 2
    with pytest.raises(EmitterError, match="added or dropped rather than moved"):
        writer._reslot_colours(payload, expected=2)

    # The control beside the probe: the same two chains with two *different*
    # literals -- one definition each -- must still be accepted, or every
    # ordinary write would be refused too.
    writer._reslot_colours(
        _EXTERNAL_STUBS + _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200, expected=2
    )


#: A colour living outside every chain, as a pre-defined STEP colour does.
#: Both chains below name it and neither defines it, so there is nothing
#: for content order to hand ownership of.
_PRE_DEFINED_COLOUR = b"#900 = DRAUGHTING_PRE_DEFINED_COLOUR('red');\n"
_CHAIN_NAMING_AN_EXTERNAL_COLOUR_500 = _CHAIN_COLOURING_500.replace(
    b"#107 = FILL_AREA_STYLE_COLOUR('',#108);\n#108 = COLOUR_RGB('',1.,0.,0.);\n",
    b"#107 = FILL_AREA_STYLE_COLOUR('',#900);\n",
)
_CHAIN_NAMING_AN_EXTERNAL_COLOUR_200 = _CHAIN_COLOURING_200.replace(
    b"#116 = FILL_AREA_STYLE_COLOUR('',#117);\n#117 = COLOUR_RGB('',0.,1.,0.);\n",
    b"#116 = FILL_AREA_STYLE_COLOUR('',#900);\n",
)


def test_a_colour_defined_outside_every_chain_is_refused() -> None:
    """No definition to move means no ownership to settle by content.

    Such a chain's colour reference is as allocator-dependent as any other
    id in the region, and this pass has no chain of its own to re-seat it
    through -- the same reason a foreign entity between two chains is
    refused rather than copied through non-canonically.
    """
    payload = (
        _EXTERNAL_STUBS
        + _PRE_DEFINED_COLOUR
        + _CHAIN_NAMING_AN_EXTERNAL_COLOUR_500
        + _CHAIN_NAMING_AN_EXTERNAL_COLOUR_200
    )

    assert len(list(writer._COLOUR_CHAIN.finditer(payload))) == 2
    assert b"COLOUR_RGB" not in payload
    with pytest.raises(EmitterError, match="defined nowhere among the chains"):
        writer._reslot_colours(payload, expected=2)

    # The control beside the probe: the same two chains, each with its own
    # inline definition, must still be accepted.
    writer._reslot_colours(
        _EXTERNAL_STUBS + _CHAIN_COLOURING_500 + _CHAIN_COLOURING_200, expected=2
    )


def test_check_reslot_integrity_refuses_a_duplicated_definition() -> None:
    """The GUILTY probe for the duplicate-id branch: reached by no other
    test, so this module's own suite is the only thing that exercises it.
    """
    with pytest.raises(EmitterError, match="duplicated or missing"):
        writer._check_reslot_integrity(
            result=b"#10 = STYLED_ITEM('color',(#11),#5);\n",
            chain_text=b"#10 = STYLED_ITEM('color',(#11),#5);\n#10 = STYLED_ITEM('color',(#11),#5);\n",
            id_map={1: 10, 2: 11},
        )


def test_check_reslot_integrity_refuses_a_dangling_reference() -> None:
    """The GUILTY probe for the dangling-reference branch: reached by no
    other test, so this module's own suite is the only thing that
    exercises it.
    """
    with pytest.raises(EmitterError, match="dangling reference"):
        writer._check_reslot_integrity(
            result=b"#10 = STYLED_ITEM('color',(#999),#5);\n",
            chain_text=b"#10 = STYLED_ITEM('color',(#999),#5);\n",
            id_map={1: 10},
        )


def test_the_optional_wrapper_does_not_bridge_an_unrelated_entity() -> None:
    """A wrapper absent before this item must not attach to a later one.

    ``[^;]*?`` cannot cross an entity boundary (no entity body here holds a
    literal ``;``), so an intervening ``CARTESIAN_POINT`` between a wrapper
    and the styled item it does *not* own must stop the optional group from
    matching at all -- group 1 is ``None`` and the point itself is never
    folded into the chain's own ids.
    """
    payload = (
        b"#100 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"
        b"('',(#200),#99);\n"
        b"#150 = CARTESIAN_POINT('',(0.,0.,0.));\n"
        b"#200 = STYLED_ITEM('color',(#201),#17);\n"
        b"#201 = PRESENTATION_STYLE_ASSIGNMENT((#202));\n"
        b"#202 = SURFACE_STYLE_USAGE(.BOTH.,#203);\n"
        b"#203 = SURFACE_SIDE_STYLE('',(#204));\n"
        b"#204 = SURFACE_STYLE_FILL_AREA(#205);\n"
        b"#205 = FILL_AREA_STYLE('',(#206));\n"
        b"#206 = FILL_AREA_STYLE_COLOUR('',#207);\n"
        b"#207 = COLOUR_RGB('',1.,0.,0.);\n"
    )

    found = writer._COLOUR_CHAIN.search(payload)

    assert found is not None
    assert found.group(1) is None
    assert found.start() == payload.index(b"#200 = STYLED_ITEM")
    assert b"CARTESIAN_POINT" not in found.group(0)


# ---------------------------------------------------------------------------
# The writer driven end to end, against a document built in memory
# ---------------------------------------------------------------------------

#: Deliberately unlike anything the kernel or any consumer would choose, so a
#: default leaking into the header is a failure rather than a coincidence.
_TITLE = "a title only this test supplies"
_TIMESTAMP = "2020-01-02T03:04:05"
_ORIGINATING_SYSTEM = "a supplied originating system 9.9"

#: ``FILE_NAME``'s seven fields in order: name, time_stamp, author,
#: organization, preprocessor_version, originating_system, authorisation.
#: Pinning the whole entity is what proves each supplied string reached its
#: own slot rather than merely appearing somewhere in the header.
_FILE_NAME = re.compile(
    rb"FILE_NAME\((?P<name>'[^']*'),(?P<stamp>'[^']*'),\([^)]*\),\([^)]*\),"
    rb"'[^']*',(?P<system>'[^']*'),'[^']*'\);"
)

_NAUO_ID = re.compile(rb"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('(\d+)'")


def _write(document: Any) -> bytes:
    """Render ``document`` with this module's supplied identity."""
    return writer.render_step(
        document,
        title=_TITLE,
        timestamp=_TIMESTAMP,
        originating_system=_ORIGINATING_SYSTEM,
    )


def _header(payload: bytes) -> re.Match[bytes]:
    """The ``FILE_NAME`` entity, unwrapped onto one line."""
    found = _FILE_NAME.search(re.sub(rb"\n\s*", b"", payload[:2048]))
    assert found is not None, "the written file has no FILE_NAME entity"
    return found


@pytest.fixture(scope="module")
def written_twice() -> tuple[bytes, bytes]:
    """One in-memory document rendered twice into one process.

    Each call picks its own scratch path internally, so comparing the two
    payloads proves that path -- caller-supplied or otherwise -- never
    reaches the bytes. Both counters this module erases are process-global,
    so a *first* write in a fresh interpreter carries a clean product name
    and occurrence ids of one whether or not ``_normalise`` ran at all.
    Reading the second write is what makes the assertions below fail when
    the normalisation is removed.
    """
    document = build_document()
    return _write(document), _write(document)


@pytest.fixture(scope="module")
def written(written_twice: tuple[bytes, bytes]) -> bytes:
    """The second of the two writes -- see ``written_twice``."""
    return written_twice[1]


def test_two_writes_of_one_document_are_byte_identical(
    written_twice: tuple[bytes, bytes],
) -> None:
    """The whole reason this module exists. Nothing about the process that
    produced a file may reach the file, so a second write of an unchanged
    document is the first write again."""
    first, second = written_twice

    assert first == second
    # Grounding: an empty or truncated write would satisfy equality too.
    assert first.startswith(b"ISO-10303-21;")
    assert first.rstrip().endswith(b"END-ISO-10303-21;")


def test_the_first_write_in_a_fresh_process_already_carries_the_product_name() -> None:
    """``STEPControl_Controller.Init_s()`` in ``render_step`` defines the
    ``Interface_Static`` keys the two ``SetCVal_s`` calls below it rely on;
    without it a *first* write in a virgin process silently keeps OCC's own
    defaults. Every other test in this module runs after ``test_step.py``
    has already read a (deliberately invalid) STEP file, which defines those
    keys as a side effect and hides the bug even with ``Init_s()`` removed --
    see the module docstring notes near ``Init_s()`` for the full story.
    A fresh interpreter, which has read nothing, is the only way to catch it.
    """
    script = (
        "from tests.xcaf import build_document\n"
        "from stompgeom.writer import render_step\n"
        "data = render_step(build_document(), title='t',\n"
        "    timestamp='2020-01-01T00:00:00', originating_system='sys')\n"
        "assert b\"PRODUCT('stompcad','stompcad'\" in data, 'missing configured name'\n"
        "assert b\"PRODUCT('Open CASCADE\" not in data, 'kept OCC default name'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_the_header_carries_the_title_it_was_given(written: bytes) -> None:
    """The identity-injection contract: no default, and the caller's string
    in ``FILE_NAME``'s own name slot rather than anywhere in the header."""
    assert _header(written).group("name") == b"'" + _TITLE.encode() + b"'"


def test_the_header_carries_the_originating_system_it_was_given(
    written: bytes,
) -> None:
    """The slot a reader consults to learn which tool cut the geometry. It
    sits next to ``preprocessor_version``, which the kernel fills in itself,
    so only a positional check tells the two apart."""
    system = _header(written).group("system")

    assert system == b"'" + _ORIGINATING_SYSTEM.encode() + b"'"
    assert b"Open CASCADE" not in system


def test_the_header_carries_the_timestamp_it_was_given(written: bytes) -> None:
    """Copied from the source document, never read from the clock -- which is
    what lets two runs a day apart agree byte for byte."""
    assert _header(written).group("stamp") == b"'" + _TIMESTAMP.encode() + b"'"


def test_the_written_file_names_no_consumer_of_this_package(written: bytes) -> None:
    """ADR-0009's rule, asserted against the bytes rather than the source: an
    assembly written by a second consumer must not claim stompdrill made it."""
    assert b"stompdrill" not in written


def test_the_wrapper_products_volatile_counter_is_erased(written: bytes) -> None:
    """The translator names its own wrapper product for the nameless leaf and
    appends a per-write counter to it. The prefix is ours; the counter is
    process history and must not survive into the file."""
    assert b"PRODUCT('stompcad','stompcad'" in written
    assert re.search(rb"stompcad \d+\.\d+", written) is None


def test_the_assembly_usage_occurrence_ids_are_renumbered_from_one(
    written: bytes,
) -> None:
    """Three components, so ids one to three -- not the raw counter, which by
    this second write has already moved past them."""
    assert _NAUO_ID.findall(written) == [b"1", b"2", b"3"]


def test_one_colour_chain_is_written_for_each_coloured_leaf(written: bytes) -> None:
    """Grounding for the reslot pass: ``_reslot_colours`` refuses a count it
    did not expect, so a write that produced no chains at all would have
    raised rather than reordered. This pins the two the document assigns."""
    assert len(writer._COLOUR_CHAIN.findall(written)) == 2


# ---------------------------------------------------------------------------
# Sub-shape colours: the census this module was fitted to a two-solid
# enclosure without.
# ---------------------------------------------------------------------------


def test_a_per_face_coloured_document_is_written_not_refused() -> None:
    """The census must count what the writer will emit. Counting only leaf
    solids under-counts a board by orders of magnitude and the guard fires.
    """
    from .fixtures.per_face_colours import per_face_coloured_document

    payload = writer.render_step(
        per_face_coloured_document(),
        title="probe",
        timestamp="1970-01-01T00:00:00+00:00",
        originating_system="test",
    )
    assert payload.count(b"STYLED_ITEM") >= 6


def test_two_writes_of_one_document_are_byte_identical_across_processes() -> None:
    """Sub-shape colours must not reintroduce process-history leakage.

    This fixture's own chains land in sort order regardless of reslot (see
    the guilty probe below), so this does not exercise the reslot's
    effect; it proves the timestamp, NAUO counters and general write path
    stay deterministic for this new kind of document across processes,
    which only a shelled-out second interpreter can actually test.
    """
    script = (
        "from stompgeom.writer import render_step;"
        "from tests.fixtures.per_face_colours import per_face_coloured_document;"
        "import hashlib,sys;"
        "sys.stdout.write(hashlib.sha256(render_step("
        "per_face_coloured_document(), title='p',"
        "timestamp='1970-01-01T00:00:00+00:00', originating_system='t')).hexdigest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout
        for _ in range(2)
    }
    assert len(digests) == 1


#: Repeated enough times that two independent allocations of the same
#: two-solid document landing in the same slot order by chance is
#: astronomically unlikely -- fresh in-process allocations swap freely
#: between the two possible orders -- without the runtime cost of a real
#: subprocess per try.
_RESLOT_TRIALS = 20


def test_the_byte_identity_control_fails_when_the_reslot_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GUILTY probe for the cross-process test above.

    ``per_face_coloured_document`` cannot serve here: a single product's own
    faces always enumerate in shape-id order, already ``_reslot_colours``'s
    sort order, so it can never disagree with the reslot enough to show it
    mattered. ``xcaf.build_document()``'s two distinct solids do swap slots
    freely between fresh in-process allocations, so disabling the reslot
    must let that freedom reach the file, while leaving it in must pull
    every allocation back to the one order the shape ids pick.
    """

    def render(document: Any) -> bytes:
        return writer.render_step(
            document, title="p",
            timestamp="1970-01-01T00:00:00+00:00", originating_system="t",
        )

    monkeypatch.setattr(writer, "_reslot_colours", lambda payload, expected: payload)
    disabled = {render(build_document()) for _ in range(_RESLOT_TRIALS)}
    monkeypatch.undo()
    enabled = {render(build_document()) for _ in range(_RESLOT_TRIALS)}

    # The claim under test: disabling the reslot lets fresh allocations
    # disagree; restoring it pulls every one of the same allocations back to
    # a single order.
    assert len(disabled) > 1
    assert len(enabled) == 1


#: Shelled out, printing three facts about one render: its digest, and the
#: two counts that ground the digest comparison. ``render_step`` is reached
#: through a fresh interpreter because the choice under test is made from a
#: ``TShape`` pointer, which only a separate process reallocates.
_REPEATED_COLOUR_PROBE = (
    "import hashlib, sys;"
    "from stompgeom.writer import render_step;"
    "from tests.fixtures.repeated_colour import repeated_colour_document;"
    "payload = render_step(repeated_colour_document(), title='p',"
    " timestamp='1970-01-01T00:00:00+00:00', originating_system='t');"
    "sys.stdout.write('%s %d %d' % (hashlib.sha256(payload).hexdigest(),"
    " payload.count(b'STYLED_ITEM'), payload.count(b'COLOUR_RGB')))"
)

#: The kernel's choice was measured landing on four of this fixture's five
#: chains across six launches, so accidental agreement costs no better
#: than a factor of five per extra launch: three launches agree by chance
#: about once in twenty-five, which a review run of this test actually
#: hit, while ten put it under one in a million. Each launch is a real
#: interpreter, about half a second, so the count is bounded by that as
#: much as by the odds -- and the falsifiable weight sits on the in-suite
#: pair in ``..._defines_it_is_settled_by_content``, which a subprocess
#: cannot be monkeypatched to carry.
_REPEATED_COLOUR_LAUNCHES = 10


def test_shapes_sharing_one_colour_render_identically_across_processes() -> None:
    """The guarantee ``render_step``'s docstring states, measured end to end.

    Five solids sharing one RGB value make the kernel choose which of the
    five chains defines it inline; that choice comes from a pointer, so it
    varies between processes and takes the chains' own structure with it.
    """
    reports = [
        subprocess.run(
            [sys.executable, "-c", _REPEATED_COLOUR_PROBE],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout.split()
        for _ in range(_REPEATED_COLOUR_LAUNCHES)
    ]

    assert len({report[0] for report in reports}) == 1
    # Grounding: agreement over a document that never exercised the choice
    # would prove nothing. Five styled items sharing one COLOUR_RGB is what
    # makes four of the five chains reference a definition they do not own.
    assert all(report[1:] == ["5", "1"] for report in reports)
