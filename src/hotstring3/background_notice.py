"""Non-blocking startup notification.

The listener starts in the background without opening its main window, so a
small always-on-top toast confirms that Hotkeys are active.  It runs on its own
daemon thread, never blocks startup, and dismisses itself after three seconds.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from . import config

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_BG = "#0f172a"
_FG = "#f8fafc"
_ACCENT = "#3b82f6"
_PADDING = 18
_MARGIN = 24


class BackgroundNotice:
    """Thread-safe owner of the startup toast window.

    Call :meth:`show` once during startup and :meth:`close` during shutdown.
    If Tk is unavailable (headless or disabled with ``HOTSTRING3_NO_POPUP=1``)
    the notice quietly becomes a no-op.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._unavailable = False

    def show(self, message: str, duration: float = config.STARTUP_NOTICE_SECONDS) -> None:
        """Display ``message`` for ``duration`` seconds without blocking."""
        if not _IS_WINDOWS or self._unavailable or config.get_env("NO_POPUP") == "1":
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(message, max(0.5, float(duration))),
                name="hotstring3-notice",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        """Dismiss the toast and wait briefly for its thread to finish."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self, message: str, duration: float) -> None:  # pragma: no cover - desktop only
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            log.warning("Startup notice disabled (Tk unavailable): %s", exc)
            self._unavailable = True
            return

        try:
            root = tk.Tk(className="HotString3Notice")
        except Exception as exc:  # noqa: BLE001 - e.g. no desktop session
            log.warning("Startup notice disabled (no window): %s", exc)
            self._unavailable = True
            return

        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-toolwindow", True)  # keep it out of the taskbar
        except Exception:  # noqa: BLE001 - not available everywhere
            pass
        root.configure(bg=_ACCENT)

        panel = tk.Frame(root, bg=_BG, padx=_PADDING, pady=_PADDING - 4)
        panel.pack(fill="both", expand=True, padx=1, pady=1)

        tk.Label(
            panel,
            text="⚡ HotString3",
            bg=_BG,
            fg=_ACCENT,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            panel,
            text=message,
            bg=_BG,
            fg=_FG,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        root.update_idletasks()
        width = max(300, int(root.winfo_reqwidth()) + 4)
        height = int(root.winfo_reqheight()) + 4
        x = max(8, int(root.winfo_screenwidth()) - width - _MARGIN)
        y = max(8, int(root.winfo_screenheight()) - height - _MARGIN - 48)
        root.geometry(f"{width}x{height}+{x}+{y}")

        deadline = time.monotonic() + duration

        def poll() -> None:
            if self._stop.is_set() or time.monotonic() >= deadline:
                try:
                    root.destroy()
                except Exception:  # noqa: BLE001
                    pass
                return
            try:
                root.after(100, poll)
            except Exception:  # noqa: BLE001 - shutting down
                pass

        root.deiconify()
        root.after(100, poll)
        try:
            root.mainloop()
        finally:
            try:
                import tkinter

                if getattr(tkinter, "_default_root", None) is root:
                    tkinter._default_root = None
            except Exception:  # noqa: BLE001
                pass


def show_background_notice(
    message: str = "Hotkey listener is running in the background",
    duration: float = config.STARTUP_NOTICE_SECONDS,
) -> BackgroundNotice:
    """Convenience helper that starts a self-dismissing notice."""
    notice = BackgroundNotice()
    notice.show(message, duration)
    return notice
