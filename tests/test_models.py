"""Tests for the SQLModel data model and persistence basics."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session

from hotstring3 import config, db
from hotstring3.models import HotString, find_suffix_conflicts, validate_trigger


@pytest.fixture()
def temp_db(tmp_path: Path):
    db.configure(tmp_path / "hotstring3-test.db")
    db.init_db()
    yield
    db.reset_engine()


# ---------------------------------------------------------------------------
# Trigger validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", [";e", ";em", ";;abc12", "A_b-1+x", ";ไทย"])
def test_valid_triggers(trigger: str) -> None:
    assert validate_trigger(trigger) == trigger


@pytest.mark.parametrize(
    "trigger",
    ["", "a", ";abcdefgh", " ", "a b", "\t\t", "ก ข"],
)
def test_invalid_triggers(trigger: str) -> None:
    with pytest.raises(ValueError):
        validate_trigger(trigger)


def test_trigger_accepts_maximum_length() -> None:
    assert validate_trigger(";1234567") == ";1234567"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_defaults() -> None:
    item = HotString(trigger=";em", description="Email", command="tmyname@example.com")
    assert item.enabled is True
    assert item.id is None
    assert item.created_at is not None
    assert item.updated_at is not None


@pytest.mark.parametrize(
    "command",
    ["", "   ", "xhello", "Hello", "t", "s", "a", "r"],
)
def test_model_rejects_invalid_commands(command: str) -> None:
    with pytest.raises(ValueError):
        HotString(trigger=";xx", description="", command=command).validate()


@pytest.mark.parametrize("trigger", [";", ";;abcdefghi", "a b"])
def test_model_rejects_invalid_triggers(trigger: str) -> None:
    with pytest.raises(ValueError):
        HotString(trigger=trigger, description="", command="tHello").validate()


def test_model_accepts_unicode_and_multiline_commands() -> None:
    item = HotString(
        trigger=";th",
        description="Thai greeting",
        command="tสวัสดีครับ\nขอบคุณ",
    )
    assert item.command.startswith("t")


# ---------------------------------------------------------------------------
# Suffix conflicts
# ---------------------------------------------------------------------------


def test_find_suffix_conflicts() -> None:
    triggers = {";em", ";eml", ";x", "x;em"}
    assert find_suffix_conflicts(";em", triggers) == ["x;em"]
    assert find_suffix_conflicts(";eml", triggers) == []
    assert find_suffix_conflicts(";zz", triggers) == []


def test_find_suffix_conflicts_is_case_sensitive() -> None:
    assert find_suffix_conflicts(";EM", {"x;eml"}) == []
    assert find_suffix_conflicts(";em", {"x;EML"}) == []


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_list_and_delete(temp_db) -> None:
    created = db.create_hotstring(";em", "Email", "tmyname@example.com")
    assert created.id is not None
    assert [item.trigger for item in db.list_hotstrings()] == [";em"]

    assert db.get_by_trigger(";em") is not None
    assert db.get_by_trigger(";EM") is None  # case-sensitive

    assert db.delete_hotstring(created.id) is True
    assert db.list_hotstrings() == []
    assert db.delete_hotstring(created.id) is False


def test_duplicate_trigger_rejected(temp_db) -> None:
    db.create_hotstring(";em", "Email", "tone")
    with pytest.raises(ValueError, match="already exists"):
        db.create_hotstring(";em", "Email again", "ttwo")


def test_invalid_values_rejected(temp_db) -> None:
    with pytest.raises(ValueError):
        db.create_hotstring(";", "Too short", "tHello")
    with pytest.raises(ValueError):
        db.create_hotstring(";ok", "Bad command", "Hello")


def test_update_hotstring(temp_db) -> None:
    item = db.create_hotstring(";em", "Email", "told@example.com")
    assert item.id is not None

    updated = db.update_hotstring(
        item.id,
        trigger=";eml",
        description="Email (work)",
        command="tnew@example.com",
        enabled=False,
    )
    assert updated.trigger == ";eml"
    assert updated.enabled is False
    assert updated.updated_at >= item.created_at

    stored = db.get_by_trigger(";eml")
    assert stored is not None
    assert stored.description == "Email (work)"


def test_update_to_existing_trigger_rejected(temp_db) -> None:
    first = db.create_hotstring(";one", "", "tone")
    db.create_hotstring(";two", "", "ttwo")
    assert first.id is not None
    with pytest.raises(ValueError, match="already exists"):
        db.update_hotstring(first.id, trigger=";two")


def test_update_missing_hotstring_rejected(temp_db) -> None:
    with pytest.raises(ValueError, match="not found"):
        db.update_hotstring(999, trigger=";zz")


def test_enabled_commands_only_returns_enabled(temp_db) -> None:
    db.create_hotstring(";a1", "", "tone", enabled=True)
    db.create_hotstring(";a2", "", "ttwo", enabled=False)
    assert db.enabled_commands() == {";a1": "tone"}
    assert [item.trigger for item in db.enabled_hotstrings()] == [";a1"]


def test_count_hotstrings_includes_disabled(temp_db) -> None:
    assert db.count_hotstrings() == 0
    db.create_hotstring(";a1", "", "tone")
    db.create_hotstring(";a2", "", "ttwo", enabled=False)
    assert db.count_hotstrings() == 2
    db.seed_hotstrings([db.SeedEntry(";a3", "", "tthree")])
    assert db.count_hotstrings() == 3


# ---------------------------------------------------------------------------
# Upsert and idempotent seeding
# ---------------------------------------------------------------------------


def test_upsert_creates_then_updates_without_duplicating(temp_db) -> None:
    first = db.upsert_hotstring(";em", "Email", "tone@example.com")
    assert first.created is True
    assert first.updated is False
    assert first.item.id is not None

    second = db.upsert_hotstring(";em", "Work email", "ttwo@example.com", enabled=False)
    assert second.created is False
    assert second.updated is True
    assert second.item.id == first.item.id
    assert second.item.description == "Work email"
    assert second.item.enabled is False
    assert len(db.list_hotstrings()) == 1


def test_upsert_can_leave_an_existing_trigger_untouched(temp_db) -> None:
    db.create_hotstring(";em", "Mine", "tkeep@example.com")
    result = db.upsert_hotstring(";em", "Seed", "tseed", update_existing=False)
    assert result.created is False
    assert result.updated is False
    stored = db.get_by_trigger(";em")
    assert stored is not None
    assert stored.description == "Mine"


def test_upsert_respects_validation(temp_db) -> None:
    with pytest.raises(ValueError):
        db.upsert_hotstring(";", "Too short", "tHello")
    with pytest.raises(ValueError):
        db.upsert_hotstring(";ok", "Bad command", "nonsense")
    assert db.list_hotstrings() == []


def test_seed_is_idempotent_by_default(temp_db) -> None:
    entries = [
        db.SeedEntry(";em", "Email", "tone@example.com"),
        db.SeedEntry(";np", "Notepad", "sStart-Process notepad"),
    ]
    first = db.seed_hotstrings(entries)
    assert first.created == [";em", ";np"]
    assert first.unchanged == []

    second = db.seed_hotstrings(entries)
    assert second.created == []
    assert second.unchanged == [";em", ";np"]
    assert len(db.list_hotstrings()) == 2


def test_seed_can_update_existing_rules(temp_db) -> None:
    db.create_hotstring(";em", "Old", "told")
    result = db.seed_hotstrings(
        [db.SeedEntry(";em", "New", "tnew")],
        update_existing=True,
    )
    assert result.updated == [";em"]
    stored = db.get_by_trigger(";em")
    assert stored is not None
    assert (stored.description, stored.command) == ("New", "tnew")


def test_seed_skips_invalid_entries_and_keeps_valid_ones(temp_db) -> None:
    result = db.seed_hotstrings(
        [
            db.SeedEntry(";ok", "Valid", "tHello"),
            db.SeedEntry("x", "Bad trigger", "tHello"),
            db.SeedEntry(";bad", "Bad command", "nonsense"),
        ]
    )
    assert result.created == [";ok"]
    assert [trigger for trigger, _message in result.skipped] == ["x", ";bad"]
    assert [item.trigger for item in db.list_hotstrings()] == [";ok"]


def test_startup_commands(temp_db) -> None:
    db.create_hotstring(";r1", "", "rStart-Process notepad")
    db.create_hotstring(";r2", "", "rStart-Process calc", enabled=False)
    db.create_hotstring(";t1", "", "tHello")
    assert db.startup_commands() == ["rStart-Process notepad"]


def test_first_run_detection(temp_db) -> None:
    assert db.is_first_run() is True

    db.create_hotstring(";em", "", "tHello")
    assert db.is_first_run() is True  # no aopen trigger yet

    db.create_hotstring(";hs", "Open HotString", "aopen")
    assert db.is_first_run() is False
    assert db.has_open_action() is True


def test_first_run_when_aopen_is_disabled(temp_db) -> None:
    db.create_hotstring(";hs", "Open HotString", "aopen", enabled=False)
    # An existing (even disabled) aopen rule still counts as configured.
    assert db.has_open_action() is True
    assert db.is_first_run() is False


def test_database_uses_configured_path(temp_db, tmp_path: Path) -> None:
    assert db.current_db_path() == tmp_path / "hotstring3-test.db"
    assert (tmp_path / "hotstring3-test.db").exists()


def test_models_roundtrip_through_session(temp_db) -> None:
    with Session(db.get_engine()) as session:
        session.add(HotString(trigger=";rt", description="Roundtrip", command="tHi"))
        session.commit()

    item = db.get_by_trigger(";rt")
    assert item is not None
    assert item.command == "tHi"
    assert config.MIN_TRIGGER_LENGTH == 2
