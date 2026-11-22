"""Global keyboard hook, rolling character buffer and trigger matching.

The matching logic lives in :class:`TriggerBuffer` and is deliberately free of
any keyboard or Windows dependency so it can be unit tested.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections import deque
from typing import Any, Callable, Iterable

from . import config
from .executor import is_input_suppressed, send_backspaces
from .suggestions import SuggestionIndex, SuggestionState, TriggerSuggestion

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

#: Virtual-key codes of the shortcut modifiers: Ctrl, Alt and the Windows keys.
_SHORTCUT_VK = (0x11, 0x12, 0x5B, 0x5C)


def _shortcut_modifier_down() -> bool:
    """Return whether Ctrl, Alt or a Windows key is physically held down.

    The listener ignores characters typed while a shortcut modifier is down
    (``Ctrl+C`` is not text).  Windows can swallow the matching key release --
    when the session is locked, during a UAC prompt or when the hook is
    temporarily removed -- and the tracked modifier state would then block every
    later keystroke.  Checking the real key state lets that recover on the next
    key press.  Shift is deliberately not a shortcut modifier: it changes the
    typed character, so ``;EM`` must still be recorded as uppercase text.
    """
    if not _IS_WINDOWS:
        return True
    try:
        user32 = ctypes.windll.user32
        return any(bool(user32.GetAsyncKeyState(vk) & 0x8000) for vk in _SHORTCUT_VK)
    except Exception:  # noqa: BLE001 - never break the hook on a probe failure
        return True


class TriggerBuffer:
    """A rolling buffer of the last ``capacity`` typed characters."""

    def __init__(self, capacity: int = config.BUFFER_SIZE) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._chars: deque[str] = deque(maxlen=capacity)

    @property
    def text(self) -> str:
        """The current buffer contents as a string."""
        return "".join(self._chars)

    def __len__(self) -> int:
        return len(self._chars)

    def push(self, character: str) -> None:
        """Append one typed character, dropping the oldest when full."""
        if character:
            self._chars.append(character)

    def backspace(self) -> None:
        """Remove the most recent character (no-op when empty)."""
        if self._chars:
            self._chars.pop()

    def clear(self) -> None:
        """Forget everything that was typed."""
        self._chars.clear()

    def match(self, triggers: Iterable[str]) -> str | None:
        """Return the trigger that matches the end of the buffer.

        Comparison is exact and case-sensitive.  When several triggers match,
        the shortest one wins -- it would have fired first while typing anyway.
        """
        text = self.text
        if not text:
            return None
        matches = [trigger for trigger in triggers if trigger and text.endswith(trigger)]
        if not matches:
            return None
        return min(matches, key=len)


def _key_names(*names: str) -> set[Any]:
    """Resolve pynput ``Key`` members by name, ignoring ones missing on this platform."""
    try:
        from pynput.keyboard import Key
    except ImportError:  # pragma: no cover - pynput is a hard dependency on Windows
        return set()
    result: set[Any] = set()
    for name in names:
        value = getattr(Key, name, None)
        if value is not None:
            result.add(value)
    return result


class KeyboardListener:
    """Listen globally for HotString3 triggers and erase them before execution.

    Args:
        on_match: Called with ``(trigger, command)`` after the trigger has been
            erased from the focused application.  Runs on the listener thread;
            keep it fast (the app dispatches execution to a worker thread).
        on_error: Optional callback for user-visible failures (tray notification).
        buffer: Optional custom buffer, mainly for tests.
    """

    def __init__(
        self,
        on_match: Callable[[str, str], None],
        *,
        on_error: Callable[[str], None] | None = None,
        on_suggestions: Callable[[SuggestionState | None], None] | None = None,
        buffer: TriggerBuffer | None = None,
    ) -> None:
        self.buffer = buffer if buffer is not None else TriggerBuffer()
        self._on_match = on_match
        self._on_error = on_error
        self._on_suggestions = on_suggestions
        self._commands: dict[str, str] = {}
        self._suggestions = SuggestionIndex()
        self._lock = threading.RLock()
        self._paused = False
        self._stop = threading.Event()
        self._keyboard_listener: Any = None
        self._mouse_listener: Any = None
        self._focus_thread: threading.Thread | None = None
        self._modifiers: set[Any] = set()
        self._modifier_keys = _key_names(
            "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r"
        )
        self._reset_keys = _key_names(
            "enter", "esc", "tab", "up", "down", "left", "right",
            "home", "end", "page_up", "page_down",
        )
        self._last_window: int | None = None

    # -- configuration ------------------------------------------------------
    def reload(
        self,
        commands: dict[str, str],
        suggestions: Iterable[TriggerSuggestion] | None = None,
    ) -> None:
        """Replace the trigger table and suggestion index.

        Args:
            commands: ``trigger -> command`` mapping used for execution.
            suggestions: Display data for the popup.  Defaults to the triggers
                in ``commands`` with empty descriptions.
        """
        if suggestions is None:
            suggestions = [
                TriggerSuggestion(trigger=trigger, command=command)
                for trigger, command in commands.items()
            ]
        with self._lock:
            self._commands = dict(commands)
            self._suggestions = SuggestionIndex(suggestions)
        log.debug("Loaded %d trigger(s)", len(commands))
        self._notify_suggestions()

    def set_paused(self, paused: bool) -> None:
        """Pause or resume matching (the keyboard hook stays installed)."""
        self._paused = paused
        if paused:
            self.buffer.clear()
            self._hide_suggestions()
        else:
            self._notify_suggestions()

    @property
    def paused(self) -> bool:
        """Whether matching is currently paused."""
        return self._paused

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Install the global keyboard and mouse hooks."""
        if self._keyboard_listener is not None:
            return

        try:
            from pynput import keyboard, mouse
        except ImportError as exc:  # pragma: no cover
            message = f"Could not import pynput: {exc}"
            log.error(message)
            self._report_error(message)
            return

        try:
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._keyboard_listener.start()
            self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()
        except Exception as exc:  # pragma: no cover - depends on the desktop session
            message = f"Could not install the keyboard hook: {exc}"
            log.exception(message)
            for listener in (self._keyboard_listener, self._mouse_listener):
                if listener is not None:
                    try:
                        listener.stop()
                    except Exception:  # noqa: BLE001
                        log.debug("Error while cleaning up a hook", exc_info=True)
            self._keyboard_listener = None
            self._mouse_listener = None
            self._report_error(message)
            return

        if _IS_WINDOWS:
            self._focus_thread = threading.Thread(
                target=self._watch_foreground_window, name="hotstring3-focus", daemon=True
            )
            self._focus_thread.start()

        log.info("Keyboard listener started")

    def stop(self) -> None:
        """Remove the hooks and stop the focus watcher."""
        self._stop.set()
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # noqa: BLE001 - shutdown is best effort
                    log.debug("Error while stopping listener", exc_info=True)
        self._keyboard_listener = None
        self._mouse_listener = None
        if self._focus_thread is not None:
            self._focus_thread.join(timeout=1.5)
            self._focus_thread = None
        self._hide_suggestions()
        log.info("Keyboard listener stopped")

    # -- pynput callbacks ---------------------------------------------------
    def _is_active(self) -> bool:
        return not self._paused and not is_input_suppressed()

    def _on_press(self, key: Any) -> None:
        try:
            if key in self._modifier_keys:
                self._modifiers.add(key)
                self._hide_suggestions()
                return
            if not self._is_active():
                return
            if self._modifiers and not _shortcut_modifier_down():
                # A release was missed while the session was locked or a secure
                # desktop was shown; recover instead of ignoring every key.
                log.info("Clearing stale modifier state")
                self._modifiers.clear()
            if self._modifiers:
                # Ctrl/Alt/Win combinations are shortcuts, not typed text.
                self._hide_suggestions()
                return

            if key in self._reset_keys:
                self.buffer.clear()
                self._hide_suggestions()
                return

            from pynput.keyboard import Key

            if key == Key.backspace:
                self.buffer.backspace()
                self._notify_suggestions()
                return

            character = getattr(key, "char", None)
            if not character or not character.isprintable():
                return

            self.buffer.push(character)
            self._check_trigger()
        except Exception:  # noqa: BLE001 - never let a hook error propagate
            log.exception("Keyboard press handler failed")

    def _on_release(self, key: Any) -> None:
        self._modifiers.discard(key)

    def _on_click(self, *_args: Any, **_kwargs: Any) -> None:
        self.buffer.clear()
        self._hide_suggestions()

    def _check_trigger(self) -> None:
        with self._lock:
            commands = self._commands
            trigger = self.buffer.match(commands.keys())
            command = commands[trigger] if trigger is not None else None

        if trigger is None or command is None:
            self._notify_suggestions()
            return

        self.buffer.clear()
        self._hide_suggestions()
        log.info("Trigger %r matched", trigger)

        try:
            send_backspaces(len(trigger))
        except Exception as exc:  # noqa: BLE001
            log.exception("Could not erase trigger")
            self._report_error(f"Could not erase the typed trigger: {exc}")

        try:
            self._on_match(trigger, command)
        except Exception:  # noqa: BLE001
            log.exception("Trigger handler failed")

    # -- suggestions --------------------------------------------------------
    def _notify_suggestions(self) -> None:
        """Send the current suggestion state to the popup (if subscribed).

        The popup coalesces updates on its own thread, so sending on every
        keystroke keeps filtering responsive without extra complexity here.
        """
        if self._on_suggestions is None:
            return
        with self._lock:
            if self._paused or is_input_suppressed():
                state: SuggestionState | None = None
            else:
                state = self._suggestions.for_buffer(self.buffer.text)

        try:
            self._on_suggestions(state)
        except Exception:  # noqa: BLE001 - popup failures must not break typing
            log.exception("Suggestion callback failed")

    def _hide_suggestions(self) -> None:
        """Hide the popup without clearing the buffer."""
        if self._on_suggestions is None:
            return
        try:
            self._on_suggestions(None)
        except Exception:  # noqa: BLE001
            log.exception("Suggestion callback failed")

    # -- window focus -------------------------------------------------------
    def _watch_foreground_window(self) -> None:
        try:
            user32 = ctypes.windll.user32
        except Exception:  # pragma: no cover
            return
        while not self._stop.is_set():
            try:
                window = int(user32.GetForegroundWindow())
                if self._last_window is not None and window != self._last_window:
                    self.buffer.clear()
                    self._hide_suggestions()
                self._last_window = window
            except Exception:  # noqa: BLE001
                log.debug("Foreground window polling failed", exc_info=True)
            self._stop.wait(0.25)

    def _report_error(self, message: str) -> None:
        if self._on_error is not None:
            try:
                self._on_error(message)
            except Exception:  # noqa: BLE001
                log.exception("Error callback failed")
