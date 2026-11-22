"""SQLite persistence layer built on SQLModel.

The database file defaults to ``%APPDATA%\\HotString3\\hotstring3.db`` and is
shared between the background listener process and the UI process.  WAL mode
plus a busy timeout keep concurrent reads and writes safe.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from . import config
from .executor import parse_command
from .models import HotString, validate_trigger

log = logging.getLogger(__name__)

_engine: Engine | None = None
_engine_path: Path | None = None
_configured_path: Path = config.DB_PATH


def configure(db_path: Path | str) -> None:
    """Point the persistence layer at ``db_path`` (mainly used by tests)."""
    global _configured_path
    path = Path(db_path)
    if path != _configured_path:
        reset_engine()
    _configured_path = path


def current_db_path() -> Path:
    """Return the database file currently in use."""
    return _configured_path


def get_engine() -> Engine:
    """Return (and lazily create) the SQLAlchemy engine for the configured database."""
    global _engine, _engine_path

    path = _configured_path
    if _engine is not None and _engine_path == path:
        return _engine

    reset_engine()
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    _engine = engine
    _engine_path = path
    return engine


def reset_engine() -> None:
    """Dispose the current engine so a different database file can be opened."""
    global _engine, _engine_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_path = None


def init_db(db_path: Path | str | None = None) -> None:
    """Create the application directories, database file and tables."""
    if db_path is not None:
        configure(db_path)
    migrate_legacy_database()
    SQLModel.metadata.create_all(get_engine())
    import_legacy_hotstrings_once()
    log.info("Database ready at %s", _configured_path)


# ---------------------------------------------------------------------------
# Migration from the pre-rename build (``%APPDATA%\HotString``)
# ---------------------------------------------------------------------------

#: Database file name used by the previous build.
LEGACY_DB_NAME = "hotstring.db"


def legacy_db_path() -> Path:
    """Return the database file of the pre-rename build, if any."""
    return config.LEGACY_APP_DIR / LEGACY_DB_NAME


def _legacy_migration_allowed() -> bool:
    """Only touch real user data: no path overrides and the default database."""
    return config.uses_default_data_dir() and current_db_path() == Path(config.DB_PATH)


def _read_legacy_rows(source: Path) -> list[tuple[str, str, str, bool]]:
    """Read ``trigger, description, command, enabled`` from a legacy database.

    The old build ran SQLite in WAL mode, so rows may still live in the
    ``-wal`` side file.  A normal connection sees them; the read-only fallback
    is used first so an intact old database is never modified.
    """

    query = "SELECT trigger, description, command, enabled FROM hotstring ORDER BY id"

    def read(read_only: bool) -> list[tuple[str, str, str, bool]]:
        if read_only:
            connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(source)
        try:
            return [
                (str(trigger), str(description or ""), str(command), bool(enabled))
                for trigger, description, command, enabled in connection.execute(query)
            ]
        finally:
            connection.close()

    try:
        return read(True)
    except sqlite3.Error:
        return read(False)


def migrate_legacy_database() -> bool:
    """Copy the old build's database when the new one does not exist yet.

    A plain file copy is not enough: the old build used WAL, so uncheckpointed
    rules live in ``hotstring.db-wal``.  SQLite's backup API produces a single
    consistent file instead.  Returns ``True`` when a copy was made.
    """
    source = legacy_db_path()
    target = current_db_path()
    if not _legacy_migration_allowed() or target.exists() or not source.is_file():
        return False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(source)
        try:
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except (OSError, sqlite3.Error) as exc:
        log.warning("Could not copy the legacy database: %s", exc)
        return False

    log.info("Copied the legacy database from %s to %s", source, target)
    return True


def import_legacy_hotstrings(source: Path | None = None) -> list[str]:
    """Import old rules whose trigger is missing from the current database.

    Existing triggers are never modified or deleted; entries that fail today's
    validation are skipped and logged.  Returns the imported triggers.
    """
    path = source if source is not None else legacy_db_path()
    if not path.is_file():
        return []

    try:
        rows = _read_legacy_rows(path)
    except sqlite3.Error as exc:
        log.warning("Could not read the legacy database: %s", exc)
        return []

    imported: list[str] = []
    for trigger, description, command, enabled in rows:
        try:
            if get_by_trigger(trigger) is not None:
                continue
            upsert_hotstring(
                trigger,
                description,
                command,
                enabled,
                update_existing=False,
            )
        except ValueError as exc:
            log.warning("Skipped legacy HotString %r: %s", trigger, exc)
            continue
        imported.append(trigger)

    if imported:
        log.info(
            "Imported %d legacy HotString(s) from %s", len(imported), path
        )
    return imported


def import_legacy_hotstrings_once() -> list[str]:
    """Run the legacy import once per installation and record it in settings."""
    if not _legacy_migration_allowed():
        return []

    settings = config.load_settings()
    if settings.get(config.LEGACY_IMPORT_SETTING):
        return []

    imported = import_legacy_hotstrings()
    if imported or legacy_db_path().is_file():
        settings[config.LEGACY_IMPORT_SETTING] = True
        config.save_settings(settings)
    return imported


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_hotstrings() -> list[HotString]:
    """Return every HotString ordered by creation time."""
    with Session(get_engine(), expire_on_commit=False) as session:
        return list(session.exec(select(HotString).order_by(HotString.id)).all())


def enabled_hotstrings() -> list[HotString]:
    """Return enabled HotStrings (used by the listener and suggestion popup)."""
    with Session(get_engine(), expire_on_commit=False) as session:
        return list(
            session.exec(
                select(HotString)
                .where(HotString.enabled == True)  # noqa: E712
                .order_by(HotString.id)
            ).all()
        )


def count_hotstrings() -> int:
    """Return the total number of configured HotStrings (enabled or not)."""
    with Session(get_engine()) as session:
        return int(session.scalar(select(func.count()).select_from(HotString)) or 0)


def get_hotstring(hotstring_id: int) -> HotString | None:
    """Return one HotString by id, or ``None``."""
    with Session(get_engine(), expire_on_commit=False) as session:
        return session.get(HotString, hotstring_id)


def get_by_trigger(trigger: str) -> HotString | None:
    """Return the HotString with the exact (case-sensitive) trigger."""
    with Session(get_engine(), expire_on_commit=False) as session:
        return session.exec(select(HotString).where(HotString.trigger == trigger)).first()


def create_hotstring(
    trigger: str,
    description: str,
    command: str,
    enabled: bool = True,
) -> HotString:
    """Create and persist a HotString.

    Raises:
        ValueError: If the values are invalid or the trigger already exists.
    """
    item = HotString(
        trigger=validate_trigger(trigger),
        description=description,
        command=command,
        enabled=enabled,
    ).validate()
    with Session(get_engine(), expire_on_commit=False) as session:
        session.add(item)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if "unique" in str(exc.orig).lower():
                raise ValueError(f"A HotString with trigger '{trigger}' already exists.") from exc
            raise
        session.refresh(item)
    log.info("Created HotString %r", trigger)
    return item


@dataclass(frozen=True, slots=True)
class UpsertResult:
    """Outcome of :func:`upsert_hotstring`."""

    item: HotString
    created: bool
    updated: bool


@dataclass(frozen=True, slots=True)
class SeedEntry:
    """One HotString to load through :func:`seed_hotstrings`."""

    trigger: str
    description: str
    command: str
    enabled: bool = True


@dataclass(slots=True)
class SeedResult:
    """Summary of an idempotent seed operation."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Number of entries processed (including skipped ones)."""
        return len(self.created) + len(self.updated) + len(self.unchanged) + len(self.skipped)


def upsert_hotstring(
    trigger: str,
    description: str,
    command: str,
    enabled: bool = True,
    *,
    update_existing: bool = True,
) -> UpsertResult:
    """Insert a HotString, or update it in place when the trigger exists.

    Triggers are the unique key, so loading the same data twice never creates
    duplicates.  Validation is applied before touching the database.

    Args:
        update_existing: When ``False`` an existing trigger is left untouched.

    Raises:
        ValueError: If the trigger or command is invalid.
    """
    validated = validate_trigger(trigger)
    parse_command(command)

    with Session(get_engine(), expire_on_commit=False) as session:
        item = session.exec(select(HotString).where(HotString.trigger == validated)).first()
        if item is None:
            item = HotString(
                trigger=validated,
                description=description,
                command=command,
                enabled=enabled,
            )
            session.add(item)
            created, updated = True, False
        elif update_existing:
            item.description = description
            item.command = command
            item.enabled = enabled
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            created, updated = False, True
        else:
            return UpsertResult(item=item, created=False, updated=False)

        try:
            session.commit()
        except IntegrityError as exc:  # another process inserted it first
            session.rollback()
            if "unique" in str(exc.orig).lower():
                raise ValueError(
                    f"A HotString with trigger '{validated}' already exists."
                ) from exc
            raise
        session.refresh(item)

    if created:
        log.info("Upsert created HotString %r", validated)
    else:
        log.info("Upsert updated HotString %r", validated)
    return UpsertResult(item=item, created=created, updated=updated)


def seed_hotstrings(
    entries: Iterable[SeedEntry],
    *,
    update_existing: bool = False,
) -> SeedResult:
    """Load a collection of HotStrings without duplicating existing triggers.

    Invalid entries are skipped and reported instead of aborting the whole
    load.  By default existing triggers are left as the user edited them; pass
    ``update_existing=True`` to overwrite them with the seed values.

    Callers that load from the UI should signal the listener afterwards (see
    :func:`hotstring3.signals.signal_reload`) so new triggers become active
    immediately.
    """
    result = SeedResult()
    for entry in entries:
        try:
            outcome = upsert_hotstring(
                entry.trigger,
                entry.description,
                entry.command,
                entry.enabled,
                update_existing=update_existing,
            )
        except ValueError as exc:
            result.skipped.append((entry.trigger, str(exc)))
            log.warning("Skipped seed %r: %s", entry.trigger, exc)
            continue

        if outcome.created:
            result.created.append(entry.trigger)
        elif outcome.updated:
            result.updated.append(entry.trigger)
        else:
            result.unchanged.append(entry.trigger)

    log.info(
        "Seeded HotStrings: %d created, %d updated, %d unchanged, %d skipped",
        len(result.created),
        len(result.updated),
        len(result.unchanged),
        len(result.skipped),
    )
    return result


def update_hotstring(
    hotstring_id: int,
    *,
    trigger: str | None = None,
    description: str | None = None,
    command: str | None = None,
    enabled: bool | None = None,
) -> HotString:
    """Update the given fields of a HotString.

    Raises:
        ValueError: If the HotString does not exist, values are invalid or the
            trigger collides with another HotString.
    """
    with Session(get_engine(), expire_on_commit=False) as session:
        item = session.get(HotString, hotstring_id)
        if item is None:
            raise ValueError("HotString not found.")

        if trigger is not None:
            item.trigger = validate_trigger(trigger)
        if description is not None:
            item.description = description
        if command is not None:
            parse_command(command)
            item.command = command
        if enabled is not None:
            item.enabled = enabled
        item.updated_at = datetime.now(timezone.utc)

        try:
            session.add(item)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if "unique" in str(exc.orig).lower():
                raise ValueError(f"A HotString with trigger '{item.trigger}' already exists.") from exc
            raise
        session.refresh(item)

    log.info("Updated HotString %r", item.trigger)
    return item


def delete_hotstring(hotstring_id: int) -> bool:
    """Delete a HotString by id.  Returns ``True`` when a row was removed."""
    with Session(get_engine()) as session:
        item = session.get(HotString, hotstring_id)
        if item is None:
            return False
        trigger = item.trigger
        session.delete(item)
        session.commit()
    log.info("Deleted HotString %r", trigger)
    return True


def enabled_commands() -> dict[str, str]:
    """Return a ``trigger -> command`` mapping of every enabled HotString."""
    return {row.trigger: row.command for row in enabled_hotstrings()}


def startup_commands() -> list[str]:
    """Return enabled commands that should run when HotString starts."""
    commands: list[str] = []
    for item in list_hotstrings():
        if not item.enabled:
            continue
        try:
            parsed = parse_command(item.command)
        except ValueError:
            continue
        if parsed.kind == "startup":
            commands.append(item.command)
    return commands


def has_open_action() -> bool:
    """Return whether any HotString opens the management UI (``aopen``)."""
    for item in list_hotstrings():
        try:
            parsed = parse_command(item.command)
        except ValueError:
            continue
        if parsed.kind == "action" and parsed.payload == "open":
            return True
    return False


def is_first_run() -> bool:
    """First run: the database is empty or no HotString opens the UI."""
    return not list_hotstrings() or not has_open_action()
