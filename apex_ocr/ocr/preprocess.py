"""Prétraitement d'image avant OCR : niveaux de gris, binarisation, upscale.

Pillow uniquement (plus d'OpenCV/numpy : −40 Mo d'exe pour trois opérations).
"""
from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

MIN_TEXT_HEIGHT_PX = 100
"""Hauteur minimale (px) visée après upscale : plus de détail pour Tesseract,
qui distingue mieux 0/6/2/8 sur de plus grands caractères que sur un petit
crop natif."""

THICKEN_PX = 3
"""Taille du filtre d'épaississement des traits (après upscale) : des traits
trop fins font lire un ':' comme un '/' ou perdre un segment de chiffre."""


def preprocess(pil_img: Image.Image, threshold: int) -> Image.Image:
    """Image binaire (mode L, 0/255) : texte NOIR sur fond BLANC, à la taille
    minimale attendue par Tesseract.

    Le seuil s'applique aux niveaux de gris d'origine (c'est lui qui est
    calibré) ; l'inversion automatique se décide ensuite sur le résultat : si
    la majorité des pixels est noire (texte clair sur fond sombre, ex. thème
    sombre d'Apex Timing), on inverse pour retrouver du noir sur blanc, que
    Tesseract lit bien mieux."""
    gray = ImageOps.grayscale(pil_img)
    bw = gray.point(lambda p: 255 if p > threshold else 0, mode="L")

    # La décision d'inversion se prend sur le CENTRE de la zone (moitié centrale),
    # là où sont les chiffres : une zone calibrée un peu large embarque des bords
    # (fond de page sombre, boutons) qui, sinon, feraient inverser à tort une boîte
    # claire à chiffres sombres.
    w, h = bw.size
    core = bw.crop((w // 4, h // 4, w - w // 4, h - h // 4)) if w >= 4 and h >= 4 else bw
    if core.histogram()[255] < core.width * core.height / 2:
        bw = ImageOps.invert(bw)

    w, h = bw.size
    if h < MIN_TEXT_HEIGHT_PX:
        scale = max(2, MIN_TEXT_HEIGHT_PX // h)
        # Le ré-échantillonnage crée des gris sur les bords : on re-binarise pour
        # garder des traits nets, puis on les épaissit légèrement.
        bw = bw.resize((w * scale, h * scale), Image.LANCZOS).point(lambda p: 255 if p > 127 else 0, mode="L")
        bw = bw.filter(ImageFilter.MinFilter(THICKEN_PX))
    return bw
