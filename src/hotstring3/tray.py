"""System tray icon and menu."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .icon import load_icon_image

log = logging.getLogger(__name__)

TITLE = "HotString3"


class TrayIcon:
    """Windows notification-area icon with a HotString3 menu.

    All user actions are delegated to callbacks owned by the application, so the
    tray module stays free of business logic.
    """

    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
        is_paused: Callable[[], bool],
        on_toggle_pause: Callable[[], bool],
        is_start_with_windows: Callable[[], bool],
        on_toggle_start_with_windows: Callable[[], bool],
    ) -> None:
        self._on_open = on_open
        self._on_exit = on_exit
        self._is_paused = is_paused
        self._on_toggle_pause = on_toggle_pause
        self._is_start_with_windows = is_start_with_windows
        self._on_toggle_start_with_windows = on_toggle_start_with_windows
        self._icon = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Create the icon and run its message loop on a background thread."""
        try:
            import pystray
        except ImportError as exc:  # pragma: no cover
            log.error("Could not import pystray: %s", exc)
            return

        try:
            self._icon = pystray.Icon(
                "HotString3",
                load_icon_image(64),
                "HotString3 — type less, do more",
                self._build_menu(),
            )
        except Exception:  # noqa: BLE001 - a tray failure must not stop the listener
            log.exception("Could not create the tray icon")
            return

        self._thread = threading.Thread(target=self._run, name="hotstring3-tray", daemon=True)
        self._thread.start()
        log.info("Tray icon started")

    def _run(self) -> None:
        assert self._icon is not None

        def setup(_icon) -> None:  # noqa: ANN001
            self._ready.set()

        try:
            self._icon.run(setup=setup)
        except Exception:  # noqa: BLE001
            log.exception("Tray icon loop failed")

    def stop(self) -> None:
        """Remove the tray icon."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                log.debug("Error while stopping the tray icon", exc_info=True)
            self._icon = None

    # -- menu ---------------------------------------------------------------
    def _build_menu(self):  # noqa: ANN202
        import pystray

        pause_label = "Resume listening" if self._is_paused() else "Pause listening"
        return pystray.Menu(
            pystray.MenuItem("Open HotString3", lambda: self._safe(self._on_open), default=True),
            pystray.MenuItem(pause_label, lambda: self._safe(self._on_toggle_pause, refresh=True)),
            pystray.MenuItem(
                "Start with Windows",
                lambda: self._safe(self._on_toggle_start_with_windows, refresh=True),
                checked=lambda _item: self._is_start_with_windows(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: self._safe(self._on_exit)),
        )

    def _safe(self, callback: Callable[[], object], refresh: bool = False) -> None:
        try:
            callback()
        except Exception:  # noqa: BLE001
            log.exception("Tray action failed")
        if refresh:
            self.refresh_menu()

    def refresh_menu(self) -> None:
        """Rebuild the menu so labels and checkmarks reflect current state."""
        if self._icon is None:
            return
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("Could not refresh the tray menu", exc_info=True)

    def notify(self, message: str, title: str = TITLE) -> None:
        """Show a balloon notification, if the tray icon is ready."""
        if self._icon is None or not self._ready.wait(timeout=1.5):
            return
        try:
            self._icon.notify(message, title)
        except Exception:  # noqa: BLE001 - notifications are best effort
            log.debug("Could not show a tray notification", exc_info=True)
