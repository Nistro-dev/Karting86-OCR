"""Ressources de marque : logo New Kart Poitiers et palette associée."""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(_UI_DIR)), "assets")

LOGO_PATH = os.path.join(_ASSETS_DIR, "logo_newkart_poitiers.png")
THEME_PATH = os.path.join(_UI_DIR, "theme_newkart.json")

PRIMARY_RED = "#ED1B24"
PRIMARY_RED_HOVER = "#951019"
ACCENT_GREY = "#787878"
BG_BLACK = "#111111"


def load_logo() -> Optional[Image.Image]:
    try:
        return Image.open(LOGO_PATH).convert("RGBA")
    except Exception:
        return None


def build_square_icon(size: int = 256) -> Image.Image:
    """Compose le logo (rectangulaire) sur un canevas carré, pour l'icône
    exe / fenêtre / systray."""
    canvas = Image.new("RGBA", (size, size), (17, 17, 17, 255))
    logo = load_logo()
    if logo is not None:
        scale = min(size * 0.86 / logo.width, size * 0.86 / logo.height)
        new_size = (max(1, int(logo.width * scale)), max(1, int(logo.height * scale)))
        resized = logo.resize(new_size, Image.LANCZOS)
        x = (size - new_size[0]) // 2
        y = (size - new_size[1]) // 2
        canvas.paste(resized, (x, y), resized)
    return canvas
