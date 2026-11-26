"""Pure trigger-prefix suggestion lookup.

This module knows nothing about SQLite, keyboard hooks or windows: the
application builds a :class:`SuggestionIndex` from enabled HotStrings, the
listener feeds it the rolling buffer, and the popup renders the resulting
:class:`SuggestionState`.  Keeping the lookup pure makes it easy to test.

The popup has two stages:

* **Stage 1** — a single non-alphanumeric leading character (normally ``;``)
  is typed.  :meth:`SuggestionIndex.categories` lists every distinct second
  character found in the triggers that start with it, so the user can see all
  available ``;a``, ``;p``, ``;g`` … groups at once.
* **Stage 2** — two or more characters are typed (``;em``).  The list narrows
  to every trigger starting with that prefix; only the trigger and its
  description are shown.
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

    @property
    def display_description(self) -> str:
        """The text the popup shows next to the trigger.

        The popup deliberately never shows the command/expansion payload, so
        this is the description alone (empty when the user left it blank).
        """
        return self.description.strip()


@dataclass(frozen=True, slots=True)
class TriggerCategory:
    """One stage-1 entry: a second character and how many triggers use it."""

    prefix: str
    count: int


@dataclass(frozen=True, slots=True)
class SuggestionState:
    """The popup contents for the current prefix.

    Exactly one of ``items`` (stage 2) or ``categories`` (stage 1) is filled.
    """

    prefix: str
    items: tuple[TriggerSuggestion, ...] = ()
    categories: tuple[TriggerCategory, ...] = ()

    @property
    def is_category_stage(self) -> bool:
        """Whether this state asks the popup to show the category overview."""
        return bool(self.categories) and not self.items


class SuggestionIndex:
    """An immutable, case-sensitive index of enabled triggers.

    Args:
        items: Enabled HotStrings to offer.
        limit: Safety cap on the number of rows returned for one prefix.
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
        then asks for suggestions.  Only stage-2 prefixes (at least
        :data:`~hotstring3.config.SUGGESTION_MIN_PREFIX` characters) are
        returned; a lone leading character is handled by
        :meth:`category_prefix_for`.
        """
        if len(buffer) < config.SUGGESTION_MIN_PREFIX:
            return None

        for length in range(len(buffer), config.SUGGESTION_MIN_PREFIX - 1, -1):
            suffix = buffer[-length:]
            if any(item.trigger.startswith(suffix) for item in self._items):
                return suffix
        return None

    def category_prefix_for(self, buffer: str) -> str | None:
        """Return a single leading character that opens the stage-1 view.

        Only non-alphanumeric leaders (``;``, ``/``, …) qualify so the popup
        stays quiet while ordinary words are typed.  The character must also
        start at least one enabled trigger.
        """
        if not buffer:
            return None
        character = buffer[-1]
        if character.isalnum() or character.isspace():
            return None
        if any(item.trigger.startswith(character) for item in self._items):
            return character
        return None

    def categories(self, prefix: str) -> tuple[TriggerCategory, ...]:
        """Return every distinct second character under ``prefix``.

        The result is sorted by character so the overview is stable, and each
        entry reports how many triggers belong to that group.
        """
        counts: dict[str, int] = {}
        for item in self._items:
            if len(item.trigger) > len(prefix) and item.trigger.startswith(prefix):
                second = item.trigger[len(prefix)]
                counts[second] = counts.get(second, 0) + 1
        return tuple(
            TriggerCategory(prefix=prefix + second, count=counts[second])
            for second in sorted(counts)
        )

    def matches(self, prefix: str | None) -> tuple[TriggerSuggestion, ...]:
        """Return enabled triggers starting with ``prefix`` (case-sensitive)."""
        if not prefix or len(prefix) < config.SUGGESTION_MIN_PREFIX:
            return ()
        found = [item for item in self._items if item.trigger.startswith(prefix)]
        return tuple(found[: self._limit])

    def for_buffer(self, buffer: str) -> SuggestionState | None:
        """Return the popup state for ``buffer``, or ``None`` to hide it.

        A matching stage-2 prefix wins; otherwise a single qualifying leading
        character produces the stage-1 category overview.
        """
        prefix = self.prefix_for(buffer)
        if prefix is not None:
            items = self.matches(prefix)
            return SuggestionState(prefix=prefix, items=items) if items else None

        category_prefix = self.category_prefix_for(buffer)
        if category_prefix is not None:
            categories = self.categories(category_prefix)
            if categories:
                return SuggestionState(prefix=category_prefix, categories=categories)
        return None
