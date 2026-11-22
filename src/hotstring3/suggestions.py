"""Pure trigger-prefix suggestion lookup.

This module knows nothing about SQLite, keyboard hooks or windows: the
application builds a :class:`SuggestionIndex` from enabled HotStrings, the
listener feeds it the rolling buffer, and the popup renders the resulting
:class:`SuggestionState`.  Keeping the lookup pure makes it easy to test.

The popup starts once the tail of the buffer is at least
:data:`~hotstring3.config.SUGGESTION_MIN_PREFIX` characters **and** is a prefix
of at least one enabled trigger.  Longer prefixes win, so typing ``;em``
narrows the list shown for ``;e``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import config


@dataclass(frozen=True, slots=True)
class TriggerSuggestion:
    """The display data for one enabled HotString3 suggestion."""

    trigger: str
    description: str = ""
    command: str = ""

    @property
    def subtitle(self) -> str:
        """A useful second line: the description, falling back to the command."""
        return self.description.strip() or self.command.strip() or "—"


@dataclass(frozen=True, slots=True)
class SuggestionState:
    """The popup contents for the current prefix."""

    prefix: str
    items: tuple[TriggerSuggestion, ...]


class SuggestionIndex:
    """An immutable, case-sensitive index of enabled triggers.

    Args:
        items: Enabled HotStrings to offer.
        limit: Maximum number of rows returned for one prefix.
    """

    def __init__(
        self,
        items: Iterable[TriggerSuggestion] = (),
        *,
        limit: int = config.SUGGESTION_LIMIT,
    ) -> None:
        self._items = tuple(sorted(items, key=lambda item: (len(item.trigger), item.trigger)))
        self._limit = max(1, limit)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> tuple[TriggerSuggestion, ...]:
        """All indexed suggestions in display order."""
        return self._items

    def prefix_for(self, buffer: str) -> str | None:
        """Return the longest buffer suffix that prefixes a known trigger.

        Scanning from the longest suffix means a fully typed trigger is found
        before a shorter prefix; the listener uses an exact match first and only
        then asks for suggestions.
        """
        if len(buffer) < config.SUGGESTION_MIN_PREFIX:
            return None

        for length in range(len(buffer), config.SUGGESTION_MIN_PREFIX - 1, -1):
            suffix = buffer[-length:]
            if any(item.trigger.startswith(suffix) for item in self._items):
                return suffix
        return None

    def matches(self, prefix: str | None) -> tuple[TriggerSuggestion, ...]:
        """Return enabled triggers starting with ``prefix`` (case-sensitive)."""
        if not prefix or len(prefix) < config.SUGGESTION_MIN_PREFIX:
            return ()
        found = [item for item in self._items if item.trigger.startswith(prefix)]
        return tuple(found[: self._limit])

    def for_buffer(self, buffer: str) -> SuggestionState | None:
        """Return the popup state for ``buffer``, or ``None`` to hide it."""
        prefix = self.prefix_for(buffer)
        if prefix is None:
            return None
        items = self.matches(prefix)
        if not items:
            return None
        return SuggestionState(prefix=prefix, items=items)
