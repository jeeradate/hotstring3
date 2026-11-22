"""PowerShell discovery and version reporting.

PowerShell 7 (``pwsh``) is preferred, with Windows PowerShell
(``powershell.exe`` 5.1 or newer) as the fallback.  Detection is cached because
the executable is queried by the executor and by the UI footer.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

WINDOWS_POWERSHELL = "powershell.exe"
PWSH = "pwsh"
MINIMUM_WINDOWS_POWERSHELL = (5, 1)
CREATE_NO_WINDOW = 0x08000000

_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True, slots=True)
class PowerShellInfo:
    """The PowerShell executable selected for command execution."""

    executable: str
    version: str

    @property
    def name(self) -> str:
        """Executable file name, for example ``pwsh`` or ``powershell.exe``."""
        return Path(self.executable).stem

    @property
    def is_pwsh(self) -> bool:
        """Whether PowerShell 7 (``pwsh``) is in use."""
        return self.name.lower() == PWSH

    @property
    def available(self) -> bool:
        """Whether a usable version was detected."""
        return bool(self.version)

    def status_text(self) -> str:
        """Human-readable footer text, for example ``PowerShell: 7.4.2 (pwsh)``."""
        if not self.version:
            return "PowerShell: not detected"
        return f"PowerShell: {self.version} (pwsh)" if self.is_pwsh else f"PowerShell: {self.version}"


_info: PowerShellInfo | None = None
_lock = threading.Lock()


def _known_candidates() -> list[str]:
    """Return executable candidates in priority order (PowerShell 7 first)."""
    candidates: list[str] = []

    for name in (PWSH, WINDOWS_POWERSHELL):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    program_files = (
        os.environ.get("ProgramW6432")
        or os.environ.get("ProgramFiles")
        or r"C:\Program Files"
    )
    local_appdata = os.environ.get("LOCALAPPDATA")
    system_root = os.environ.get("SystemRoot", r"C:\Windows")

    known = [
        Path(program_files) / "PowerShell" / "7" / "pwsh.exe",
        Path(program_files) / "PowerShell" / "7-preview" / "pwsh.exe",
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
    ]
    if local_appdata:
        known.insert(2, Path(local_appdata) / "Microsoft" / "WindowsApps" / "pwsh.exe")

    candidates.extend(str(path) for path in known if path.is_file())

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _creation_flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _probe_version(executable: str) -> str | None:
    """Return the PowerShell version reported by ``executable``, or ``None``."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable, no shell
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$PSVersionTable.PSVersion.ToString()",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=_creation_flags(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Could not query PowerShell at %s: %s", executable, exc)
        return None

    for line in reversed((completed.stdout or "").splitlines()):
        match = _VERSION_RE.search(line.strip())
        if match:
            return ".".join(part for part in match.groups() if part is not None)
    if completed.returncode != 0:
        log.debug(
            "PowerShell version probe failed for %s (exit %s): %s",
            executable,
            completed.returncode,
            (completed.stderr or "").strip(),
        )
    return None


def _is_supported(executable: str, version: str) -> bool:
    """Check that the detected version meets the minimum requirements."""
    match = _VERSION_RE.match(version)
    if match is None:
        return False
    major = int(match.group(1))
    minor = int(match.group(2))

    if Path(executable).stem.lower() == PWSH:
        return major >= 6  # PowerShell 7 and newer (preview builds included)
    return (major, minor) >= MINIMUM_WINDOWS_POWERSHELL


def detect_powershell() -> PowerShellInfo:
    """Detect and prioritise an installed PowerShell 7 or Windows PowerShell 5.1+."""
    for executable in _known_candidates():
        version = _probe_version(executable)
        if version is not None and _is_supported(executable, version):
            info = PowerShellInfo(executable=executable, version=version)
            log.info("Using PowerShell %s (%s)", version, info.name)
            return info

    # Keep commands working even when detection is inconclusive; the process
    # error is reported through the normal executor error path.
    log.warning("No supported PowerShell version was detected; falling back to %s", WINDOWS_POWERSHELL)
    return PowerShellInfo(executable=WINDOWS_POWERSHELL, version="")


def get_powershell_info(*, refresh: bool = False) -> PowerShellInfo:
    """Return the cached PowerShell information, detecting it on first use."""
    global _info
    with _lock:
        if refresh or _info is None:
            _info = detect_powershell()
        return _info


def reset_cache() -> None:
    """Forget the cached detection result (used by tests)."""
    global _info
    with _lock:
        _info = None
