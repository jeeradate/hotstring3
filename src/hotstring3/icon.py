"""Application icon handling.

The repository ships a lightning ``.ico`` in ``assets/``.  A matching icon is
generated as a fallback for source checkouts where the asset folder is missing,
so the window, taskbar and tray always show the same lightning mark.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

from . import config

log = logging.getLogger(__name__)

#: Icon formats tried, in order, from the project's assets folder.
_ICON_NAMES = ("lightning.ico", "lightning.png")

#: Sizes embedded in a generated ``.ico``.
_ICO_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def _asset_dirs() -> tuple[Path, ...]:
    """Return the folders that may contain a bundled lightning icon."""
    return (
        config.ASSETS_DIR,
        config.ASSETS_DIR / "icons",
        Path(__file__).resolve().parent / "assets",
    )


def find_icon_asset() -> Path | None:
    """Return the bundled lightning icon path, or ``None`` when it is missing."""
    for directory in _asset_dirs():
        for name in _ICON_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def create_lightning_image(size: int = 256) -> Image.Image:
    """Draw a fallback icon: a white lightning bolt on a blue rounded square."""
    size = max(16, int(size))
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = max(1, round(size * 0.04))
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=max(4, size // 5),
        fill=(37, 99, 235, 255),
        outline=(29, 78, 216, 255),
        width=max(1, size // 32),
    )

    points = (
        (0.60, 0.12),
        (0.26, 0.56),
        (0.47, 0.56),
        (0.39, 0.89),
        (0.75, 0.43),
        (0.53, 0.43),
    )
    polygon = [(round(x * size), round(y * size)) for x, y in points]
    draw.polygon(polygon, fill=(255, 255, 255, 255))
    return image


def ensure_icon_file() -> str:
    """Return the path of a usable ``.ico`` file for window and tray icons.

    The bundled asset is preferred.  If it is unavailable, a lightning ``.ico``
    is generated once in :data:`config.ICON_PATH`.  Returns an empty string when
    neither is possible, allowing callers to fall back to a default icon.
    """
    asset = find_icon_asset()
    if asset is not None:
        return str(asset)

    try:
        config.APP_DIR.mkdir(parents=True, exist_ok=True)
        if not config.ICON_PATH.exists():
            create_lightning_image(256).save(config.ICON_PATH, format="ICO", sizes=_ICO_SIZES)
        return str(config.ICON_PATH)
    except OSError as exc:
        log.warning("Could not write the application icon: %s", exc)
        return ""


def load_icon_image(size: int = 64) -> Image.Image:
    """Load the application icon at ``size`` pixels, falling back to drawing it."""
    icon_path = ensure_icon_file()
    if icon_path:
        try:
            with Image.open(icon_path) as source:
                return source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except (OSError, ValueError) as exc:
            log.warning("Could not load the application icon: %s", exc)
    return create_lightning_image(size)
