"""Capture de fenêtre : chemin de repli (PrintWindow -> capture d'écran) et raisons d'échec,
avec des faux win32/mss/pygetwindow (aucune fenêtre réelle)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from apex_ocr import capture

TITLE = "Timer Test - Apex Timing OCR – Brave"


class FakeGw:
    def __init__(self, windows):
        self._windows = windows

    def getWindowsWithTitle(self, title):
        return [w for w in self._windows if w.title == title]

    def getAllTitles(self):
        return [w.title for w in self._windows]


class FakeMss:
    """mss.mss() simulé : renvoie une image rouge sauf hors des écrans (exception)."""
    grabbed: list[dict] = []
    fail = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, region):
        FakeMss.grabbed.append(region)
        if FakeMss.fail:
            raise ValueError("hors écran")
        w, h = region["width"], region["height"]
        return SimpleNamespace(width=w, height=h, rgb=bytes([200, 0, 0]) * (w * h))


def window(left=40, top=40, width=300, height=200, minimized=False):
    return SimpleNamespace(title=TITLE, left=left, top=top, width=width, height=height, isMinimized=minimized)


@pytest.fixture
def fakes(monkeypatch):
    FakeMss.grabbed = []
    FakeMss.fail = False
    monkeypatch.setattr(capture.mss, "mss", FakeMss)
    monkeypatch.setattr(capture, "WIN32_OK", True)
    monkeypatch.setattr(capture, "win32gui", SimpleNamespace(GetWindowRect=lambda h: (-1928, -8, 8, 1040)), raising=False)
    monkeypatch.setattr(capture, "_find_hwnd_by_title", lambda title: 4242)
    monkeypatch.setattr(capture, "_capture_hwnd_content", lambda h, w, ht: None)   # PrintWindow échoue
    return monkeypatch


def test_printwindow_success_is_used_first(fakes):
    fakes.setattr(capture, "gw", FakeGw([window()]))
    fakes.setattr(capture, "_capture_hwnd_content", lambda h, w, ht: Image.new("RGB", (w, ht), (0, 255, 0)))
    img, reason = capture.capture_window_ex(TITLE)
    assert reason == "" and img.size == (300, 200) and not FakeMss.grabbed


def test_falls_back_to_screen_grab_with_real_negative_rect(fakes):
    fakes.setattr(capture, "gw", FakeGw([window(left=0, top=0)]))   # pygetwindow se trompe, GetWindowRect fait foi
    img, reason = capture.capture_window_ex(TITLE)
    assert reason == "" and img is not None
    assert FakeMss.grabbed == [{"left": -1928, "top": -8, "width": 1936, "height": 1048}]


def test_minimized_window_is_reported_not_restored(fakes):
    fakes.setattr(capture, "gw", FakeGw([window(minimized=True)]))
    img, reason = capture.capture_window_ex(TITLE)
    assert img is None and reason == capture.REASON_WINDOW_MINIMIZED and not FakeMss.grabbed


def test_window_not_found(fakes):
    fakes.setattr(capture, "gw", FakeGw([]))
    assert capture.capture_window_ex(TITLE) == (None, capture.REASON_WINDOW_NOT_FOUND)


def test_screen_grab_failure_reason(fakes):
    fakes.setattr(capture, "gw", FakeGw([window()]))
    FakeMss.fail = True
    img, reason = capture.capture_window_ex(TITLE)
    assert img is None and reason == capture.REASON_SCREEN_GRAB_FAILED
    assert capture.CAPTURE_REASON_LABELS[reason]


def test_zone_scaled_when_window_size_differs_from_calibration():
    assert capture.scale_zone((100, 50, 200, 40), [1000, 500], (2000, 1000)) == (200, 100, 400, 80)
    assert capture.scale_zone((100, 50, 200, 40), None, (2000, 1000)) == (100, 50, 200, 40)      # ancienne config
    assert capture.scale_zone((100, 50, 200, 40), [1000, 500], (1000, 500)) == (100, 50, 200, 40)


def test_capture_zone_ex_crops_scaled_zone(fakes):
    fakes.setattr(capture, "gw", FakeGw([window(width=600, height=400)]))
    fakes.setattr(capture, "_capture_hwnd_content", lambda h, w, ht: Image.new("RGB", (w, ht), (0, 0, 255)))
    img, reason = capture.capture_zone_ex(TITLE, (10, 10, 100, 50), ref_size=[300, 200])
    assert reason == "" and img.size == (200, 100)
