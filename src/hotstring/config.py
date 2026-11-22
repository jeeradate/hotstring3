"""Application-wide constants, paths, persisted settings and logging setup."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "HotString"
APP_VERSION = "1.0.0"

#: Root folder for logs, settings and generated icons.
APP_DIR = Path(
    os.environ.get(
        "HOTSTRING_APP_DIR",
        Path(os.environ.get("APPDATA", Path.home())) / APP_NAME,
    )
)

#: Folder that holds the SQLite database (created on demand).
DB_DIR = Path(os.environ.get("HOTSTRING_DB_DIR", r"D:\hotbuff"))

#: SQLite database file.  Override with the ``HOTSTRING_DB`` environment variable.
DB_PATH = Path(os.environ.get("HOTSTRING_DB", DB_DIR / "hotstring.db"))

#: Rotating log file location.
LOG_PATH = Path(os.environ.get("HOTSTRING_LOG", APP_DIR / "hotstring.log"))

#: Persisted runtime settings (pause state and first-run bookkeeping).
SETTINGS_PATH = Path(os.environ.get("HOTSTRING_SETTINGS", APP_DIR / "settings.json"))

#: Generated tray / window icon.
ICON_PATH = APP_DIR / "hotstring.png"

MIN_TRIGGER_LENGTH = 2
MAX_TRIGGER_LENGTH = 8

#: Number of characters kept in the rolling keyboard buffer.
BUFFER_SIZE = 8

#: Valid first characters of a Command.
COMMAND_PREFIXES: dict[str, str] = {
    "t": "type",
    "s": "powershell",
    "a": "action",
    "r": "startup",
}

#: Windows objects used for single-instance detection and cross-process signals.
MUTEX_NAME = r"Local\HotString.SingleInstance"
EVENT_SHOW_UI = r"Local\HotString.ShowUI"
EVENT_RELOAD = r"Local\HotString.Reload"
EVENT_QUIT = r"Local\HotString.Quit"

#: UI window geometry.
WINDOW_SIZE = (1100, 780)

DEFAULT_SETTINGS: dict[str, Any] = {
    "paused": False,
}

_logging_configured = False


def ensure_dirs() -> None:
    """Create the application data and database directories if they are missing."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure rotating file logging (and a console handler when one exists).

    Calling this function more than once is harmless; handlers are only attached
    on the first call so that forked UI windows do not duplicate log lines.
    """
    global _logging_configured
    if _logging_configured:
        return

    ensure_dirs()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)

    # A console handler is only useful when a real console is attached.
    if sys.stderr is not None and sys.stderr.isatty():
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    _logging_configured = True
    logging.getLogger(__name__).info("Logging initialised at %s", LOG_PATH)


def load_settings() -> dict[str, Any]:
    """Return persisted settings merged over :data:`DEFAULT_SETTINGS`."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_PATH.exists():
            with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                settings.update(data)
    except (OSError, ValueError) as exc:  # corrupted settings must never break startup
        logging.getLogger(__name__).warning("Could not read settings: %s", exc)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    """Persist ``settings`` as pretty-printed JSON."""
    ensure_dirs()
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    tmp_path = SETTINGS_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
    tmp_path.replace(SETTINGS_PATH)


def is_paused() -> bool:
    """Return whether the keyboard listener is currently paused."""
    return bool(load_settings().get("paused", False))


def set_paused(paused: bool) -> None:
    """Persist the paused flag."""
    settings = load_settings()
    settings["paused"] = bool(paused)
    save_settings(settings)
