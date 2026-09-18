"""Calibration automatique du seuil de binarisation.

Teste une plage de seuils sur PLUSIEURS captures prises à des instants
différents (pas une seule image) : une seule capture peut tomber sur une
lecture ponctuellement bonne ou mauvaise et donner un résultat différent à
chaque calibration. Un seuil n'est retenu que s'il est valide sur une
majorité des échantillons, puis on choisit le centre de la plus longue
plage contiguë de seuils robustes plutôt qu'un seuil "limite".
"""
from __future__ import annotations

from typing import Optional

from PIL import Image

from apex_ocr.ocr import engine
from apex_ocr.ocr.parsing import parse_strict
from apex_ocr.ocr.preprocess import preprocess

DEFAULT_THRESHOLD_RANGE = range(40, 221, 8)
MIN_VALID_RATIO = 0.7


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


def calibrate_threshold(images: list[Image.Image], threshold_range=DEFAULT_THRESHOLD_RANGE) -> Optional[int]:
    thresholds = list(threshold_range)
    if not images or not thresholds:
        return None

    per_sample_valid: list[set[int]] = []
    for img in images:
        valid_here: set[int] = set()
        for t in thresholds:
            processed = preprocess(img, t)
            text = engine.extract_text(processed)
            if parse_strict(text) is not None:
                valid_here.add(t)
        per_sample_valid.append(valid_here)

    validity = aggregate_sample_validity(per_sample_valid, thresholds)
    return find_most_robust_threshold(validity)
