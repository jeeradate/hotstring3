"""Console entry point: ``uv run hotstring3`` / ``python -m hotstring3``."""

from __future__ import annotations

import argparse
import multiprocessing
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and start either the background app or the UI window."""
    # Required when the app is frozen: NiceGUI's native window is a spawned child
    # process that re-executes this executable with multiprocessing arguments.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(
        prog="hotstring3",
        description="HotString3 — type a short trigger anywhere on Windows to run a command.",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--onboarding",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.ui:
        from .ui import run_ui_process

        run_ui_process(onboarding=args.onboarding)
        return 0

    from .app import run_application

    return run_application()


if __name__ == "__main__":
    raise SystemExit(main())
