"""Lectures structurées du chrono (temps + tours) et conversions de format.

Héritées du parsing OCR : ``StrictReading`` sert à armer/démarrer une session (lecture
complète), ``LenientReading`` pendant la course (temps ou tours peuvent manquer). La source
Apex Timing (``apex_ocr/source/apex_live.py``) produit les deux à partir de la base.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def seconds_from_time(text: str) -> Optional[int]:
    """"MM:SS" ou "H:MM:SS" -> secondes, None si ce n'est pas un temps."""
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def time_from_seconds(total_seconds: float, with_hours: bool, round_up: bool = False) -> str:
    """``round_up`` : arrondi au supérieur, comme l'affichage de GoKarts."""
    total_seconds = max(0, int(math.ceil(total_seconds - 1e-6) if round_up else round(total_seconds)))
    if with_hours:
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    m, s = divmod(total_seconds, 60)
    return f"{m:02d}:{s:02d}"


@dataclass(frozen=True)
class StrictReading:
    """Lecture complète et non ambiguë (utilisée pour armer/démarrer une session)."""

    time_text: str
    laps_done: Optional[int]
    laps_total: Optional[int]

    @property
    def has_laps(self) -> bool:
        return self.laps_done is not None


@dataclass(frozen=True)
class LenientReading:
    """Lecture partielle tolérante (utilisée pendant une session en cours)."""

    time_text: Optional[str]
    laps_done: Optional[int]
    laps_total: Optional[int]
