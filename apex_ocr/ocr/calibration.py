"""Calibration automatique du seuil de binarisation.

Teste une plage de seuils sur PLUSIEURS captures prises à des instants
différents (pas une seule image) : une seule capture peut tomber sur une
lecture ponctuellement bonne ou mauvaise et donner un résultat différent à
chaque calibration. Un seuil n'est retenu que s'il est valide sur une
majorité des échantillons ET que les temps lus concordent entre échantillons
(une lecture « valide » n'est pas forcément « correcte » : 09:49 lu 06:49 passe
le format, mais pas la concordance avec les autres captures). On choisit
ensuite le centre de la plus longue plage contiguë de seuils robustes plutôt
qu'un seuil « limite ».
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PIL import Image

from apex_ocr.ocr import engine
from apex_ocr.ocr.parsing import parse_strict, seconds_from_time
from apex_ocr.ocr.preprocess import preprocess

DEFAULT_THRESHOLD_RANGE = range(40, 221, 8)
MIN_VALID_RATIO = 0.7
# Les échantillons sont pris à ~0,25 s d'intervalle : sur 5 captures, le chrono a
# pu changer de 1 à 2 s. Au-delà, les lectures ne parlent pas du même temps.
MAX_SPREAD_SECONDS = 2


def find_most_robust_threshold(validity_by_threshold: dict[int, bool]) -> Optional[int]:
    thresholds = sorted(validity_by_threshold)
    if not thresholds:
        return None
    step = thresholds[1] - thresholds[0] if len(thresholds) > 1 else 1

    best_run: list[int] = []
    current_run: list[int] = []
    prev: Optional[int] = None
    for t in thresholds:
        if not validity_by_threshold[t]:
            current_run = []
            prev = t
            continue
        if prev is not None and t - prev == step and current_run:
            current_run.append(t)
        else:
            current_run = [t]
        if len(current_run) > len(best_run):
            best_run = current_run
        prev = t

    if not best_run:
        return None
    return best_run[len(best_run) // 2]


def aggregate_sample_validity(
    per_sample_valid_thresholds: list[set[int]],
    all_thresholds: list[int],
    min_ratio: float = MIN_VALID_RATIO,
) -> dict[int, bool]:
    """Un seuil n'est "valide" que s'il a réussi sur au moins ``min_ratio``
    des échantillons testés, pas juste un seul coup de chance."""
    n = len(per_sample_valid_thresholds)
    if n == 0:
        return {t: False for t in all_thresholds}
    required = max(1, round(n * min_ratio))
    counts = {t: 0 for t in all_thresholds}
    for valid_set in per_sample_valid_thresholds:
        for t in valid_set:
            if t in counts:
                counts[t] += 1
    return {t: counts[t] >= required for t in all_thresholds}


def concordant_thresholds(
    per_sample_seconds: list[dict[int, int]],
    all_thresholds: list[int],
    max_spread: int = MAX_SPREAD_SECONDS,
) -> set[int]:
    """Seuils pour lesquels les temps lus sur les différents échantillons se
    tiennent dans ``max_spread`` secondes : un seuil qui lit 09:49 sur une capture
    et 06:49 sur la suivante n'est pas fiable, même si chaque lecture est « valide »."""
    ok: set[int] = set()
    for t in all_thresholds:
        values = [sample[t] for sample in per_sample_seconds if t in sample]
        if values and max(values) - min(values) <= max_spread:
            ok.add(t)
    return ok


def calibrate_threshold(
    images: list[Image.Image],
    threshold_range=DEFAULT_THRESHOLD_RANGE,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> Optional[int]:
    """``on_progress(fait, total)`` après chaque essai ; ``cancel`` (Event) interrompt
    la calibration, qui renvoie alors None."""
    thresholds = list(threshold_range)
    if not images or not thresholds:
        return None

    total = len(images) * len(thresholds)
    done = 0
    per_sample_valid: list[set[int]] = []
    per_sample_seconds: list[dict[int, int]] = []
    for img in images:
        valid_here: set[int] = set()
        seconds_here: dict[int, int] = {}
        for t in thresholds:
            if cancel is not None and cancel.is_set():
                return None
            processed = preprocess(img, t)
            reading = parse_strict(engine.extract_text(processed))
            if reading is not None:
                valid_here.add(t)
                secs = seconds_from_time(reading.time_text)
                if secs is not None:
                    seconds_here[t] = secs
            done += 1
            if on_progress is not None:
                on_progress(done, total)
        per_sample_valid.append(valid_here)
        per_sample_seconds.append(seconds_here)

    validity = aggregate_sample_validity(per_sample_valid, thresholds)
    concordant = concordant_thresholds(per_sample_seconds, thresholds)
    return find_most_robust_threshold({t: validity[t] and t in concordant for t in thresholds})
