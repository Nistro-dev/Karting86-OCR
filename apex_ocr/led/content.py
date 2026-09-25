"""Ce que le panneau LED doit afficher, à partir de l'état de la session
(pure logique, testée)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from apex_ocr.ocr.parsing import seconds_from_time
from apex_ocr.session import DisplayValue, SessionState


@dataclass(frozen=True)
class PanelContent:
    time_text: str
    laps_text: Optional[str] = None
    alert: bool = False


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


def panel_content(
    state: SessionState,
    display: DisplayValue,
    laps_only: bool = False,
    alert_seconds: int = 60,
    alert_laps: int = 5,
) -> Optional[PanelContent]:
    """Contenu à afficher sur le panneau LED.

    En course (RUNNING) : chrono et tours (ou tours seuls si *laps_only*).
    Sinon : heure courante (HH:MM:SS)."""
    if state != SessionState.RUNNING or not display.is_live:
        return PanelContent(time_text=time.strftime("%H:%M"))
    laps_text = None
    if display.laps_total is not None:
        digits = max(2, len(str(display.laps_total)))
        laps_text = f"{display.laps_done or 0:0{digits}d}/{display.laps_total}"
    alert = _is_alert(display, alert_seconds, alert_laps)
    if laps_only and laps_text is not None:
        return PanelContent(time_text=laps_text, alert=alert)
    return PanelContent(display.time_text, laps_text, alert=alert)
