"""Icône dans la zone de notification : logo New Kart Poitiers avec un badge
de statut (gris = attente, vert = course suivie, rouge = problème), et permet
d'afficher/quitter l'application."""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from apex_ocr.health import HealthStatus
from apex_ocr.ui import branding

_BADGE_COLORS: dict[HealthStatus, tuple[int, int, int, int]] = {
    HealthStatus.IDLE: (140, 140, 140, 255),
    HealthStatus.ACTIVE: (0, 201, 74, 255),
    HealthStatus.ERROR: (237, 27, 36, 255),
}


def _with_status_badge(base: Image.Image, color: tuple[int, int, int, int]) -> Image.Image:
    img = base.copy()
    d = ImageDraw.Draw(img)
    size = img.width
    r = size * 0.16
    cx = cy = size - r - size * 0.05
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=branding.BG_BLACK, width=max(2, int(size * 0.03)))
    return img


def build_default_icon_image(size: int = 64) -> Image.Image:
    """Icône par défaut de l'application (logo, sans badge de statut)."""
    return branding.build_square_icon(size)


class TrayIcon:
    def __init__(self, on_show: Callable[[], None], on_quit: Callable[[], None]):
        base = branding.build_square_icon(64)
        self._icons = {status: _with_status_badge(base, color) for status, color in _BADGE_COLORS.items()}
        self._icon: Optional[pystray.Icon] = None
        self._on_show = on_show
        self._on_quit = on_quit
        self._current_status: Optional[HealthStatus] = None

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Afficher", lambda: self._on_show(), default=True),
            pystray.MenuItem("Quitter", lambda: self._on_quit()),
        )
        self._icon = pystray.Icon("ApexTimingOCR", self._icons[HealthStatus.IDLE], "Apex Timing OCR", menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    def set_status(self, status: HealthStatus) -> None:
        if self._icon is None or status == self._current_status:
            return
        self._current_status = status
        self._icon.icon = self._icons[status]

    def notify(self, title: str, message: str) -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
