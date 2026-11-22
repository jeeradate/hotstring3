"""Tests for the default data/database locations.

The paths are computed at import time, so each case runs in a fresh interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

OVERRIDE_VARS = (
    "HOTSTRING3_DATA_DIR",
    "HOTSTRING3_APP_DIR",
    "HOTSTRING3_DB",
    "HOTSTRING_DATA_DIR",
    "HOTSTRING_APP_DIR",
    "HOTSTRING_DB",
    "HOTSTRING_DB_DIR",
)


def database_path(env: dict[str, str]) -> Path:
    output = subprocess.check_output(
        [sys.executable, "-c", "from hotstring3 import config; print(config.DB_PATH)"],
        env=env,
        text=True,
    )
    return Path(output.strip())


def clean_env(**values: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in OVERRIDE_VARS:
        env.pop(name, None)
    env.update(values)
    return env


def test_database_defaults_to_appdata(tmp_path: Path) -> None:
    appdata = tmp_path / "Roaming"
    path = database_path(clean_env(APPDATA=str(appdata)))
    assert path == appdata / "HotString3" / "hotstring3.db"


def test_data_dir_override_moves_the_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "custom-data"
    path = database_path(clean_env(APPDATA=str(tmp_path / "Roaming"), HOTSTRING_DATA_DIR=str(data_dir)))
    assert path == data_dir / "hotstring3.db"


def test_new_prefix_override_takes_priority(tmp_path: Path) -> None:
    data_dir = tmp_path / "new-prefix-data"
    path = database_path(
        clean_env(
            APPDATA=str(tmp_path / "Roaming"),
            HOTSTRING3_DATA_DIR=str(data_dir),
            HOTSTRING_DATA_DIR=str(tmp_path / "legacy-data"),
        )
    )
    assert path == data_dir / "hotstring3.db"


def test_explicit_database_path_wins(tmp_path: Path) -> None:
    explicit = tmp_path / "elsewhere" / "rules.db"
    path = database_path(
        clean_env(
            APPDATA=str(tmp_path / "Roaming"),
            HOTSTRING_DATA_DIR=str(tmp_path / "custom-data"),
            HOTSTRING_DB=str(explicit),
        )
    )
    assert path == explicit
