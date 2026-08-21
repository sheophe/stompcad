"""Findings, their severity order, and the exit-code reduction over them."""

from __future__ import annotations

import operator

import pytest

from stompmodel.diagnostics import (
    EXIT_CLEAN,
    EXIT_ERRORS,
    EXIT_USAGE,
    EXIT_WARNINGS,
    Diagnostic,
    Severity,
    exit_for_severity,
)
from stompmodel.units import Nanometre

_A_FLOAT = 40_000_000.0


# --------------------------------------------------------------------------
# Severity orders total, and refuses to compare with anything else
# --------------------------------------------------------------------------


def test_severities_order_by_how_much_they_matter() -> None:
    """``worst_severity`` is a ``max`` over this order, and the exit code is read
    off that — so the order is a contract, not an implementation detail."""
    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert Severity.ERROR > Severity.WARNING > Severity.INFO
    assert Severity.WARNING >= Severity.WARNING
    assert Severity.WARNING <= Severity.WARNING
    assert max((Severity.INFO, Severity.ERROR, Severity.WARNING)) is Severity.ERROR


def test_comparing_a_severity_with_a_non_severity_is_not_implemented() -> None:
    assert Severity.INFO.__lt__(1) is NotImplemented


def test_a_severity_does_not_compare_with_anything_else() -> None:
    """Severity comparisons with non-severity values raise ``TypeError``.

    ``__lt__`` returning ``NotImplemented`` is only half the story: Python
    turns that into ``TypeError`` once neither operand's dunder resolves it.
    """
    with pytest.raises(TypeError):
        operator.lt(Severity.WARNING, "warning")
    with pytest.raises(TypeError):
        operator.ge(Severity.WARNING, 2)


# --------------------------------------------------------------------------
# the exit-code reduction
# --------------------------------------------------------------------------


def test_no_finding_and_an_informational_finding_both_exit_clean() -> None:
    assert exit_for_severity(None) == EXIT_CLEAN == 0
    assert exit_for_severity(Severity.INFO) == EXIT_CLEAN


def test_a_warning_exits_one_and_an_error_exits_two() -> None:
    assert exit_for_severity(Severity.WARNING) == EXIT_WARNINGS == 1
    assert exit_for_severity(Severity.ERROR) == EXIT_ERRORS == 2


def test_every_severity_has_an_exit_code() -> None:
    for severity in Severity:
        assert exit_for_severity(severity) in (EXIT_CLEAN, EXIT_WARNINGS, EXIT_ERRORS)


def test_a_usage_failure_exits_three_and_no_finding_can_reach_it() -> None:
    """A run that never started has no worst severity, so the reduction above
    cannot state this code and something has to. Every caller of the table
    shares it, which is why the number is fixed here and not per tool."""
    assert EXIT_USAGE == 3
    assert EXIT_USAGE not in {exit_for_severity(worst) for worst in (None, *Severity)}


# --------------------------------------------------------------------------
# what a finding may hold
# --------------------------------------------------------------------------


def test_a_diagnostic_locates_a_finding_in_whole_nanometres() -> None:
    """``location_nm`` is a position in the canonical frame like any other."""
    finding = Diagnostic.warning(
        "off-grid", "hole 4 moved", location_nm=(-40_000_000, 18_000_000)
    )
    assert finding.location_nm == (-40_000_000, 18_000_000)
    assert all(type(value) is int for value in finding.location_nm)


def test_a_finding_need_not_be_anywhere() -> None:
    """A finding about the panel as a whole has no coordinate to give."""
    assert Diagnostic.error("unmatched-enclosure", "113 × 60 is no footprint").location_nm is None


@pytest.mark.parametrize("value", [_A_FLOAT, True], ids=["float", "bool"])
def test_a_diagnostic_location_must_hold_whole_nanometres(value: object) -> None:
    """The guard Diagnostic shares with the rest of the model applies to its
    own location fields too, on both axes independently."""
    with pytest.raises(TypeError, match="nanometres"):
        Diagnostic.warning("off-grid", "hole 4 moved", location_nm=(value, 0))
    with pytest.raises(TypeError, match="nanometres"):
        Diagnostic.warning("off-grid", "hole 4 moved", location_nm=(0, value))


@pytest.mark.parametrize("value", [_A_FLOAT, True], ids=["float", "bool"])
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda v: Diagnostic.warning("off-grid", "hole 4 moved", data=(("moved_nm", v),)),
            id="Diagnostic.data",
        ),
        pytest.param(
            lambda v: Diagnostic(
                Severity.WARNING,
                "off-grid",
                "hole 4 moved",
                # A JSON round trip hands back lists; the model coerces them,
                # and this parameter exists to prove the guard sees inside one.
                data=[["moved_nm", v]],  # type: ignore[arg-type]
            ),
            id="Diagnostic.data-as-json-shaped-lists",
        ),
        pytest.param(
            lambda v: Diagnostic.warning(
                "off-grid",
                "hole 4 moved",
                # The length key is second on purpose: with only one key the
                # loop cannot distinguish skipping a non-length key from
                # stopping at it, and `continue -> break` goes unnoticed.
                data=(("stage", "ReviewGridTies"), ("moved_nm", v)),
            ),
            id="Diagnostic.data-with-a-non-length-key-first",
        ),
    ],
)
def test_a_payload_key_ending_nm_must_hold_whole_nanometres(build, value: object) -> None:
    """The suffix is the whole contract in a payload, so it is enforced."""
    with pytest.raises(TypeError, match="nanometres"):
        build(value)


def test_a_payload_key_ending_nm_accepts_whole_nanometres() -> None:
    """The other side of the same guard: it refuses a type, not a payload.

    Without this the rule above is satisfied by a check that rejects everything,
    and every stage in the pipeline would be unable to describe itself.
    """
    finding = Diagnostic.warning("off-grid", "hole 4 moved", data=(("moved_nm", -9_400),))
    assert finding is not None


def test_a_payload_key_that_is_not_a_length_may_hold_a_float() -> None:
    """The rule is the suffix, not "no floats"."""
    finding = Diagnostic.warning("off-grid", "hole 4 moved", data=(("share", 0.25),))
    assert finding.get("share") == 0.25


#: The finding as a stage writes it: tuples all the way down. Every JSON-shaped
#: spelling below is the same finding and must compare and hash as one.
#:
#: Two payload values, because the two are guarded differently. ``share`` is a
#: float under a key that does not name a length, which is the one combination
#: that would break if the ``_nm`` rule were ever widened into "a payload holds
#: integers": a share is genuinely 0.25, and a round trip that had to spell it
#: as a string would be a round trip that lost it. ``tied_locations`` is the one
#: payload value that is itself a sequence of sequences — ``grid-ambiguous``
#: names every place that tied, because a panel-level finding has no single
#: hole to point at — and so the only one a nested ``json.load`` list of lists
#: can arrive in.
_TUPLE_BUILT_FINDING = Diagnostic(
    Severity.WARNING,
    "off-grid",
    "hole 4 moved",
    location_nm=(Nanometre(-40_000_000), Nanometre(18_000_000)),
    data=(("share", 0.25), ("tied_locations", ((4, 9), (1, 2)))),
)

#: One list per case, and never two at once: ``json.load`` returns a list for
#: every array, so all four of these arrive together in practice — but folding
#: them into one case would let any three of the four coercions be deleted with
#: the case still failing on the fourth, which is no test of any of them.
_JSON_SHAPED_FINDINGS = [
    pytest.param(
        [-40_000_000, 18_000_000],
        (("share", 0.25), ("tied_locations", ((4, 9), (1, 2)))),
        id="location",
    ),
    pytest.param(
        (-40_000_000, 18_000_000),
        [("share", 0.25), ("tied_locations", ((4, 9), (1, 2)))],
        id="payload",
    ),
    pytest.param(
        (-40_000_000, 18_000_000),
        (["share", 0.25], ("tied_locations", ((4, 9), (1, 2)))),
        id="payload-pair",
    ),
    pytest.param(
        (-40_000_000, 18_000_000),
        (("share", 0.25), ("tied_locations", [[4, 9], [1, 2]])),
        id="payload-value",
    ),
]

#: Both ways a finding is built. The convenience constructors are the ones every
#: stage calls, the direct constructor is what ``dataclasses.replace`` and a
#: consumer rebuilding a document both go through, and a coercion in either one
#: alone leaves the other spelling of the same finding unequal to it.
_FINDING_CONSTRUCTORS = [
    pytest.param(
        lambda location_nm, data: Diagnostic(
            Severity.WARNING, "off-grid", "hole 4 moved", location_nm, data
        ),
        id="direct",
    ),
    pytest.param(
        lambda location_nm, data: Diagnostic.warning(
            "off-grid", "hole 4 moved", location_nm, data
        ),
        id="convenience",
    ),
]


@pytest.mark.parametrize(("location_nm", "data"), _JSON_SHAPED_FINDINGS)
@pytest.mark.parametrize("build", _FINDING_CONSTRUCTORS)
def test_a_finding_rebuilt_from_json_is_the_finding_it_was_written_from(
    build, location_nm, data
) -> None:
    """A ``Diagnostic`` is a value object, so a list in one is a broken one."""
    rebuilt = build(location_nm, data)
    assert rebuilt == _TUPLE_BUILT_FINDING
    assert hash(rebuilt) == hash(_TUPLE_BUILT_FINDING)
