"""SQLite persistence layer built on SQLModel.

The database file defaults to ``D:\\hotbuff\\hotstring.db`` and is shared between
the background listener process and the UI process.  WAL mode plus a busy
timeout keep concurrent reads and writes safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event
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
    SQLModel.metadata.create_all(get_engine())
    log.info("Database ready at %s", _configured_path)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_hotstrings() -> list[HotString]:
    """Return every HotString ordered by creation time."""
    with Session(get_engine(), expire_on_commit=False) as session:
        return list(session.exec(select(HotString).order_by(HotString.id)).all())


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
    with Session(get_engine()) as session:
        rows = session.exec(select(HotString).where(HotString.enabled == True)).all()  # noqa: E712
        return {row.trigger: row.command for row in rows}


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
