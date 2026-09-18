"""Appel à Tesseract pour lire le texte brut d'une zone prétraitée."""
from __future__ import annotations

import pytesseract

_TESS_CONFIG = (
    "--psm 7 "
    "-c tessedit_char_whitelist=0123456789:/ "
    "-c classify_bln_numeric_mode=1"  # aide le classifieur legacy sur du numérique pur (sans effet si LSTM only, inoffensif)
)


def set_tesseract_path(path: str) -> None:
    if path:
        pytesseract.pytesseract.tesseract_cmd = path


def extract_text(processed_image) -> str:
    return pytesseract.image_to_string(processed_image, config=_TESS_CONFIG).strip()
