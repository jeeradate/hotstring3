"""Tests for the rolling buffer and suffix matching (no real keyboard involved)."""

from __future__ import annotations

import pytest

from hotstring import config
from hotstring.listener import KeyboardListener, TriggerBuffer


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
