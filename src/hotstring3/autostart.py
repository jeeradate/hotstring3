"""Start-with-Windows support through the user's registry ``Run`` key."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "HotString"


def build_launch_command() -> str:
    """Build the command stored in the ``Run`` registry value.

    ``pythonw.exe`` is preferred so no console window appears at login.  When
    HotString is packaged as a frozen executable its own path is used.
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'

    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else executable
    return f'"{interpreter}" -m hotstring'


def is_enabled() -> bool:
    """Return whether HotString is registered to start with Windows."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - not on Windows
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("Could not read autostart registry value: %s", exc)
        return False


def enable() -> bool:
    """Register HotString in the current user's ``Run`` key."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - not on Windows
        log.warning("Autostart is only supported on Windows.")
        return False

    command = build_launch_command()
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        log.info("Enabled start with Windows: %s", command)
        return True
    except OSError as exc:
        log.error("Could not enable autostart: %s", exc)
        return False


def disable() -> bool:
    """Remove HotString from the current user's ``Run`` key."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - not on Windows
        return False

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        log.info("Disabled start with Windows")
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.error("Could not disable autostart: %s", exc)
        return False


def set_enabled(enabled: bool) -> bool:
    """Enable or disable the autostart entry."""
    return enable() if enabled else disable()
