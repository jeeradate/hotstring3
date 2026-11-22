"""Console entry point: ``uv run hotstring`` / ``python -m hotstring``."""

from __future__ import annotations

import argparse
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and start either the background app or the UI window."""
    parser = argparse.ArgumentParser(
        prog="hotstring",
        description="HotString — type a short trigger anywhere on Windows to run a command.",
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
