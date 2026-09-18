"""Parsing du texte OCR brut en lectures structurées (temps + tours).

Deux modes de lecture :
- ``parse_strict`` : la chaîne entière doit correspondre à un format connu.
  Utilisé pour armer/confirmer un départ (on ne veut aucun faux positif).
- ``parse_lenient`` : extrait indépendamment le temps et les tours, même si
  l'un des deux est illisible. Utilisé une fois la session en cours, pour
  éviter qu'un bruit ponctuel sur une partie de la zone invalide tout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_ALLOWED_CHARS_RE = re.compile(r"[^0-9:/\s]")
_WHITESPACE_RE = re.compile(r"\s+")

_LAPS_RE = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})")
_TIME_WITH_COLON_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
_TIME_DIGITS_RE = re.compile(r"(?<!\d)(\d{3,6})(?!\d)")
_TIME_VALID_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def clean_raw(text: str) -> str:
    """Ne garde que chiffres / ':' / '/' / espaces (réduits à un seul)."""
    cleaned = _ALLOWED_CHARS_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def repair_colons(digits: str) -> str:
    """Reconstruit les ':' quand Tesseract ne les a pas lus, selon le nombre de chiffres."""
    if len(digits) == 3:
        return f"{digits[0]}:{digits[1:]}"
    if len(digits) == 4:
        return f"{digits[:2]}:{digits[2:]}"
    if len(digits) == 5:
        return f"{digits[0]}:{digits[1:3]}:{digits[3:]}"
    if len(digits) == 6:
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"
    return digits


def is_valid_time(text: str) -> bool:
    if not _TIME_VALID_RE.match(text):
        return False
    # Les minutes et secondes doivent être < 60 : sans ce garde-fou, un simple
    # 0 lu comme 6 par l'OCR (ex: "09:49" -> "69:49") passerait pour valide.
    minutes_and_seconds = text.split(":")[-2:]
    return all(int(p) < 60 for p in minutes_and_seconds)


def seconds_from_time(text: str) -> Optional[int]:
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def time_from_seconds(total_seconds: float, with_hours: bool) -> str:
    total_seconds = max(0, int(round(total_seconds)))
    if with_hours:
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    m, s = divmod(total_seconds, 60)
    return f"{m:02d}:{s:02d}"


def _find_time_match(text: str) -> Optional[re.Match]:
    return _TIME_WITH_COLON_RE.search(text) or _TIME_DIGITS_RE.search(text)


def extract_time(text: str) -> Optional[str]:
    match = _find_time_match(text)
    if not match:
        return None
    raw = match.group(0)
    candidate = raw if ":" in raw else repair_colons(raw)
    return candidate if is_valid_time(candidate) else None


def extract_laps(text: str) -> Optional[tuple[int, int]]:
    match = _LAPS_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


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


def parse_strict(raw_text: str) -> Optional[StrictReading]:
    text = clean_raw(raw_text)
    if not text:
        return None

    laps_match = _LAPS_RE.search(text)
    remainder = text
    laps_done = laps_total = None
    if laps_match:
        laps_done, laps_total = int(laps_match.group(1)), int(laps_match.group(2))
        remainder = (text[: laps_match.start()] + text[laps_match.end() :]).strip()

    time_match = _find_time_match(remainder)
    if not time_match:
        return None
    raw_time = time_match.group(0)
    time_text = raw_time if ":" in raw_time else repair_colons(raw_time)
    if not is_valid_time(time_text):
        return None

    leftover = (remainder[: time_match.start()] + remainder[time_match.end() :]).strip()
    if leftover:
        return None

    return StrictReading(time_text=time_text, laps_done=laps_done, laps_total=laps_total)


def parse_lenient(raw_text: str) -> LenientReading:
    """Tente toujours d'extraire les tours (même si absents jusqu'ici) : sinon
    on ne détecterait jamais leur apparition en cours de session."""
    text = clean_raw(raw_text)
    laps_done = laps_total = None
    laps = extract_laps(text)
    if laps is not None:
        laps_done, laps_total = laps
    return LenientReading(time_text=extract_time(text), laps_done=laps_done, laps_total=laps_total)
