"""Ressources de marque : logos New Kart Poitiers et palette associée.

Trois variantes, chacune avec un usage dédié :
- ``logo_favicon.png`` : marque seule, fond transparent -> placée sur les
  fonds existants (bandeau fenêtre, filigrane affichage externe).
- ``logo_square.png`` : carré arrondi (fond noir intégré) -> icône exe /
  fenêtre / barre des tâches.
- ``logo_round.png`` : badge rond (fond noir intégré) -> icône systray.
"""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(_UI_DIR)), "assets")

FAVICON_PATH = os.path.join(_ASSETS_DIR, "logo_favicon.png")
SQUARE_LOGO_PATH = os.path.join(_ASSETS_DIR, "logo_square.png")
ROUND_LOGO_PATH = os.path.join(_ASSETS_DIR, "logo_round.png")
THEME_PATH = os.path.join(_UI_DIR, "theme_newkart.json")

PRIMARY_RED = "#ED1B24"
PRIMARY_RED_HOVER = "#951019"
ACCENT_GREY = "#787878"
BG_BLACK = "#111111"


def _load(path: str) -> Optional[Image.Image]:
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def load_logo() -> Optional[Image.Image]:
    """Marque seule, fond transparent (bandeaux/filigranes)."""
    return _load(FAVICON_PATH)


def build_square_icon(size: int = 256) -> Image.Image:
    """Icône carrée (exe / fenêtre / barre des tâches)."""
    img = _load(SQUARE_LOGO_PATH)
    if img is None:
        return Image.new("RGBA", (size, size), (17, 17, 17, 255))
    return img.resize((size, size), Image.LANCZOS)


def build_round_icon(size: int = 256) -> Image.Image:
    """Icône ronde (systray)."""
    img = _load(ROUND_LOGO_PATH)
    if img is None:
        return build_square_icon(size)
    return img.resize((size, size), Image.LANCZOS)


def build_status_icon(size: int, tint: tuple[int, int, int], alpha: float = 0.40, round_shape: bool = False) -> Image.Image:
    """Icône (carrée ou ronde) teintée d'une couleur de statut."""
    base = (build_round_icon(size) if round_shape else build_square_icon(size)).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (*tint, int(255 * alpha)))
    return Image.alpha_composite(base, overlay)
