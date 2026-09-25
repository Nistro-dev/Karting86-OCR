"""Capture du contenu réel d'une fenêtre Windows, même occultée ou en arrière-plan.

Essaie d'abord ``PrintWindow`` (lit le buffer de rendu de la fenêtre
directement), puis se replie sur une capture d'écran classique (``mss``) si
indisponible ou en échec.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from PIL import Image

try:
    import pygetwindow as gw
except ImportError:
    gw = None

WIN32_OK = False
if sys.platform == "win32":
    try:
        import win32gui
        import win32ui

        WIN32_OK = True
    except ImportError:
        WIN32_OK = False

import mss


def list_window_titles() -> list[str]:
    if gw is None:
        return []
    try:
        return sorted(set(t for t in gw.getAllTitles() if t.strip()))
    except Exception:
        return []


def _find_hwnd_by_title(title: str) -> Optional[int]:
    if not WIN32_OK:
        return None
    matches: list[int] = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
            matches.append(hwnd)

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception:
        return None
    return matches[0] if matches else None


def _capture_hwnd_content(hwnd: int, width: int, height: int) -> Optional[Image.Image]:
    if not WIN32_OK or width <= 0 or height <= 0:
        return None
    hwnd_dc = mfc_dc = save_dc = bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        result = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
        if result != 1:
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )
        return img if img.getbbox() is not None else None
    except Exception:
        return None
    finally:
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)


def capture_window(title: str) -> Optional[Image.Image]:
    """Capture le contenu réel de la fenêtre nommée ``title``."""
    if gw is None:
        return None
    try:
        wins = gw.getWindowsWithTitle(title)
    except Exception:
        return None
    if not wins:
        return None
    w = wins[0]

    hwnd = _find_hwnd_by_title(title)
    if hwnd:
        img = _capture_hwnd_content(hwnd, w.width, w.height)
        if img is not None:
            return img

    if w.isMinimized:
        return None  # pas de restore : ça ramènerait la fenêtre au premier plan
    try:
        with mss.mss() as sct:
            mon = {"left": w.left, "top": w.top, "width": w.width, "height": w.height}
            shot = sct.grab(mon)
            return Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
    except Exception:
        return None


def capture_zone(title: str, zone: tuple[int, int, int, int]) -> Optional[Image.Image]:
    img = capture_window(title)
    if img is None:
        return None
    x, y, w, h = zone
    return img.crop((x, y, x + w, y + h))
