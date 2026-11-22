"""Tests for importing HotStrings from the pre-rename build's database.

The old build ran SQLite in WAL mode, so its newest rules can live in the
``-wal`` side file instead of the main database file.  These tests make sure the
import sees them and never overwrites rules that already exist.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hotstring3 import db

SCHEMA = (
    "CREATE TABLE hotstring ("
    "id INTEGER PRIMARY KEY, trigger TEXT, description TEXT, "
    "command TEXT, enabled BOOLEAN)"
)


@pytest.fixture()
def temp_db(tmp_path: Path):
    db.configure(tmp_path / "hotstring3-test.db")
    db.init_db()
    yield
    db.reset_engine()


def make_legacy_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(SCHEMA)
        connection.executemany(
            "INSERT INTO hotstring (trigger, description, command, enabled) VALUES (?, ?, ?, ?)",
            [
                (";ahs", "Open HotString", "aopen", 1),
                (";tok", "OK Thank you", "tIt is OK, thank you", 1),
                (";old", "Disabled", "tStill exported", 0),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_import_adds_missing_rules_and_keeps_existing_ones(temp_db, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    make_legacy_db(legacy)
    db.create_hotstring(";ahs", "Mine", "tKeep me")

    imported = db.import_legacy_hotstrings(legacy)

    assert imported == [";tok", ";old"]
    assert db.get_by_trigger(";tok") is not None
    assert db.get_by_trigger(";tok").enabled is True
    assert db.get_by_trigger(";old").enabled is False
    assert db.get_by_trigger(";ahs").description == "Mine"


def test_import_is_idempotent(temp_db, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    make_legacy_db(legacy)

    assert db.import_legacy_hotstrings(legacy) == [";ahs", ";tok", ";old"]
    assert db.import_legacy_hotstrings(legacy) == []
    assert db.count_hotstrings() == 3


def test_import_skips_invalid_legacy_rules(temp_db, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy)
    try:
        connection.execute(SCHEMA)
        connection.executemany(
            "INSERT INTO hotstring (trigger, description, command, enabled) VALUES (?, ?, ?, ?)",
            [
                (";ok", "Valid", "tHello", 1),
                ("x", "Trigger too short", "tHello", 1),
                (";bad", "Unknown prefix", "nonsense", 1),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    assert db.import_legacy_hotstrings(legacy) == [";ok"]
    assert [item.trigger for item in db.list_hotstrings()] == [";ok"]


def test_import_reads_rules_still_in_the_wal_file(temp_db, tmp_path: Path) -> None:
    """Rows written by the old build can sit in ``hotstring.db-wal`` only."""
    legacy = tmp_path / "legacy.db"
    writer = sqlite3.connect(legacy)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(SCHEMA)
        writer.execute(
            "INSERT INTO hotstring (trigger, description, command, enabled) "
            "VALUES (';tok', 'OK', 'tFine', 1)"
        )
        writer.commit()

        assert db.import_legacy_hotstrings(legacy) == [";tok"]
    finally:
        writer.close()


def test_missing_legacy_database_is_a_no_op(temp_db, tmp_path: Path) -> None:
    assert db.import_legacy_hotstrings(tmp_path / "nope.db") == []
    assert db.list_hotstrings() == []
