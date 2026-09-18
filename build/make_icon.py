"""Génère assets/icon.ico à partir du glyphe utilisé par l'appli (fenêtre + tray)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apex_ocr.ui.tray import build_default_icon_image  # noqa: E402

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "icon.ico")
    img = build_default_icon_image(256)
    img.save(out_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Icône écrite : {out_path}")
