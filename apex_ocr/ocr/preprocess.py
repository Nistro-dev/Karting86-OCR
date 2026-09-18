"""Prétraitement d'image avant OCR : niveaux de gris, binarisation, upscale."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


MIN_TEXT_HEIGHT_PX = 100
"""Hauteur minimale (px) visée après upscale : plus de détail pour le
classifieur LSTM de Tesseract, qui distingue mieux 0/6/2/8 sur de plus
grands caractères que sur un petit crop natif."""


def preprocess(pil_img: Image.Image, threshold: int) -> np.ndarray:
    arr = np.array(pil_img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    h, w = bw.shape
    if h < MIN_TEXT_HEIGHT_PX:
        scale = max(2, MIN_TEXT_HEIGHT_PX // h)
        bw = cv2.resize(bw, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    return bw
