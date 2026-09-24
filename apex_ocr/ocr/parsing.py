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


def _strip_time_token(text: str) -> tuple[str, Optional[re.Match]]:
    """Retire le premier motif d'horaire trouvé (ancré sur ':', donc sans
    ambiguïté) et renvoie le texte restant + le match. Doit toujours être
    extrait AVANT les tours : sinon, quand l'OCR ne restitue pas l'espace
    entre "tt/tt" et l'heure (ex: "0/2010:00" au lieu de "0/20 10:00"), la
    regex gourmande des tours mange les premiers chiffres de l'heure
    (-> "0/201" au lieu de "0/20")."""
    match = _find_time_match(text)
    if not match:
        return text, None
    remainder = (text[: match.start()] + text[match.end() :]).strip()
    return remainder, match


def parse_strict(raw_text: str) -> Optional[StrictReading]:
    text = clean_raw(raw_text)
    if not text:
        return None

    remainder, time_match = _strip_time_token(text)
    if time_match is None:
        return None
    raw_time = time_match.group(0)
    time_text = raw_time if ":" in raw_time else repair_colons(raw_time)
    if not is_valid_time(time_text):
        return None

    laps_done = laps_total = None
    laps_match = _LAPS_RE.search(remainder)
    if laps_match:
        laps_done, laps_total = int(laps_match.group(1)), int(laps_match.group(2))
        remainder = (remainder[: laps_match.start()] + remainder[laps_match.end() :]).strip()

    if remainder:
        return None

    return StrictReading(time_text=time_text, laps_done=laps_done, laps_total=laps_total)


def _strip_laps_token(text: str) -> tuple[str, Optional[re.Match]]:
    """Retire le motif de tours (tt/tt) et renvoie le texte restant + le match."""
    match = _LAPS_RE.search(text)
    if not match:
        return text, None
    remainder = (text[: match.start()] + text[match.end() :]).strip()
    return remainder, match


def parse_lenient(raw_text: str) -> LenientReading:
    """Tente toujours d'extraire les tours (même si absents jusqu'ici) : sinon
    on ne détecterait jamais leur apparition en cours de session.

    Quand un ':' ET un '/' sont présents, on essaie les deux ordres d'extraction
    (temps-d'abord vs tours-d'abord) et on garde celui qui extrait le plus
    d'information : sinon la regex temps peut avaler les chiffres des tours
    (ex: "14/15 01:12" brouillé en "150112" → faux temps "15:01") ou la regex
    tours peut avaler les chiffres du temps (ex: "0/2010:00" → faux total 201)."""
    text = clean_raw(raw_text)

    # Stratégie 1 : temps d'abord (ordre historique, évite que les tours
    # avalent le début du temps quand il n'y a pas d'espace).
    remainder_t, _ = _strip_time_token(text)
    time1 = extract_time(text)
    laps1 = extract_laps(remainder_t)

    # Stratégie 2 : tours d'abord (évite que le temps avale les chiffres
    # des tours quand le '/' est absent du texte brouillé).
    remainder_l, laps_match = _strip_laps_token(text)
    time2 = extract_time(remainder_l) if laps_match else None
    laps2 = (int(laps_match.group(1)), int(laps_match.group(2))) if laps_match else None

    # Choisir la stratégie qui extrait le plus : préférer celle qui a à la
    # fois un temps ET des tours ; à égalité, préférer temps-d'abord (1).
    score1 = (time1 is not None) + (laps1 is not None)
    score2 = (time2 is not None) + (laps2 is not None)

    if score2 > score1:
        time_text = time2
        laps_done = laps2[0] if laps2 else None
        laps_total = laps2[1] if laps2 else None
    else:
        time_text = time1
        laps_done = laps1[0] if laps1 else None
        laps_total = laps1[1] if laps1 else None

    return LenientReading(time_text=time_text, laps_done=laps_done, laps_total=laps_total)
