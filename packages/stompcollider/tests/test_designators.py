"""The panel-reference filter: grammar, override order, and its refusals."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stompcollider.designators import parse_filter
from stompcollider.errors import UsageError

_PRESENT = ("D1", "D2", "D3", "D4", "RV1", "RV2", "SW1", "SW10", "C1")


def _admit(expression: str) -> set[str]:
    return set(parse_filter(expression).admit(_PRESENT))


def test_a_literal_admits_exactly_itself() -> None:
    assert _admit("D3") == {"D3"}


def test_a_glob_star_admits_a_run() -> None:
    assert _admit("RV*") == {"RV1", "RV2"}


def test_a_glob_question_matches_one_character_not_many() -> None:
    """Both clauses: SW1 is admitted and SW10 is not."""
    assert _admit("SW?") == {"SW1"}


def test_a_range_admits_its_endpoints_inclusively() -> None:
    assert _admit("D(2..4)") == {"D2", "D3", "D4"}


def test_a_later_term_overrides_an_earlier_one() -> None:
    """Left-to-right, not set arithmetic: the negation must remove what the
    glob added, and the order of the two terms must matter."""
    assert _admit("RV*,!RV1") == {"RV2"}
    assert _admit("!RV1,RV*") == {"RV1", "RV2"}


def test_a_negation_alone_admits_nothing() -> None:
    """No implicit 'everything' to subtract from; the spec gives no default."""
    assert _admit("!RV1") == set()


def test_a_malformed_expression_is_a_usage_error() -> None:
    for expression in ("D(", "D(4..2)", "", ",", "D(a..b)"):
        with pytest.raises(UsageError):
            parse_filter(expression)


def test_an_unbalanced_paren_is_malformed_on_its_own() -> None:
    """A lone '(' is never a valid literal or glob -- the grammar gives
    parentheses to the range production alone."""
    with pytest.raises(UsageError):
        parse_filter("D(")


def test_a_descending_range_is_malformed_on_its_own() -> None:
    """Distinct from an unbalanced paren: this one parses as a range and is
    refused only because its bounds are the wrong way round."""
    with pytest.raises(UsageError):
        parse_filter("D(4..2)")


def test_a_non_integer_bound_is_malformed_on_its_own() -> None:
    for expression in ("D(a..b)", "D(2.5..4)"):
        with pytest.raises(UsageError):
            parse_filter(expression)


def test_an_empty_term_is_malformed_on_its_own() -> None:
    """A bare comma, not a bad pattern -- distinct from every paren failure."""
    with pytest.raises(UsageError):
        parse_filter(",")


def test_an_empty_expression_is_malformed_on_its_own() -> None:
    with pytest.raises(UsageError):
        parse_filter("")


def test_a_bare_negation_is_malformed_on_its_own() -> None:
    """'!' with nothing to negate, distinct from every range failure."""
    with pytest.raises(UsageError):
        parse_filter("!")


def test_a_single_point_range_is_the_innocent_probe() -> None:
    """Looks as unusual as the guilty descending range beside it, but a range
    whose bounds are equal is valid and must not raise."""
    assert _admit("D(2..2)") == {"D2"}


def test_matching_is_case_sensitive() -> None:
    """The spec declares no case folding; a lower-case pattern must not reach
    the upper-case designators actually present."""
    assert _admit("d3") == set()
    assert _admit("d*") == set()


def test_surrounding_whitespace_is_insignificant() -> None:
    """Spacing around terms and commas is trimmed, not treated as part of the
    literal -- ' D3' must still match 'D3', not fail to match anything."""
    assert _admit(" D3 , RV* ") == {"D3", "RV1", "RV2"}


@given(st.lists(st.sampled_from(_PRESENT), min_size=1, max_size=4))
def test_parse_and_apply_is_idempotent(chosen: list[str]) -> None:
    """The property the spec names: applying an expression to its own result
    admits the same set."""
    expression = ",".join(chosen)
    once = parse_filter(expression).admit(_PRESENT)
    assert parse_filter(expression).admit(once) == once
