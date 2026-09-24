"""Panneau LED : contenu à afficher, rendu, et pilotage BLE (client simulé)."""
from __future__ import annotations

import asyncio
import io
import logging
import time

import pytest
from PIL import Image

from apex_ocr.led import panel as panel_mod
from apex_ocr.led.content import PanelContent, panel_content
from apex_ocr.led.panel import LedPanel, LedStatus
from apex_ocr.led.protocol import brightness_command, build_png_packet, power_command
from apex_ocr.led.rendering import TimerRenderer, blank_png
from apex_ocr.session import DisplayValue, SessionState

RED = (255, 30, 20)


# ---- contenu -------------------------------------------------------------


def test_content_blank_when_not_running():
    live = DisplayValue("09:58", None, None, is_live=True)
    assert panel_content(SessionState.WAITING, live) is None
    assert panel_content(SessionState.ARMED, live) is None


def test_content_blank_after_session_ends():
    frozen = DisplayValue("00:00", 20, 20, is_live=False)
    assert panel_content(SessionState.WAITING, frozen) is None


def test_content_time_only():
    value = DisplayValue("09:58", None, None, is_live=True)
    assert panel_content(SessionState.RUNNING, value) == PanelContent("09:58", None)


def test_content_time_and_laps_padded():
    value = DisplayValue("09:58", 3, 20, is_live=True)
    assert panel_content(SessionState.RUNNING, value) == PanelContent("09:58", "03/20")


def test_content_laps_three_digits():
    value = DisplayValue("1:09:58", 7, 120, is_live=True)
    assert panel_content(SessionState.RUNNING, value).laps_text == "007/120"


# ---- rendu ---------------------------------------------------------------


def _decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_render_panel_size_and_lit_pixels():
    renderer = TimerRenderer(64, 16, RED)
    img = _decode(renderer.render("09:58"))
    assert img.size == (64, 16)
    assert img.getbbox() is not None  # au moins un pixel allumé


def test_render_split_uses_both_sides():
    renderer = TimerRenderer(64, 16, RED)
    img = _decode(renderer.render("09:58", "03/20"))
    boundary = round(64 * 0.34)
    assert img.crop((0, 0, boundary, 16)).getbbox() is not None
    assert img.crop((boundary, 0, 64, 16)).getbbox() is not None


def test_render_caches_font_per_shape():
    renderer = TimerRenderer(64, 16, RED)
    renderer.render("09:58")
    renderer.render("09:57")
    renderer.render("1:09:57")
    assert len(renderer._fonts) == 2


# ---- pilotage BLE (client simulé) -----------------------------------------


class FakeClient:
    instances: list["FakeClient"] = []
    fail_connects = 0
    write_delay = 0.0

    def __init__(self, address, disconnected_callback=None, timeout=None):
        self.address = address
        self.is_connected = False
        self.writes: list[bytes] = []
        self.disconnected_callback = disconnected_callback
        FakeClient.instances.append(self)

    async def connect(self):
        if FakeClient.fail_connects > 0:
            FakeClient.fail_connects -= 1
            raise OSError("panneau introuvable")
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def write_gatt_char(self, uuid, data, response=None):
        if FakeClient.write_delay:
            await asyncio.sleep(FakeClient.write_delay)
        if not self.is_connected:
            raise OSError("déconnecté")
        self.writes.append(bytes(data))


@pytest.fixture
def led(monkeypatch):
    FakeClient.instances = []
    FakeClient.fail_connects = 0
    FakeClient.write_delay = 0.0
    monkeypatch.setattr(panel_mod, "BleakClient", FakeClient)
    monkeypatch.setattr(panel_mod, "RETRY_MIN_S", 0.01)
    monkeypatch.setattr(panel_mod, "RETRY_MAX_S", 0.02)
    p = LedPanel(64, 16, RED, logging.getLogger("test_led"))
    yield p
    p.shutdown()


def wait_until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition non atteinte")


BLANK = build_png_packet(blank_png(64, 16))


def packet_for(time_text, laps_text=None, rgb=RED):
    return build_png_packet(TimerRenderer(64, 16, rgb).render(time_text, laps_text))


def test_connect_full_brightness_then_clears_screen(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    writes = FakeClient.instances[-1].writes
    assert writes[:3] == [brightness_command(100), power_command(True), BLANK]


def test_show_sends_content_then_blank(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    client = FakeClient.instances[-1]
    led.show(PanelContent("09:58", "03/20"))
    wait_until(lambda: client.writes[-1] == packet_for("09:58", "03/20"))
    led.show(None)
    wait_until(lambda: client.writes[-1] == BLANK)


def test_slow_bluetooth_skips_to_latest_value(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    client = FakeClient.instances[-1]
    FakeClient.write_delay = 0.2
    led.show(PanelContent("09:58"))
    time.sleep(0.05)  # 09:58 est en cours d'envoi
    led.show(PanelContent("09:57"))
    led.show(PanelContent("09:56"))
    wait_until(lambda: client.writes[-1] == packet_for("09:56"))
    assert packet_for("09:57") not in client.writes


def test_retries_until_panel_available(led):
    FakeClient.fail_connects = 3
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    assert len(FakeClient.instances) == 4


def test_reconnects_and_resends_after_drop(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    led.show(PanelContent("05:00"))
    first = FakeClient.instances[-1]
    wait_until(lambda: first.writes[-1] == packet_for("05:00"))

    first.is_connected = False
    first.disconnected_callback(first)
    wait_until(lambda: len(FakeClient.instances) == 2 and FakeClient.instances[-1].writes[-1:] == [packet_for("05:00")])


def test_disconnect_clears_screen(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    client = FakeClient.instances[-1]
    led.show(PanelContent("05:00"))
    wait_until(lambda: client.writes[-1] == packet_for("05:00"))
    led.disconnect()
    wait_until(lambda: led.status == LedStatus.DISABLED)
    assert client.writes[-1] == BLANK
    assert not client.is_connected


def test_color_change_resends_current_value(led):
    led.connect("AA:BB")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    client = FakeClient.instances[-1]
    led.show(PanelContent("05:00"))
    wait_until(lambda: client.writes[-1] == packet_for("05:00"))
    led.set_color((40, 220, 90))
    wait_until(lambda: client.writes[-1] == packet_for("05:00", rgb=(40, 220, 90)))
