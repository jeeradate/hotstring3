"""Cross-process signalling with Windows named events.

The background listener process owns three auto-reset events.  The UI process
(and a second application launch) can set them to ask the listener to open the
UI, reload triggers or quit -- without any network socket or polling delay.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

from . import config

log = logging.getLogger(__name__)

EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:  # pragma: no cover - Windows only
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.OpenEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:  # pragma: no cover
    _kernel32 = None


def signal(event_name: str, retries: int = 10) -> bool:
    """Set a named event, waiting briefly in case the listener is still starting."""
    if not _IS_WINDOWS or _kernel32 is None:
        return False

    for _ in range(retries):
        handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, event_name)
        if handle:
            try:
                _kernel32.SetEvent(handle)
                return True
            finally:
                _kernel32.CloseHandle(handle)
        time.sleep(0.1)

    log.warning("Could not signal event %s", event_name)
    return False


def signal_show_ui() -> bool:
    """Ask the running instance to show its management window."""
    return signal(config.EVENT_SHOW_UI)


def signal_reload() -> bool:
    """Ask the running instance to reload triggers and settings from disk."""
    return signal(config.EVENT_RELOAD)


def signal_quit() -> bool:
    """Ask the running instance to exit."""
    return signal(config.EVENT_QUIT)


class SignalHub:
    """Owns the named events and dispatches them to callbacks on a worker thread."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handles: dict[int, tuple[str, wintypes.HANDLE]] = {}

    # -- lifecycle ----------------------------------------------------------
    def start(
        self,
        *,
        on_show_ui: Callable[[], None],
        on_reload: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        """Create the events and start dispatching them."""
        if not _IS_WINDOWS or _kernel32 is None:
            log.warning("Cross-process signalling is only available on Windows.")
            return

        events = {
            config.EVENT_SHOW_UI: on_show_ui,
            config.EVENT_RELOAD: on_reload,
            config.EVENT_QUIT: on_quit,
        }
        self._callbacks = {}
        for index, (name, callback) in enumerate(events.items()):
            handle = _kernel32.CreateEventW(None, False, False, name)
            if not handle:
                log.error("Could not create named event %s", name)
                self.close()
                return
            self._handles[WAIT_OBJECT_0 + index] = (name, handle)
            self._callbacks[WAIT_OBJECT_0 + index] = callback

        self._thread = threading.Thread(target=self._loop, name="hotstring3-signals", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        assert _kernel32 is not None
        handles = (wintypes.HANDLE * len(self._handles))(*[handle for _, handle in self._handles.values()])
        while not self._stop.is_set():
            result = _kernel32.WaitForMultipleObjects(
                len(self._handles), handles, False, 500
            )
            if result == WAIT_TIMEOUT:
                continue
            callback = self._callbacks.get(int(result))
            if callback is None:
                continue
            try:
                callback()
            except Exception:  # noqa: BLE001 - signal handling must not die
                log.exception("Signal handler failed")

    def close(self) -> None:
        """Stop the dispatcher and release the named events."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        if _IS_WINDOWS and _kernel32 is not None:
            for _, handle in self._handles.values():
                _kernel32.CloseHandle(handle)
        self._handles.clear()
