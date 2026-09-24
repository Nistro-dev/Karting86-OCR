"""Ce que le panneau LED doit afficher, à partir de l'état de la session
(pure logique, testée)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from apex_ocr.session import DisplayValue, SessionState


@dataclass(frozen=True)
class PanelContent:
    time_text: str
    laps_text: Optional[str] = None


def panel_content(state: SessionState, display: DisplayValue, laps_only: bool = False) -> Optional[PanelContent]:
    """Contenu à afficher sur le panneau LED.

    En course (RUNNING) : chrono et tours (ou tours seuls si *laps_only*).
    Sinon : heure courante (HH:MM:SS)."""
    if state != SessionState.RUNNING or not display.is_live:
        return PanelContent(time_text=time.strftime("%H:%M:%S"))
    laps_text = None
    if display.laps_total is not None:
        digits = max(2, len(str(display.laps_total)))
        laps_text = f"{display.laps_done or 0:0{digits}d}/{display.laps_total}"
    if laps_only and laps_text is not None:
        return PanelContent(time_text=laps_text)
    return PanelContent(display.time_text, laps_text)
