"""Icône dans la zone de notification : logo New Kart Poitiers teinté selon
l'état de santé (gris = attente, vert = course suivie, rouge = problème).
Le clic droit affiche un menu dont la première ligne donne le statut
courant, en plus d'Afficher/Quitter."""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray

from apex_ocr.health import HealthStatus
from apex_ocr.ui import branding

_TINTS: dict[HealthStatus, tuple[int, int, int]] = {
    HealthStatus.IDLE: (140, 140, 140),
    HealthStatus.ACTIVE: (0, 201, 74),
    HealthStatus.ERROR: (237, 27, 36),
}

_STATUS_LABELS = {
    HealthStatus.IDLE: "En attente",
    HealthStatus.ACTIVE: "Course suivie",
    HealthStatus.ERROR: "Problème",
}


def build_default_icon_image(size: int = 64):
    """Icône par défaut (logo, sans teinte de statut) — utilisée pour l'exe/l'icône de fenêtre initiale."""
    return branding.build_square_icon(size)


class TrayIcon:
    def __init__(self, on_show: Callable[[], None], on_quit: Callable[[], None]):
        self._icons = {status: branding.build_status_icon(64, tint) for status, tint in _TINTS.items()}
        self._icon: Optional[pystray.Icon] = None
        self._on_show = on_show
        self._on_quit = on_quit
        self._current_status: Optional[HealthStatus] = None
        self._status_text = "État : inconnu"

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afficher", lambda: self._on_show(), default=True),
            pystray.MenuItem("Quitter", lambda: self._on_quit()),
        )
        self._icon = pystray.Icon("ApexTimingOCR", self._icons[HealthStatus.IDLE], "Apex Timing OCR", menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    def set_status(self, status: HealthStatus) -> None:
        if self._icon is None or status == self._current_status:
            return
        self._current_status = status
        self._status_text = f"État : {_STATUS_LABELS[status]}"
        self._icon.icon = self._icons[status]
        try:
            self._icon.update_menu()
        except Exception:
            pass

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
