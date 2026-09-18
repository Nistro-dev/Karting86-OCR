"""Génère les images de l'installeur (assistant Inno Setup) aux couleurs de
CodeForgeStudio (éditeur du logiciel) — distinct du logo New Kart Poitiers
(client) utilisé pour l'icône de l'application elle-même.

Palette dérivée d'une capture d'écran du logiciel de gestion CodeForgeStudio
(fond quasi noir, dégradé violet/cyan).
"""
import os

from PIL import Image, ImageDraw, ImageFont

BG_TOP = (12, 11, 15)
BG_BOTTOM = (31, 14, 33)
VIOLET = (192, 71, 204)
VIOLET_DARK = (108, 34, 114)
TEAL = (65, 199, 216)
WHITE = (240, 240, 245)

OUT_DIR = os.path.join(os.path.dirname(__file__), "installer_assets")


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _vertical_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", size)
    for y in range(h):
        t = y / max(1, h - 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            img.putpixel((x, y), row)
    return img


def _add_glow(img: Image.Image, center, radius, color, max_alpha=90):
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    steps = 40
    for i in range(steps, 0, -1):
        r = radius * i / steps
        alpha = int(max_alpha * (1 - i / steps) ** 2)
        gd.ellipse(
            (center[0] - r, center[1] - r, center[0] + r, center[1] + r),
            fill=(*color, alpha),
        )
    base = img.convert("RGBA")
    return Image.alpha_composite(base, glow).convert("RGB")


def build_wizard_image(size=(164, 314)) -> Image.Image:
    img = _vertical_gradient(size, BG_TOP, BG_BOTTOM)
    img = _add_glow(img, (size[0] * 0.85, size[1] * 0.08), size[0] * 0.9, TEAL, max_alpha=70)
    img = _add_glow(img, (size[0] * 0.15, size[1] * 0.95), size[0] * 1.0, VIOLET, max_alpha=60)

    d = ImageDraw.Draw(img)
    # glyphe "code" abstrait : chevrons
    gx, gy = size[0] * 0.5, size[1] * 0.42
    gs = size[0] * 0.16
    d.line([(gx - gs, gy), (gx - gs * 1.6, gy + gs * 0.6), (gx - gs, gy + gs * 1.2)], fill=VIOLET, width=4)
    d.line([(gx + gs, gy), (gx + gs * 1.6, gy + gs * 0.6), (gx + gs, gy + gs * 1.2)], fill=TEAL, width=4)

    font_lg = _font(int(size[0] * 0.155))
    font_sm = _font(int(size[0] * 0.10))
    y_text = size[1] * 0.58
    for line, font, color in (("CodeForge", font_lg, WHITE), ("Studio", font_sm, (180, 180, 190))):
        bbox = d.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        d.text((size[0] / 2 - w / 2, y_text), line, font=font, fill=color)
        y_text += (bbox[3] - bbox[1]) + size[1] * 0.03

    return img


def build_small_image(size=(55, 58)) -> Image.Image:
    img = _vertical_gradient(size, BG_TOP, BG_BOTTOM)
    img = _add_glow(img, (size[0] * 0.7, size[1] * 0.3), size[0] * 1.1, VIOLET, max_alpha=90)
    d = ImageDraw.Draw(img)
    font = _font(int(size[1] * 0.42))
    text = "CF"
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((size[0] / 2 - w / 2, size[1] / 2 - h / 2 - bbox[1]), text, font=font, fill=WHITE)
    return img


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    wizard = build_wizard_image()
    wizard_path = os.path.join(OUT_DIR, "wizard_image.bmp")
    wizard.save(wizard_path)
    print(f"Écrit : {wizard_path}")

    small = build_small_image()
    small_path = os.path.join(OUT_DIR, "wizard_small.bmp")
    small.save(small_path)
    print(f"Écrit : {small_path}")
