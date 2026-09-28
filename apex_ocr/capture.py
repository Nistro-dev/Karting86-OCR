"""Capture du contenu réel d'une fenêtre Windows, même occultée ou en arrière-plan.

Essaie d'abord ``PrintWindow`` (lit le buffer de rendu de la fenêtre
directement), puis se replie sur une capture d'écran classique (``mss``) sur
le rectangle réel de la fenêtre — y compris en coordonnées négatives, quand
elle est sur un écran placé à gauche/au-dessus de l'écran principal.

``capture_window_ex`` / ``capture_zone_ex`` renvoient en plus la raison d'un
échec, pour que l'appli puisse dire *pourquoi* elle ne lit rien.
"""
from __future__ import annotations

import sys
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

# Raisons d'échec exposées à l'appli (texte lisible côté UI, voir CAPTURE_REASON_LABELS).
REASON_OK = ""
REASON_WINDOW_NOT_FOUND = "window_not_found"
REASON_WINDOW_MINIMIZED = "window_minimized"
REASON_PRINTWINDOW_FAILED = "printwindow_failed"
REASON_SCREEN_GRAB_FAILED = "screen_grab_failed"

CAPTURE_REASON_LABELS = {
    REASON_OK: "",
    REASON_WINDOW_NOT_FOUND: "fenêtre source introuvable (fermée ou titre différent)",
    REASON_WINDOW_MINIMIZED: "fenêtre source réduite : la restaurer",
    REASON_PRINTWINDOW_FAILED: "capture de la fenêtre impossible (hors écran ou non rendue)",
    REASON_SCREEN_GRAB_FAILED: "capture d'écran impossible (fenêtre hors des écrans ?)",
}

# PW_RENDERFULLCONTENT (contenu composé, fenêtres DirectComposition/navigateurs),
# puis le mode classique en repli : certaines fenêtres ne répondent qu'à l'un des deux.
_PRINTWINDOW_FLAGS = (2, 0)


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


def _print_window(hwnd: int, width: int, height: int, flags: int) -> Optional[Image.Image]:
    hwnd_dc = mfc_dc = save_dc = bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        if win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags) != 1:
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1,
        )
        return img if img.getbbox() is not None else None  # image noire = fenêtre non rendue
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


def _capture_hwnd_content(hwnd: int, width: int, height: int) -> Optional[Image.Image]:
    if not WIN32_OK or width <= 0 or height <= 0:
        return None
    for flags in _PRINTWINDOW_FLAGS:
        img = _print_window(hwnd, width, height, flags)
        if img is not None:
            return img
    return None


def _window_rect(hwnd: Optional[int], w) -> tuple[int, int, int, int]:
    """(left, top, width, height) réels de la fenêtre : via GetWindowRect quand on a le
    handle (fiable en coordonnées négatives / multi-écrans), sinon via pygetwindow."""
    if WIN32_OK and hwnd:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right > left and bottom > top:
                return left, top, right - left, bottom - top
        except Exception:
            pass
    return w.left, w.top, w.width, w.height


def _screen_grab(left: int, top: int, width: int, height: int) -> Optional[Image.Image]:
    """Capture d'écran du rectangle donné (coordonnées de l'écran virtuel, négatives
    comprises) ; None si la zone est hors des écrans ou si mss échoue. Contrairement à
    PrintWindow, une image toute noire est ici un vrai contenu (thème sombre), pas un échec."""
    if width <= 0 or height <= 0:
        return None
    try:
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
            return Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
    except Exception:
        return None


def capture_window_ex(title: str) -> tuple[Optional[Image.Image], str]:
    """Capture le contenu réel de la fenêtre nommée ``title`` -> (image, raison).
    ``raison`` est vide en cas de succès, sinon l'une des constantes REASON_*."""
    if gw is None:
        return None, REASON_WINDOW_NOT_FOUND
    try:
        wins = gw.getWindowsWithTitle(title)
    except Exception:
        return None, REASON_WINDOW_NOT_FOUND
    if not wins:
        return None, REASON_WINDOW_NOT_FOUND
    w = wins[0]

    hwnd = _find_hwnd_by_title(title)
    if hwnd:
        img = _capture_hwnd_content(hwnd, w.width, w.height)
        if img is not None:
            return img, REASON_OK

    if w.isMinimized:
        return None, REASON_WINDOW_MINIMIZED  # pas de restore : ça ramènerait la fenêtre au premier plan

    img = _screen_grab(*_window_rect(hwnd, w))
    if img is not None:
        return img, REASON_OK
    return None, REASON_SCREEN_GRAB_FAILED if hwnd else REASON_PRINTWINDOW_FAILED


def capture_window(title: str) -> Optional[Image.Image]:
    """Capture le contenu réel de la fenêtre nommée ``title``."""
    return capture_window_ex(title)[0]


def scale_zone(zone: tuple[int, int, int, int], ref_size, actual_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Zone définie sur une fenêtre de taille ``ref_size`` -> même zone sur une fenêtre de
    ``actual_size`` (autre DPI, redimensionnée). Sans ``ref_size`` (ancienne config), inchangée."""
    if not ref_size or tuple(ref_size) == tuple(actual_size) or not all(ref_size):
        return zone
    sx = actual_size[0] / ref_size[0]
    sy = actual_size[1] / ref_size[1]
    x, y, w, h = zone
    return round(x * sx), round(y * sy), max(1, round(w * sx)), max(1, round(h * sy))


def capture_zone_ex(title: str, zone: tuple[int, int, int, int], ref_size=None) -> tuple[Optional[Image.Image], str]:
    img, reason = capture_window_ex(title)
    if img is None:
        return None, reason
    x, y, w, h = scale_zone(zone, ref_size, img.size)
    return img.crop((x, y, x + w, y + h)), REASON_OK


def capture_zone(title: str, zone: tuple[int, int, int, int], ref_size=None) -> Optional[Image.Image]:
    return capture_zone_ex(title, zone, ref_size)[0]
