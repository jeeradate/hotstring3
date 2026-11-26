"""Application-wide constants, paths, persisted settings and logging setup."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import sys
from pathlib import Path
from typing import Any

APP_NAME = "HotString3"
APP_VERSION = "1.0.0"

#: Product name used by older builds.  It is only referenced while migrating
#: existing data, so renaming the project never silently loses a database.
LEGACY_APP_NAME = "HotString"

def _bundle_root() -> Path:
    """Return the repository root, or the temporary bundle folder when frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


#: Repository root (``pyproject.toml`` lives here) and the bundled icon folder.
PROJECT_ROOT = _bundle_root()
ASSETS_DIR = PROJECT_ROOT / "assets"


def get_env(name: str, default: str | None = None) -> str | None:
    """Return an environment override, preferring the ``HOTSTRING3_`` prefix.

    ``HOTSTRING_*`` variables from earlier builds keep working as aliases so
    existing scripts and tests do not break after the rename.
    """
    value = os.environ.get(f"HOTSTRING3_{name}")
    if not value:
        value = os.environ.get(f"HOTSTRING_{name}")
    return default if not value else value


_USING_DEFAULT_DATA_DIR = not any(
    get_env(name) for name in ("DATA_DIR", "APP_DIR", "DB", "LOG", "SETTINGS")
)

#: Root folder for the database, logs, settings and generated icons.
APP_DIR = Path(
    get_env("DATA_DIR")
    or get_env("APP_DIR")
    or Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
)

#: Backwards-compatible alias that describes the folder's contents.
DATA_DIR = APP_DIR

#: Folder used by the pre-rename build, used only for a one-time migration.
LEGACY_APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / LEGACY_APP_NAME

#: SQLite database file, inside the app data folder by default.
DB_PATH = Path(get_env("DB", str(APP_DIR / "hotstring3.db")) or APP_DIR / "hotstring3.db")

#: Settings key that records the one-time import of rules from the old build.
LEGACY_IMPORT_SETTING = "legacy_import_done"

#: Rotating log file location.
LOG_PATH = Path(get_env("LOG", str(APP_DIR / "hotstring3.log")) or APP_DIR / "hotstring3.log")

#: Persisted runtime settings (pause state and first-run bookkeeping).
SETTINGS_PATH = Path(
    get_env("SETTINGS", str(APP_DIR / "settings.json")) or APP_DIR / "settings.json"
)

#: Generated window / tray icon fallback (the bundled lightning icon wins).
ICON_PATH = APP_DIR / "hotstring3.ico"

MIN_TRIGGER_LENGTH = 2
MAX_TRIGGER_LENGTH = 8

#: Number of characters kept in the rolling keyboard buffer.
BUFFER_SIZE = 8

#: Suggestions appear once the typed prefix reaches this many characters.
SUGGESTION_MIN_PREFIX = MIN_TRIGGER_LENGTH

#: Maximum number of suggestions shown in the popup at once.
SUGGESTION_LIMIT = 6

#: Valid first characters of a Command.
COMMAND_PREFIXES: dict[str, str] = {
    "t": "type",
    "s": "powershell",
    "a": "action",
    "r": "startup",
}

#: Windows objects used for single-instance detection and cross-process signals.
MUTEX_NAME = r"Local\HotString3.SingleInstance"
EVENT_SHOW_UI = r"Local\HotString3.ShowUI"
EVENT_RELOAD = r"Local\HotString3.Reload"
EVENT_QUIT = r"Local\HotString3.Quit"

#: UI window geometry.
WINDOW_SIZE = (1100, 780)

#: Duration of the non-blocking startup background notice.
STARTUP_NOTICE_SECONDS = 3.0

DEFAULT_SETTINGS: dict[str, Any] = {
    "paused": False,
}

_logging_configured = False


def uses_default_data_dir() -> bool:
    """Return whether the default data folder is in use (no path overrides)."""
    return _USING_DEFAULT_DATA_DIR


def _migrate_legacy_data() -> None:
    """Copy the previous build's log and settings on first start.

    Only runs when the default (non-overridden) data folder is used.  Existing
    files are never overwritten, so a failed or interrupted migration can
    safely be retried.  The database is migrated by
    :func:`hotstring3.db.migrate_legacy_database` because it needs a consistent
    SQLite copy (the old build used WAL, so the rows may live in the side file).
    """
    if not _USING_DEFAULT_DATA_DIR or not LEGACY_APP_DIR.is_dir():
        return

    pairs = (
        ("hotstring.log", LOG_PATH),
        ("settings.json", SETTINGS_PATH),
    )
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        copied = False
        for legacy_name, target in pairs:
            source = LEGACY_APP_DIR / legacy_name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
                copied = True
        if copied:
            logging.getLogger(__name__).info(
                "Migrated log and settings from %s to %s", LEGACY_APP_DIR, APP_DIR
            )
    except OSError as exc:  # migration must never prevent the app from starting
        logging.getLogger(__name__).warning("Could not migrate old data: %s", exc)


def ensure_dirs() -> None:
    """Create the application data and database directories if they are missing."""
    _migrate_legacy_data()
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
