"""Tests for the pure trigger-prefix suggestion lookup."""

from __future__ import annotations

from hotstring3.suggestions import SuggestionIndex, TriggerSuggestion


def make_index(*items: TriggerSuggestion, limit: int = 6) -> SuggestionIndex:
    return SuggestionIndex(items, limit=limit)


def test_no_suggestions_below_two_characters() -> None:
    index = make_index(TriggerSuggestion(";em", "Email"))
    assert index.for_buffer("") is None
    assert index.for_buffer(";") is None
    assert index.for_buffer("hello;") is None


def test_suggestions_appear_at_two_characters() -> None:
    index = make_index(TriggerSuggestion(";em", "Email"))
    state = index.for_buffer(";e")
    assert state is not None
    assert state.prefix == ";e"
    assert [item.trigger for item in state.items] == [";em"]


def test_prefix_is_found_at_the_end_of_arbitrary_text() -> None:
    index = make_index(TriggerSuggestion(";email", "Work email"))
    state = index.for_buffer("please type ;em")
    assert state is not None
    assert state.prefix == ";em"


def test_longer_prefix_filters_the_list() -> None:
    index = make_index(
        TriggerSuggestion(";email", "Work email"),
        TriggerSuggestion(";em", "Personal email"),
        TriggerSuggestion(";np", "Notepad"),
    )
    broad = index.for_buffer(";e")
    assert broad is not None
    assert [item.trigger for item in broad.items] == [";em", ";email"]

    narrow = index.for_buffer(";ema")
    assert narrow is not None
    assert narrow.prefix == ";ema"
    assert [item.trigger for item in narrow.items] == [";email"]


def test_no_state_when_the_typed_text_matches_nothing() -> None:
    index = make_index(TriggerSuggestion(";em", "Email"))
    assert index.for_buffer(";ex") is None
    assert index.for_buffer("hello") is None


def test_lookup_is_case_sensitive() -> None:
    index = make_index(TriggerSuggestion(";EM", "Upper"))
    assert index.for_buffer(";em") is None
    assert index.for_buffer(";EM") is not None


def test_limit_is_applied() -> None:
    index = make_index(
        *(TriggerSuggestion(f";e{number}", str(number)) for number in range(8)),
        limit=3,
    )
    state = index.for_buffer(";e")
    assert state is not None
    assert len(state.items) == 3


def test_subtitle_prefers_description_then_command() -> None:
    described = TriggerSuggestion(";em", "Email", "tme@example.com")
    undescribed = TriggerSuggestion(";np", "", "sStart-Process notepad")
    assert described.subtitle == "Email"
    assert undescribed.subtitle == "sStart-Process notepad"


def test_empty_index_returns_nothing() -> None:
    index = make_index()
    assert len(index) == 0
    assert index.prefix_for(";em") is None
    assert index.for_buffer(";e") is None
