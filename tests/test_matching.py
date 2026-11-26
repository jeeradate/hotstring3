"""Tests for the rolling buffer and suffix matching (no real keyboard involved)."""

from __future__ import annotations

import pytest
from pynput.keyboard import Key

from hotstring3 import config
from hotstring3.listener import KeyboardListener, TriggerBuffer
from hotstring3.suggestions import SuggestionState, TriggerSuggestion


def test_buffer_starts_empty() -> None:
    buffer = TriggerBuffer()
    assert buffer.text == ""
    assert len(buffer) == 0
    assert buffer.match({";em"}) is None


def test_buffer_keeps_only_last_eight_characters() -> None:
    buffer = TriggerBuffer()
    for character in "abcdefghij":
        buffer.push(character)
    assert buffer.text == "cdefghij"
    assert len(buffer) == config.BUFFER_SIZE


def test_push_ignores_empty_string() -> None:
    buffer = TriggerBuffer()
    buffer.push("")
    assert buffer.text == ""


def test_backspace_removes_last_character() -> None:
    buffer = TriggerBuffer()
    for character in ";ema":
        buffer.push(character)
    buffer.backspace()
    assert buffer.text == ";em"
    for _ in range(10):
        buffer.backspace()
    assert buffer.text == ""


def test_clear() -> None:
    buffer = TriggerBuffer()
    buffer.push("x")
    buffer.clear()
    assert buffer.text == ""


def test_exact_suffix_match() -> None:
    buffer = TriggerBuffer()
    for character in "hello;em":
        buffer.push(character)
    assert buffer.match({";em"}) == ";em"


def test_matching_is_case_sensitive() -> None:
    buffer = TriggerBuffer()
    for character in "Hello;EM":
        buffer.push(character)
    assert buffer.match({";em"}) is None
    assert buffer.match({";EM"}) == ";EM"


def test_no_match_when_trigger_is_only_a_prefix() -> None:
    buffer = TriggerBuffer()
    buffer.push(";")
    assert buffer.match({";em"}) is None


def test_trigger_spanning_oldest_buffered_characters() -> None:
    buffer = TriggerBuffer()
    for character in "xx;abcdefgh":
        buffer.push(character)
    # Only the last eight characters remain, so a nine character trigger cannot match.
    assert buffer.text == "abcdefgh"
    assert buffer.match({";abcdefgh"}) is None


def test_maximum_length_trigger_matches() -> None:
    buffer = TriggerBuffer()
    for character in ";abcdefg":
        buffer.push(character)
    assert buffer.match({";abcdefg"}) == ";abcdefg"


def test_shortest_match_wins() -> None:
    buffer = TriggerBuffer()
    for character in ";em":
        buffer.push(character)
    # Both triggers match the end of ";em"; the shorter one fires first.
    assert buffer.match({";em", "em"}) == "em"


def test_trigger_that_is_a_prefix_does_not_match() -> None:
    buffer = TriggerBuffer()
    for character in ";eml":
        buffer.push(character)
    assert buffer.match({";em"}) is None
    assert buffer.match({";eml"}) == ";eml"


def test_alternate_trigger_matches() -> None:
    buffer = TriggerBuffer()
    for character in "abc;zz":
        buffer.push(character)
    assert buffer.match({";em", ";zz"}) == ";zz"


def test_match_ignores_empty_trigger() -> None:
    buffer = TriggerBuffer()
    buffer.push("a")
    assert buffer.match({""}) is None


def test_capacity_can_be_smaller() -> None:
    buffer = TriggerBuffer(capacity=3)
    for character in "abcdef":
        buffer.push(character)
    assert buffer.text == "def"


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TriggerBuffer(capacity=0)


def test_listener_reload_and_pause() -> None:
    listener = KeyboardListener(lambda trigger, command: None)
    listener.reload({";em": "tmyname@example.com"})
    assert listener._commands == {";em": "tmyname@example.com"}

    listener.set_paused(True)
    assert listener.paused is True
    listener.set_paused(False)
    assert listener.paused is False


def test_listener_buffer_reset_on_pause() -> None:
    buffer = TriggerBuffer()
    listener = KeyboardListener(lambda trigger, command: None, buffer=buffer)
    buffer.push(";e")
    listener.set_paused(True)
    assert buffer.text == ""


def test_characters_typed_while_ctrl_is_held_are_ignored(monkeypatch) -> None:
    """Ctrl+C is a shortcut, not text: its characters must not be buffered."""
    monkeypatch.setattr("hotstring3.listener._shortcut_modifier_down", lambda: True)
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    matched: list[str] = []
    listener = KeyboardListener(lambda trigger, _command: matched.append(trigger))
    listener.reload({";tok": "tHello"})

    listener._on_press(Key.ctrl_l)
    for character in ";tok":
        listener._on_press(typed(character))

    assert matched == []
    assert listener.buffer.text == ""


def test_stale_modifier_state_does_not_block_typing(monkeypatch) -> None:
    """A missed Ctrl release (screen lock, UAC) must not disable all triggers."""
    monkeypatch.setattr("hotstring3.listener._shortcut_modifier_down", lambda: True)
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    matched: list[str] = []
    listener = KeyboardListener(lambda trigger, _command: matched.append(trigger))
    listener.reload({";tok": "tIt is OK, thank you"})

    listener._on_press(Key.ctrl_l)  # press seen, release lost
    monkeypatch.setattr("hotstring3.listener._shortcut_modifier_down", lambda: False)
    for character in ";tok":
        listener._on_press(typed(character))

    assert matched == [";tok"]


def test_uppercase_trigger_fires_with_shift(monkeypatch) -> None:
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    matched: list[str] = []
    listener = KeyboardListener(lambda trigger, _command: matched.append(trigger))
    listener.reload({";EM": "tone@example.com"})

    listener._on_press(typed(";"))
    listener._on_press(Key.shift)
    listener._on_press(typed("E"))
    listener._on_press(typed("M"))

    assert matched == [";EM"]


# ---------------------------------------------------------------------------
# Suggestion popup events
# ---------------------------------------------------------------------------


class FakeKey:
    """A minimal stand-in for a pynput character key."""

    def __init__(self, character: str) -> None:
        self.char = character


def typed(character: str) -> FakeKey:
    return FakeKey(character)


def test_listener_publishes_two_character_suggestions(monkeypatch) -> None:
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    states: list[SuggestionState | None] = []
    listener = KeyboardListener(lambda _trigger, _command: None, on_suggestions=states.append)
    listener.reload(
        {";em": "tone@example.com"},
        [TriggerSuggestion(";em", "Email", "tone@example.com")],
    )

    listener._on_press(typed(";"))
    # A lone ";" opens stage 1: the list of second-character categories.
    assert states[-1] is not None
    assert states[-1].is_category_stage
    assert states[-1].categories[0].prefix == ";e"

    listener._on_press(typed("e"))
    assert states[-1] is not None
    assert states[-1].prefix == ";e"
    assert states[-1].items[0].description == "Email"

    listener._on_press(typed("x"))
    assert states[-1] is None


def test_listener_hides_suggestions_when_a_trigger_fires(monkeypatch) -> None:
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    states: list[SuggestionState | None] = []
    matched: list[tuple[str, str]] = []
    listener = KeyboardListener(
        lambda trigger, command: matched.append((trigger, command)),
        on_suggestions=states.append,
    )
    listener.reload(
        {";em": "tone@example.com"},
        [TriggerSuggestion(";em", "Email", "tone@example.com")],
    )

    listener._on_press(typed(";"))
    listener._on_press(typed("e"))
    assert states[-1] is not None

    listener._on_press(typed("m"))
    assert matched == [(";em", "tone@example.com")]
    assert states[-1] is None


def test_listener_updates_suggestions_on_backspace_and_dismiss(monkeypatch) -> None:
    monkeypatch.setattr("hotstring3.listener.send_backspaces", lambda _count: None)
    states: list[SuggestionState | None] = []
    listener = KeyboardListener(lambda _trigger, _command: None, on_suggestions=states.append)
    listener.reload({}, [TriggerSuggestion(";em", "Email")])

    listener._on_press(typed(";"))
    listener._on_press(typed("e"))
    assert states[-1] is not None

    listener._on_press(Key.backspace)
    assert states[-1] is not None
    assert states[-1].is_category_stage

    listener._on_press(typed("e"))
    assert states[-1] is not None
    assert [item.trigger for item in states[-1].items] == [";em"]
    listener._on_press(Key.esc)
    assert states[-1] is None
    assert listener.buffer.text == ""


def test_listener_hides_suggestions_on_click_and_pause() -> None:
    states: list[SuggestionState | None] = []
    listener = KeyboardListener(lambda _trigger, _command: None, on_suggestions=states.append)
    listener.reload({}, [TriggerSuggestion(";em", "Email")])

    listener._on_press(typed(";"))
    listener._on_press(typed("e"))
    assert states[-1] is not None

    listener._on_click(0, 0, None, True)
    assert states[-1] is None

    listener._on_press(typed(";"))
    listener._on_press(typed("e"))
    assert states[-1] is not None
    listener.set_paused(True)
    assert states[-1] is None
