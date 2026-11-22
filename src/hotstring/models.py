"""SQLModel data model for HotString rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlmodel import Field, SQLModel

from . import config


def validate_trigger(trigger: str) -> str:
    """Validate a trigger string.

    Triggers are 2-8 characters, contain no whitespace and are compared
    case-sensitively.

    Raises:
        ValueError: If the trigger is invalid.
    """
    if not isinstance(trigger, str) or not trigger:
        raise ValueError("Trigger is required.")
    if len(trigger) < config.MIN_TRIGGER_LENGTH or len(trigger) > config.MAX_TRIGGER_LENGTH:
        raise ValueError(
            f"Trigger must be between {config.MIN_TRIGGER_LENGTH} and "
            f"{config.MAX_TRIGGER_LENGTH} characters long."
        )
    if any(character.isspace() for character in trigger):
        raise ValueError("Trigger must not contain spaces or whitespace.")
    return trigger


def find_suffix_conflicts(trigger: str, other_triggers: Iterable[str]) -> list[str]:
    """Return other triggers that end with ``trigger``.

    Because the listener fires the shortest matching trigger first, a trigger
    that is the suffix of another one can never be reached in practice; the UI
    warns about this.
    """
    return [other for other in other_triggers if other != trigger and other.endswith(trigger)]


class HotString(SQLModel, table=True):
    """A single trigger-to-command binding."""

    __tablename__ = "hotstring"

    id: int | None = Field(default=None, primary_key=True)
    trigger: str = Field(index=True, unique=True)
    description: str = Field(default="")
    command: str
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def validate(self) -> "HotString":
        """Validate this instance's trigger and command.

        SQLModel table models do not run Pydantic model validators on
        construction, so validation is applied explicitly by the persistence
        layer and the UI.

        Raises:
            ValueError: If the trigger or command is invalid.
        """
        from .executor import parse_command

        validate_trigger(self.trigger)
        parse_command(self.command)
        return self
