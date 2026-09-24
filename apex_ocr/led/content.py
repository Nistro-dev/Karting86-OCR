"""Ce que le panneau LED doit afficher, à partir de l'état de la session
(pure logique, testée)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from apex_ocr.session import DisplayValue, SessionState


@dataclass(frozen=True)
class PanelContent:
    time_text: str
    laps_text: Optional[str] = None


def panel_content(state: SessionState, display: DisplayValue) -> Optional[PanelContent]:
    """Contenu à afficher, ou ``None`` pour un écran vide.

    Uniquement pendant une course confirmée (RUNNING) : une lecture en cours
    d'armement peut être un faux départ, et le résultat figé de la course
    précédente ne doit pas rester sur la piste."""
    if state != SessionState.RUNNING or not display.is_live:
        return None
    laps_text = None
    if display.laps_total is not None:
        digits = max(2, len(str(display.laps_total)))
        laps_text = f"{display.laps_done or 0:0{digits}d}/{display.laps_total}"
    return PanelContent(display.time_text, laps_text)
