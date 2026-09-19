"""What the footer states, without an application to state it in."""

from __future__ import annotations

from rich.cells import cell_len

from stompcad.workbench.footer import MOVING, TYPING, Hint, Mode

__all__: list[str] = []


def test_a_mode_states_its_name_then_its_keys_divided() -> None:
    """The shape every mode takes: the name first, one cell per hint."""
    mode = Mode("moving", (Hint("?", "help"), Hint("q", "quit")))
    assert mode.describe() == " MOVING │ ? — help │ q — quit "


def test_a_message_takes_a_cell_of_its_own() -> None:
    """What the application is saying is divided from the keys, not appended to them."""
    mode = Mode("moving", (Hint("q", "quit"),))
    assert mode.describe("no artwork is selected") == (
        " MOVING │ q — quit │ no artwork is selected "
    )


def test_silence_adds_no_empty_cell() -> None:
    """The control: a message cell drawn always would leave a divider with nothing after it."""
    assert Mode("moving", (Hint("q", "quit"),)).describe() == " MOVING │ q — quit "


def test_the_way_out_is_stated_where_the_key_works() -> None:
    """`q` quits while moving and types while typing, so only one mode offers it."""
    assert Hint("q", "quit") in MOVING.hints
    assert not any(hint.keys == "q" for hint in TYPING.hints)
    assert any("esc" in hint.keys for hint in TYPING.hints)


def test_the_footer_fits_a_terminal_nobody_has_widened() -> None:
    """Eighty columns is the floor; a line past it loses whichever key comes last."""
    for mode in (MOVING, TYPING):
        assert cell_len(mode.describe()) <= 80
