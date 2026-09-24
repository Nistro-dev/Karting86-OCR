"""Rendu des images envoyées au panneau LED (texte centré, temps + tours
côte à côte). Repris de newkart-led-panel, réduit au minuteur."""
from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = ("arialbd.ttf", "arial.ttf", "consolab.ttf", "cour.ttf", "DejaVuSans-Bold.ttf")

# tours plus petits à gauche, temps plus grand à droite (même disposition
# que le mode combiné de newkart-led-panel)
LAPS_SPLIT = 0.34


def _to_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def blank_png(width: int, height: int) -> bytes:
    return _to_png(Image.new("RGB", (width, height), (0, 0, 0)))


def fit_font(text: str, width: int, height: int):
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for candidate in FONT_CANDIDATES:
        for size in range(height + 4, 3, -1):
            try:
                font = ImageFont.truetype(candidate, size)
            except OSError:
                break
            bbox = probe.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= width and bbox[3] - bbox[1] <= height:
                return font
    return ImageFont.load_default()


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, font, rgb: tuple, x0: int, width: int, height: int):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = x0 + max(0, (width - tw) // 2) - bbox[0]
    y = max(0, (height - th) // 2) - bbox[1]
    draw.text((x, y), text, font=font, fill=rgb)


class TimerRenderer:
    """Rend "MM:SS" (ou "tt/tt MM:SS") en PNG à la taille du panneau.

    La recherche de police est coûteuse (plusieurs tailles/polices testées) :
    on la met en cache par *forme* de texte (chiffres remplacés par 0), donc
    une seule fois par format et pas à chaque seconde."""

    def __init__(self, width: int, height: int, rgb: tuple):
        self.width = width
        self.height = height
        self.rgb = rgb
        self._fonts: dict[tuple, object] = {}

    def _font(self, text: str, width: int):
        key = (re.sub(r"\d", "0", text), width)
        font = self._fonts.get(key)
        if font is None:
            font = self._fonts[key] = fit_font(key[0], width, self.height)
        return font

    def render(self, time_text: str, laps_text: str | None = None) -> bytes:
        img = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        if laps_text:
            boundary = max(1, min(self.width - 1, round(self.width * LAPS_SPLIT)))
            right_w = self.width - boundary
            _draw_centered(draw, laps_text, self._font(laps_text, boundary - 2), self.rgb, 0, boundary, self.height)
            _draw_centered(draw, time_text, self._font(time_text, right_w - 2), self.rgb, boundary, right_w, self.height)
        else:
            _draw_centered(draw, time_text, self._font(time_text, self.width), self.rgb, 0, self.width, self.height)
        return _to_png(img)
