"""Ressources de marque : logos New Kart Poitiers, palette associée et libellés
d'état partagés par toutes les surfaces (fenêtre principale, fenêtre dev, systray).

Trois variantes de logo, chacune avec un usage dédié :
- ``logo_favicon.png`` : marque seule, fond transparent -> bandeau de fenêtre.
- ``logo_square.png`` : carré arrondi (fond noir intégré) -> icône exe /
  fenêtre / barre des tâches.
- ``logo_round.png`` : badge rond (fond noir intégré) -> icône systray.
"""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image

from apex_ocr.health import HealthStatus
from apex_ocr.led.panel import LedStatus

APP_NAME = "New Kart - Panneau led"

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
STATUS_GREY = "#8a8a8a"
STATUS_GREEN = "#00c94a"
STATUS_AMBER = "#e0a000"

# Libellé + couleur de chaque état, une seule source pour toutes les fenêtres.
HEALTH_LABELS: dict[HealthStatus, tuple[str, str]] = {
    HealthStatus.IDLE: ("En attente", STATUS_GREY),
    HealthStatus.ACTIVE: ("Course suivie", STATUS_GREEN),
    HealthStatus.ERROR: ("Problème", PRIMARY_RED),
}
# Teinte RGB des icônes (fenêtre, barre des tâches, systray) selon l'état.
HEALTH_TINTS: dict[HealthStatus, tuple[int, int, int]] = {
    HealthStatus.IDLE: (140, 140, 140),
    HealthStatus.ACTIVE: (0, 201, 74),
    HealthStatus.ERROR: (237, 27, 36),
}
LED_LABELS: dict[LedStatus, tuple[str, str]] = {
    LedStatus.DISABLED: ("Non connecté", STATUS_GREY),
    LedStatus.CONNECTING: ("Connexion...", STATUS_AMBER),
    LedStatus.CONNECTED: ("Connecté", STATUS_GREEN),
    LedStatus.RETRYING: ("Reconnexion...", PRIMARY_RED),
}


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
