"""A small, non-activating popup that lists matching triggers.

The popup runs its own Tk event loop on a daemon thread.  The listener and
application only enqueue :meth:`SuggestionPopup.show` / :meth:`SuggestionPopup.hide`
calls, so they never touch Tk from the wrong thread.

On Windows the window is created with ``WS_EX_NOACTIVATE`` and shown with
``SW_SHOWNOACTIVATE``: typing continues in the application underneath and the
popup never takes keyboard focus.  It is positioned below the text caret when
the target application reports one, otherwise below the mouse pointer.
"""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
from ctypes import wintypes
from typing import Any

from .suggestions import SuggestionState, TriggerCategory, TriggerSuggestion

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Window styles / placement flags used to show the popup without activation.
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SW_SHOWNOACTIVATE = 4
_GA_ROOT = 2

# Monitor placement flags.
_MONITOR_DEFAULTTONEAREST = 2

_BG = "#ffffff"
_BORDER = "#cbd5e1"
_HEADER_BG = "#eef4ff"
_HEADER_FG = "#475569"
_TRIGGER_FG = "#1d4ed8"
_DESC_FG = "#334155"

#: Popup geometry.  Long lists flow into extra columns instead of being cut off.
_MIN_WIDTH = 380
_COLUMN_WIDTH = 320
_MAX_ROWS_PER_COLUMN = 16
_MAX_COLUMNS = 5
_DESCRIPTION_LIMIT = 60


if _IS_WINDOWS:  # pragma: no cover - exercised by the desktop smoke test
    class _GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _USER32.GetForegroundWindow.restype = wintypes.HWND
    _USER32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _USER32.GetGUIThreadInfo.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(_GUITHREADINFO),
    ]
    _USER32.GetGUIThreadInfo.restype = wintypes.BOOL
    _USER32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _USER32.ClientToScreen.restype = wintypes.BOOL
    _USER32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _USER32.GetCursorPos.restype = wintypes.BOOL
    _USER32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    _USER32.MonitorFromPoint.restype = wintypes.HMONITOR
    _USER32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    _USER32.GetMonitorInfoW.restype = wintypes.BOOL
    _USER32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _USER32.GetAncestor.restype = wintypes.HWND
    _USER32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.GetWindowLongW.restype = ctypes.c_long
    _USER32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _USER32.SetWindowLongW.restype = ctypes.c_long
    _USER32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _USER32.SetWindowPos.restype = wintypes.BOOL
    _USER32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _USER32.ShowWindow.restype = wintypes.BOOL
else:  # pragma: no cover
    _USER32 = None


def _caret_point() -> tuple[int, int]:
    """Return screen coordinates just below the caret, or the mouse pointer."""
    if _USER32 is None:
        return 200, 200
    try:
        foreground = _USER32.GetForegroundWindow()
        thread_id = _USER32.GetWindowThreadProcessId(foreground, None)
        if thread_id:
            info = _GUITHREADINFO()
            info.cbSize = ctypes.sizeof(_GUITHREADINFO)
            if _USER32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndCaret:
                point = wintypes.POINT(info.rcCaret.left, info.rcCaret.bottom)
                if _USER32.ClientToScreen(info.hwndCaret, ctypes.byref(point)):
                    return int(point.x), int(point.y)

        point = wintypes.POINT()
        _USER32.GetCursorPos(ctypes.byref(point))
        return int(point.x) + 14, int(point.y) + 20
    except Exception:  # pragma: no cover - best effort
        log.debug("Could not determine the caret position", exc_info=True)
        return 200, 200


def _clamp_position(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """Keep the popup on the caret's monitor, flipping above near the bottom edge."""
    if _USER32 is None:
        return max(8, x), max(8, y)

    monitor = _USER32.MonitorFromPoint(wintypes.POINT(x, y), _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not monitor or not _USER32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return max(8, x), max(8, y)

    left, top = info.rcWork.left, info.rcWork.top
    right, bottom = info.rcWork.right, info.rcWork.bottom
    max_x = max(left + 8, right - width - 8)
    x = min(max(x, left + 8), max_x)

    if y + height > bottom - 8:
        y -= height + 28  # open above the caret instead of off-screen
    max_y = max(top + 8, bottom - height - 8)
    y = min(max(y, top + 8), max_y)
    return x, y


def _root_hwnd(widget: Any) -> int:
    """Return the wrapper HWND for a Tk toplevel (Tk exposes its child)."""
    assert _USER32 is not None
    child = int(widget.winfo_id())
    root = _USER32.GetAncestor(child, _GA_ROOT)
    return int(root or child)


def _make_non_activating(hwnd: int) -> None:
    """Add ``WS_EX_NOACTIVATE`` so the popup can never take keyboard focus."""
    assert _USER32 is not None
    style = _USER32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    _USER32.SetWindowLongW(
        hwnd,
        _GWL_EXSTYLE,
        style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST,
    )


def _place_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    assert _USER32 is not None
    _USER32.SetWindowPos(
        hwnd,
        ctypes.c_void_p(-1),  # HWND_TOPMOST
        x,
        y,
        width,
        height,
        _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
    )
    _USER32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)


def _truncate(text: str, limit: int = 52) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class SuggestionPopup:
    """Thread-safe façade around the Tk suggestion window.

    All methods are safe to call from the listener thread.  If Tk is missing or
    the environment is headless, the popup quietly becomes a no-op.
    """

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[tuple[str, SuggestionState | None]] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._root: Any = None
        self._rows: Any = None
        self._header: Any = None
        self._hwnd = 0
        self._visible = False
        self._unavailable = False
        self._closed = False

    # -- public API ---------------------------------------------------------
    def show(self, state: SuggestionState) -> None:
        """Render ``state`` (or update the existing popup)."""
        if self._closed or self._unavailable or (not state.items and not state.categories):
            return
        self._ensure_thread()
        if self._thread is not None:
            self._queue.put(("show", state))

    def hide(self) -> None:
        """Hide the popup if it is visible."""
        if not self._closed and self._thread is not None:
            self._queue.put(("hide", None))

    def close(self) -> None:
        """Destroy the popup and stop its thread (used at application exit)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is None:
            return
        self._queue.put(("close", None))
        thread.join(timeout=2.5)

    # -- Tk thread ----------------------------------------------------------
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None or self._closed or self._unavailable:
                return
            if not _IS_WINDOWS or os.environ.get("HOTSTRING_NO_POPUP") == "1":
                self._unavailable = True
                return
            self._thread = threading.Thread(
                target=self._run, name="hotstring3-suggestions", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:  # pragma: no cover - requires a desktop session
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            log.warning("Suggestion popup disabled (Tk unavailable): %s", exc)
            self._unavailable = True
            return

        try:
            root = tk.Tk(className="HotString3Suggestions")
        except Exception as exc:  # noqa: BLE001 - e.g. no display
            log.warning("Suggestion popup disabled (no window): %s", exc)
            self._unavailable = True
            return

        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=_BORDER)
        root.bind_all("<Button-1>", self._on_popup_click, add="+")

        panel = tk.Frame(
            root, bg=_BG, bd=0, highlightthickness=1, highlightbackground=_BORDER
        )
        panel.pack(fill="both", expand=True)

        self._header = tk.Label(
            panel,
            text="HotString3 suggestions",
            bg=_HEADER_BG,
            fg=_HEADER_FG,
            anchor="w",
            padx=12,
            pady=6,
            font=("Segoe UI", 9),
        )
        self._header.pack(fill="x")

        self._rows = tk.Frame(panel, bg=_BG)
        self._rows.pack(fill="both", expand=True)

        self._root = root
        self._hwnd = _root_hwnd(root)
        _make_non_activating(self._hwnd)

        root.after(20, self._poll)
        log.debug("Suggestion popup window created")
        try:
            root.mainloop()
        finally:
            # Tk objects must be released on the thread that created them, and
            # the implicit default root must not linger into interpreter exit.
            self._root = None
            self._rows = None
            self._header = None
            self._visible = False
            try:
                import tkinter

                if getattr(tkinter, "_default_root", None) is root:
                    tkinter._default_root = None
            except Exception:  # noqa: BLE001
                pass

    def _poll(self) -> None:  # pragma: no cover - Tk thread
        root = self._root
        if root is None:
            return

        pending: tuple[str, SuggestionState | None] | None = None
        while True:
            try:
                command, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if command == "close":
                self._destroy()
                return
            pending = (command, payload)

        if pending is not None:
            if pending[0] == "show" and pending[1] is not None:
                self._render(pending[1])
            else:
                self._hide()

        try:
            root.after(25, self._poll)
        except Exception:  # noqa: BLE001 - shutting down
            pass

    def _render(self, state: SuggestionState) -> None:  # pragma: no cover - Tk thread
        """Render stage 1 (categories) or stage 2 (trigger + description).

        Nothing is clipped: when the entries do not fit in one column the
        popup grows additional columns, up to :data:`_MAX_COLUMNS`.
        """
        root = self._root
        if root is None:
            return

        import tkinter as tk

        assert self._rows is not None and self._header is not None
        for child in self._rows.winfo_children():
            child.destroy()

        is_categories = state.is_category_stage
        if is_categories:
            self._header.configure(text=f'HotStrings starting with "{state.prefix}"')
        else:
            self._header.configure(text=f'Suggestions for "{state.prefix}"')

        total = len(state.categories) if is_categories else len(state.items)
        per_column = min(_MAX_ROWS_PER_COLUMN, max(1, total))
        columns = -(-total // per_column)
        while columns > _MAX_COLUMNS:
            per_column += 1
            columns = -(-total // per_column)

        grid = tk.Frame(self._rows, bg=_BG)
        grid.pack(fill="both", expand=True)
        for index in range(columns):
            start = index * per_column
            if index:
                tk.Frame(grid, bg=_BORDER, width=1).pack(side="left", fill="y")
            column = tk.Frame(grid, bg=_BG)
            column.pack(side="left", anchor="n", fill="y")
            if is_categories:
                for category in state.categories[start : start + per_column]:
                    self._add_category_row(column, category)
            else:
                for item in state.items[start : start + per_column]:
                    self._add_item_row(column, item)

        width = max(_MIN_WIDTH, columns * _COLUMN_WIDTH)
        root.update_idletasks()
        height = max(60, int(root.winfo_reqheight()))
        x, y = _caret_point()
        x, y = _clamp_position(x, y, width, height)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.update_idletasks()

        if not self._visible:
            self._visible = True
            try:
                root.deiconify()
            except Exception:  # noqa: BLE001
                pass
        _place_window(self._hwnd, x, y, width, height)

    def _add_item_row(
        self, parent: Any, item: TriggerSuggestion
    ) -> None:  # pragma: no cover - Tk thread
        """Add one stage-2 row: the trigger and its description only."""
        import tkinter as tk

        row = tk.Frame(parent, bg=_BG, padx=12, pady=7)
        row.pack(fill="x")

        trigger = tk.Label(
            row,
            text=item.trigger,
            bg=_BG,
            fg=_TRIGGER_FG,
            font=("Consolas", 10, "bold"),
            width=9,
            anchor="w",
        )
        trigger.pack(side="left")
        description = tk.Label(
            row,
            text=_truncate(item.display_description, _DESCRIPTION_LIMIT),
            bg=_BG,
            fg=_DESC_FG,
            font=("Segoe UI", 10),
            anchor="w",
        )
        description.pack(side="left", fill="x", expand=True)

    def _add_category_row(
        self, parent: Any, category: TriggerCategory
    ) -> None:  # pragma: no cover - Tk thread
        """Add one stage-1 row: a second-character prefix and its rule count."""
        import tkinter as tk

        row = tk.Frame(parent, bg=_BG, padx=12, pady=7)
        row.pack(fill="x")

        prefix = tk.Label(
            row,
            text=category.prefix,
            bg=_BG,
            fg=_TRIGGER_FG,
            font=("Consolas", 10, "bold"),
            width=4,
            anchor="w",
        )
        prefix.pack(side="left")
        count = tk.Label(
            row,
            text=f"{category.count} rule{'s' if category.count != 1 else ''}",
            bg=_BG,
            fg=_DESC_FG,
            font=("Segoe UI", 9),
            anchor="w",
        )
        count.pack(side="left", fill="x", expand=True)

    def _hide(self) -> None:  # pragma: no cover - Tk thread
        if not self._visible or self._root is None:
            return
        try:
            self._root.withdraw()
        except Exception:  # noqa: BLE001
            pass
        self._visible = False

    def _on_popup_click(self, _event: Any = None) -> None:  # pragma: no cover - Tk thread
        self._hide()

    def _destroy(self) -> None:  # pragma: no cover - Tk thread
        root = self._root
        self._root = None
        self._visible = False
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._rows = None
        self._header = None
