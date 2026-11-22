"""System tray icon and menu."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from . import config

log = logging.getLogger(__name__)

TITLE = "HotString"


def create_icon_image(size: int = 64) -> Image.Image:
    """Draw the HotString tray icon (a blue rounded square with ``HS``)."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (2, 2, size - 3, size - 3),
        radius=max(6, size // 5),
        fill=(37, 99, 235, 255),
        outline=(29, 78, 216, 255),
        width=max(1, size // 32),
    )
    try:
        font = ImageFont.load_default(size=int(size * 0.42))
    except TypeError:  # pragma: no cover - very old Pillow
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), "HS", fill=(255, 255, 255, 255), font=font, anchor="mm")
    return image


def ensure_icon_file() -> str:
    """Create (once) and return the path of a PNG version of the app icon."""
    try:
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        if not config.ICON_PATH.exists():
            create_icon_image(256).save(config.ICON_PATH, format="PNG")
        return str(config.ICON_PATH)
    except OSError as exc:
        log.warning("Could not write the application icon: %s", exc)
        return ""


class TrayIcon:
    """Windows notification-area icon with a HotString menu.

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
                "HotString",
                create_icon_image(),
                "HotString — type less, do more",
                self._build_menu(),
            )
        except Exception:  # noqa: BLE001 - a tray failure must not stop the listener
            log.exception("Could not create the tray icon")
            return

        self._thread = threading.Thread(target=self._run, name="hotstring-tray", daemon=True)
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
            pystray.MenuItem("Open HotString", lambda: self._safe(self._on_open), default=True),
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
