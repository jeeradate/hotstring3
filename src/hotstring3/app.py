"""Application startup: single instance, listener, tray and UI process management."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from . import autostart, config, db, signals
from .background_notice import BackgroundNotice
from .executor import CommandExecutor
from .listener import KeyboardListener
from .suggestion_popup import SuggestionPopup
from .suggestions import SuggestionState, TriggerSuggestion
from .tray import TrayIcon

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
_IS_WINDOWS = sys.platform == "win32"


class SingleInstance:
    """Named-mutex based single-instance guard with a lock-file fallback."""

    def __init__(self) -> None:
        self._handle: int | None = None
        self._lock_fd: int | None = None
        self._kernel32 = None

    def acquire(self) -> bool:
        """Return ``True`` when this process is the first instance."""
        if _IS_WINDOWS:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_wchar_p,
            ]
            self._kernel32.CreateMutexW.restype = ctypes.c_void_p
            self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle.restype = ctypes.c_int

            handle = self._kernel32.CreateMutexW(None, False, config.MUTEX_NAME)
            if not handle:
                log.warning("Could not create the single-instance mutex")
                return True  # better to run twice than not at all
            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                self._kernel32.CloseHandle(handle)
                return False
            self._handle = handle
            return True

        # Development fallback for non-Windows systems.
        config.ensure_dirs()
        lock_path = config.APP_DIR / "hotstring3.lock"
        try:
            import fcntl

            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
            self._lock_fd = fd
            return True
        except OSError:
            return True

    def release(self) -> None:
        """Release the mutex or lock file."""
        if self._handle is not None and self._kernel32 is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            finally:
                self._lock_fd = None


class HotString3Application:
    """Owns all long-running parts of HotString3."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._signals = signals.SignalHub()
        self._listener: KeyboardListener | None = None
        self._tray: TrayIcon | None = None
        self._executor: CommandExecutor | None = None
        self._popup = SuggestionPopup()
        self._notice = BackgroundNotice()
        self._ui_process: subprocess.Popen | None = None

    # -- startup ------------------------------------------------------------
    def run(self) -> int:
        """Start the background application and block until exit is requested."""
        config.setup_logging()
        config.ensure_dirs()
        db.init_db()
        log.info("Starting HotString3 %s", config.APP_VERSION)
        autostart.migrate_legacy_entry()

        self._executor = CommandExecutor(
            open_ui=self.open_ui,
            on_error=self._notify_error,
        )

        self._listener = KeyboardListener(
            self._on_trigger,
            on_error=self._notify_error,
            on_suggestions=self._on_suggestions,
        )
        self._reload_listener()
        self._listener.set_paused(config.is_paused())
        self._listener.start()

        self._tray = TrayIcon(
            on_open=self.open_ui,
            on_exit=self.request_exit,
            is_paused=config.is_paused,
            on_toggle_pause=self._toggle_pause,
            is_start_with_windows=autostart.is_enabled,
            on_toggle_start_with_windows=self._toggle_autostart,
        )
        self._tray.start()

        self._signals.start(
            on_show_ui=self.open_ui,
            on_reload=self.reload,
            on_quit=self.request_exit,
        )

        self._executor.run_startup_commands(db.startup_commands())

        if db.is_first_run():
            log.info("First run detected; opening onboarding")
            self.open_ui(onboarding=True)

        log.info("HotString3 is running in the background")
        self._notice.show(
            "Hotkey listener is running in the background",
            config.STARTUP_NOTICE_SECONDS,
        )
        try:
            while not self._stop.wait(0.5):
                if self._ui_process is not None and self._ui_process.poll() is not None:
                    self._ui_process = None
        except KeyboardInterrupt:
            log.info("Interrupted, shutting down")

        self.shutdown()
        return 0

    # -- callbacks ----------------------------------------------------------
    def _on_trigger(self, trigger: str, command: str) -> None:
        log.info("Executing command for trigger %r", trigger)
        assert self._executor is not None
        self._executor.execute_async(command)

    def _on_suggestions(self, state: SuggestionState | None) -> None:
        """Forward listener updates to the popup thread."""
        if state is None:
            self._popup.hide()
        else:
            self._popup.show(state)

    def _reload_listener(self) -> None:
        """Load enabled commands and their display data into the listener."""
        if self._listener is None:
            return
        rows = db.enabled_hotstrings()
        self._listener.reload(
            {row.trigger: row.command for row in rows},
            [
                TriggerSuggestion(
                    trigger=row.trigger,
                    description=row.description,
                    command=row.command,
                )
                for row in rows
            ],
        )

    def _notify_error(self, message: str) -> None:
        log.error(message)
        if self._tray is not None:
            short = message if len(message) <= 180 else message[:177] + "…"
            self._tray.notify(short, "HotString3 error")

    def _toggle_pause(self) -> bool:
        paused = not config.is_paused()
        config.set_paused(paused)
        if self._listener is not None:
            self._listener.set_paused(paused)
        log.info("Listening %s", "paused" if paused else "resumed")
        return paused

    def _toggle_autostart(self) -> bool:
        wanted = not autostart.is_enabled()
        if not autostart.set_enabled(wanted):
            self._notify_error("Could not update the Windows startup entry.")
        return autostart.is_enabled()

    def reload(self) -> None:
        """Reload triggers and settings after the UI changed them."""
        try:
            if self._listener is not None:
                self._reload_listener()
                self._listener.set_paused(config.is_paused())
            if self._tray is not None:
                self._tray.refresh_menu()
            log.info("Triggers reloaded from the database")
        except Exception:  # noqa: BLE001 - reload errors must not stop the app
            log.exception("Could not reload triggers")
            self._notify_error("Could not reload triggers. See the log for details.")

    # -- UI process ---------------------------------------------------------
    def open_ui(self, onboarding: bool = False) -> None:
        """Open the management window in a separate process (no-op if already open)."""
        if self._ui_process is not None and self._ui_process.poll() is None:
            return

        argv = [sys.executable, "-m", "hotstring3", "--ui"]
        if onboarding:
            argv.append("--onboarding")

        creationflags = 0
        if _IS_WINDOWS:
            creationflags = subprocess.CREATE_NO_WINDOW

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        try:
            self._ui_process = subprocess.Popen(  # noqa: S603 - launching our own interpreter
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                env=env,
                cwd=str(Path(__file__).resolve().parents[2])
                if (Path(__file__).resolve().parents[2] / "pyproject.toml").exists()
                else None,
            )
            log.info("Opened UI process (pid %s)", self._ui_process.pid)
        except OSError as exc:
            log.exception("Could not start the UI process")
            self._notify_error(f"Could not open the HotString3 window: {exc}")

    # -- shutdown -----------------------------------------------------------
    def request_exit(self) -> None:
        """Ask the main loop to shut down."""
        self._stop.set()

    def shutdown(self) -> None:
        """Stop every component and exit cleanly."""
        log.info("Shutting down HotString3")
        if self._ui_process is not None and self._ui_process.poll() is None:
            try:
                self._ui_process.terminate()
                self._ui_process.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self._ui_process.kill()
                except Exception:  # noqa: BLE001
                    log.debug("Could not terminate the UI process", exc_info=True)
        self._ui_process = None

        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self._popup.close()
        self._notice.close()
        self._signals.close()
        log.info("HotString3 stopped")


def run_application() -> int:
    """Entry point used by the console script and ``python -m hotstring3``."""
    config.setup_logging()
    instance = SingleInstance()
    if not instance.acquire():
        log.info("Another instance is running; asking it to show the UI")
        signals.signal_show_ui()
        return 0

    try:
        return HotString3Application().run()
    except Exception:  # noqa: BLE001 - log fatal startup errors instead of dying silently
        log.exception("Fatal error in HotString3")
        raise
    finally:
        instance.release()
