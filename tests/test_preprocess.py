"""Prétraitement (Pillow) : sortie binaire noir-sur-blanc, inversion automatique, upscale."""
from PIL import Image, ImageDraw

from apex_ocr.ocr.preprocess import MIN_TEXT_HEIGHT_PX, preprocess


def synthetic(bg, fg, size=(120, 30)):
    img = Image.new("RGB", size, bg)
    ImageDraw.Draw(img).rectangle((20, 8, 40, 22), fill=fg)   # un « trait » de texte
    return img


def lit_ratio(img: Image.Image) -> float:
    hist = img.histogram()
    return hist[0] / (img.width * img.height)   # part de pixels noirs


def test_dark_text_on_light_background_stays_black_on_white():
    out = preprocess(synthetic(bg=(230, 230, 230), fg=(10, 10, 10)), threshold=127)
    hist = out.histogram()
    assert out.mode == "L" and hist[0] + hist[255] == out.width * out.height   # binaire
    assert 0 < lit_ratio(out) < 0.5          # texte noir minoritaire sur fond blanc


def test_light_text_on_dark_background_is_inverted():
    out = preprocess(synthetic(bg=(0, 0, 0), fg=(0, 255, 40)), threshold=127)
    assert 0 < lit_ratio(out) < 0.5          # même résultat : noir sur blanc


def test_small_crops_are_upscaled_to_min_height():
    out = preprocess(synthetic(bg=(230, 230, 230), fg=(0, 0, 0), size=(120, 30)), threshold=127)
    scale = max(2, MIN_TEXT_HEIGHT_PX // 30)   # même règle que l'ancienne version OpenCV
    assert out.size == (120 * scale, 30 * scale)


def test_large_crops_keep_their_size():
    out = preprocess(synthetic(bg=(230, 230, 230), fg=(0, 0, 0), size=(400, 150)), threshold=127)
    assert out.size == (400, 150)
