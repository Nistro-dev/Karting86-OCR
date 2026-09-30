"""Icône dans la zone de notification : logo New Kart Poitiers teinté selon
l'état de santé (gris = attente, vert = course suivie, rouge = problème).
L'infobulle et la première ligne du menu (clic droit) donnent le statut
courant et le détail du problème s'il y en a un, en plus d'Afficher/Quitter."""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray

from apex_ocr.health import HealthStatus
from apex_ocr.ui import branding

_TOOLTIP_MAX = 120   # limite Windows pour l'infobulle d'une icône de notification


def build_default_icon_image(size: int = 64):
    """Icône par défaut (logo carré, sans teinte de statut) — utilisée pour l'exe/l'icône de fenêtre initiale."""
    return branding.build_square_icon(size)


class TrayIcon:
    def __init__(self, on_show: Callable[[], None], on_quit: Callable[[], None]):
        self._icons = {
            status: branding.build_status_icon(64, tint, round_shape=True)
            for status, tint in branding.HEALTH_TINTS.items()
        }
        self._icon: Optional[pystray.Icon] = None
        self._on_show = on_show
        self._on_quit = on_quit
        self._current: Optional[tuple[HealthStatus, str]] = None
        self._status_text = "État : inconnu"

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afficher", lambda: self._on_show(), default=True),
            pystray.MenuItem("Quitter", lambda: self._on_quit()),
        )
        self._icon = pystray.Icon("NewKartPanneauLed", self._icons[HealthStatus.IDLE], branding.APP_NAME, menu)
        threading.Thread(target=self._icon.run, daemon=True).start()

    def set_status(self, status: HealthStatus, detail: str = "") -> None:
        if self._icon is None or (status, detail) == self._current:
            return
        self._current = (status, detail)
        label = branding.HEALTH_LABELS[status][0]
        self._status_text = f"État : {label}" + (f" — {detail}" if detail else "")
        self._icon.icon = self._icons[status]
        try:
            self._icon.title = (f"{branding.APP_NAME} — {label}" + (f"\n{detail}" if detail else ""))[:_TOOLTIP_MAX]
            self._icon.update_menu()
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
