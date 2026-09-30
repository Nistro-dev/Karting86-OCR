"""Ce que le panneau LED doit afficher, à partir de l'état de la session
(pure logique, testée)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from apex_ocr.readings import seconds_from_time
from apex_ocr.session import DisplayValue, SessionState


@dataclass(frozen=True)
class PanelContent:
    time_text: str
    laps_text: Optional[str] = None
    alert: bool = False
    clock: bool = False                # heure courante : image fixe, pas un décompte
    alert_below: Optional[int] = None  # seuil (s) sous lequel les trames du décompte prennent la couleur d'alerte


def _is_alert(display: DisplayValue, alert_seconds: int, alert_laps: int) -> bool:
    """Vrai si on est dans la zone d'alerte (temps ou tours)."""
    remaining_seconds = seconds_from_time(display.time_text)
    if remaining_seconds is not None and remaining_seconds <= alert_seconds:
        return True
    if display.laps_total is not None and display.laps_done is not None:
        remaining_laps = display.laps_total - display.laps_done
        if remaining_laps <= alert_laps:
            return True
    return False


def trim_zero_hours(time_text: str) -> str:
    """"00:10:00" -> "10:00" : des heures à zéro n'apportent rien sur le panneau et prennent
    la place des gros chiffres. "1:09:58" reste tel quel."""
    parts = time_text.split(":")
    if len(parts) == 3 and parts[0].isdigit() and int(parts[0]) == 0:
        return ":".join(parts[1:])
    return time_text


def panel_content(
    state: SessionState,
    display: DisplayValue,
    laps_only: bool = False,
    alert_seconds: int = 60,
    alert_laps: int = 5,
    idle_clock: bool = True,
) -> Optional[PanelContent]:
    """Contenu à afficher sur le panneau LED.

    En course (RUNNING) : chrono et tours (ou tours seuls si *laps_only*).
    Sinon : heure courante (HH:MM, renvoyée au panneau à chaque changement de minute),
    ou écran noir (``None``) si *idle_clock* est faux."""
    if state != SessionState.RUNNING or not display.is_live:
        return PanelContent(time_text=time.strftime("%H:%M"), clock=True) if idle_clock else None
    laps_text = None
    if display.laps_total is not None:
        digits = max(2, len(str(display.laps_total)))
        laps_text = f"{display.laps_done or 0:0{digits}d}/{display.laps_total}"
    alert = _is_alert(display, alert_seconds, alert_laps)
    if laps_only and laps_text is not None:
        return PanelContent(time_text=laps_text, alert=alert)
    return PanelContent(trim_zero_hours(display.time_text), laps_text, alert=alert, alert_below=alert_seconds)
