"""PyInstaller entry point for the standalone Windows build.

The frozen executable must initialise multiprocessing before anything else so
the spawned native-window process re-enters the bootloader instead of running
the normal application startup again.
"""

from __future__ import annotations

import multiprocessing

from hotstring3.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
