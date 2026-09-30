"""Panneau LED : contenu à afficher, rendu 64×16, programme RHX8 et pilotage Wi-Fi (panneau simulé)."""
from __future__ import annotations

import logging
import re
import threading
import time

import pytest

from apex_ocr.led import panel as panel_mod
from apex_ocr.led import protocol
from apex_ocr.led.content import PanelContent, panel_content, trim_zero_hours
from apex_ocr.led.panel import LedPanel, LedStatus
from apex_ocr.led.rendering import (BLUE, GREEN, RED, WHITE, Frame, TimerRenderer, build_program, color_index,
                                    format_like, parse_seconds, program_length, program_size)
from apex_ocr.session import DisplayValue, SessionState

RED_RGB = (255, 30, 20)
BLUE_RGB = (0, 0, 255)
PASSWORD = "LED12345678"


# ---- contenu -------------------------------------------------------------


def test_content_clock_when_not_running():
    live = DisplayValue("09:58", None, None, is_live=True)
    for state in (SessionState.WAITING, SessionState.ARMED):
        content = panel_content(state, live)
        assert content.clock and re.fullmatch(r"\d{2}:\d{2}", content.time_text) and content.laps_text is None


def test_content_clock_after_session_ends():
    frozen = DisplayValue("00:00", 20, 20, is_live=False)
    assert panel_content(SessionState.WAITING, frozen).clock


def test_content_time_only():
    value = DisplayValue("09:58", None, None, is_live=True)
    assert panel_content(SessionState.RUNNING, value) == PanelContent("09:58", None, alert_below=60)


def test_content_time_and_laps_padded():
    value = DisplayValue("09:58", 3, 20, is_live=True)
    assert panel_content(SessionState.RUNNING, value) == PanelContent("09:58", "03/20", alert_below=60)


def test_content_laps_three_digits():
    value = DisplayValue("1:09:58", 7, 120, is_live=True)
    assert panel_content(SessionState.RUNNING, value).laps_text == "007/120"


def test_content_drops_zero_hours():
    assert panel_content(SessionState.RUNNING, DisplayValue("00:10:00", None, None, True)).time_text == "10:00"
    assert panel_content(SessionState.RUNNING, DisplayValue("0:09:58", None, None, True)).time_text == "09:58"
    assert panel_content(SessionState.RUNNING, DisplayValue("1:09:58", None, None, True)).time_text == "1:09:58"
    assert panel_content(SessionState.RUNNING, DisplayValue("01:09:58", None, None, True)).time_text == "01:09:58"
    assert trim_zero_hours("09:58") == "09:58"


def test_content_idle_without_clock_is_blank():
    live = DisplayValue("09:58", None, None, is_live=True)
    assert panel_content(SessionState.WAITING, live, idle_clock=False) is None
    assert panel_content(SessionState.WAITING, live, idle_clock=True).clock
    # en course, le réglage n'a pas d'effet
    assert panel_content(SessionState.RUNNING, live, idle_clock=False).time_text == "09:58"


def test_content_laps_only_is_static_text():
    value = DisplayValue("09:58", 3, 20, is_live=True)
    assert panel_content(SessionState.RUNNING, value, laps_only=True) == PanelContent("03/20")
    assert panel_content(SessionState.RUNNING, DisplayValue("09:58", None, None, True), laps_only=True).time_text == "09:58"


def test_content_alert_on_time_or_laps():
    assert not panel_content(SessionState.RUNNING, DisplayValue("01:01", None, None, True)).alert
    assert panel_content(SessionState.RUNNING, DisplayValue("01:00", None, None, True)).alert
    assert panel_content(SessionState.RUNNING, DisplayValue("09:58", 15, 20, True)).alert          # 5 tours restants
    assert not panel_content(SessionState.RUNNING, DisplayValue("09:58", 14, 20, True)).alert
    assert panel_content(SessionState.RUNNING, DisplayValue("02:00", None, None, True), alert_seconds=120).alert_below == 120


# ---- protocole -----------------------------------------------------------


@pytest.mark.parametrize("password, token", [
    ("LED12345678", "d92e2bb0e0632d5c"),   # 2e bloc RC5 = mdp[3:11] : ne dépend pas du défi,
    ("12345678", "4197268e2f477b32"),      # comparé aux échanges capturés avec l'appli RHX Plus
    ("LED166188", "e00b6f6936fa8919"),
])
def test_login_response_matches_captures(password, token):
    assert protocol.login_response(bytes(8), password)[8:16].hex() == token


def test_login_response_depends_on_nonce():
    a = protocol.login_response(bytes(8), PASSWORD)
    b = protocol.login_response(bytes(range(8)), PASSWORD)
    assert a[:8] != b[:8] and a[8:] == b[8:]


def test_rc5_roundtrip():
    block = bytes(range(8))
    assert protocol.rc5_decrypt(protocol.rc5_encrypt(block)) == block


def test_brightness_packet_levels():
    assert protocol.brightness_packet(1)[6:8] == b"\x0a\xf0"
    assert protocol.brightness_packet(16)[6:8] == b"\x0a\xff"
    assert protocol.brightness_packet(99) == protocol.brightness_packet(16)


# ---- rendu ---------------------------------------------------------------


def lit(frame: Frame, x0=0, x1=64) -> int:
    return sum(1 for row in frame.px for x in range(x0, x1) if row[x])


def test_parse_and_format_time():
    assert parse_seconds("09:58") == 598
    assert parse_seconds("1:09:58") == 4198
    assert parse_seconds("--:--") is None
    assert format_like(598, "09:58") == "09:58"
    assert format_like(4198, "1:09:58") == "1:09:58"
    assert format_like(4198, "01:09:58") == "01:09:58"
    assert format_like(-3, "09:58") == "00:00"


def test_color_index_quantizes_to_panel_palette():
    assert color_index(RED_RGB) == RED
    assert color_index((40, 220, 90)) == GREEN
    assert color_index((0, 0, 255)) == BLUE
    assert color_index((10, 10, 10)) == WHITE  # jamais noir sur noir


def test_render_fills_height_and_keeps_row0_clear():
    fr = TimerRenderer(64, 16, RED_RGB).render("09:58")
    assert lit(fr) > 100
    assert not any(fr.px[0])                       # ligne 0 inatteignable sur le panneau
    assert any(fr.px[1]) and any(fr.px[15])        # chiffres sur toute la hauteur
    assert all(c in (0, RED) for row in fr.px for c in row)


def test_render_split_uses_both_sides():
    fr = TimerRenderer(64, 16, RED_RGB).render("09:58", "03/20")
    assert lit(fr, 0, 30) > 0 and lit(fr, 30, 64) > 0


@pytest.mark.parametrize("time_text, laps", [("09:58", None), ("1:09:58", None), ("01:09:58", None),
                                             ("09:58", "03/20"), ("1:09:58", "007/120"), ("59:59", "999/999")])
def test_render_never_overflows(time_text, laps):
    fr = TimerRenderer(64, 16, RED_RGB).render(time_text, laps)
    assert lit(fr) > 0
    assert any(fr.px[y][63] == 0 for y in range(16)) or lit(fr, 63, 64) < 16
    assert fr != TimerRenderer(64, 16, RED_RGB).render("00:00", laps)


def test_countdown_frames_one_per_second():
    frames = TimerRenderer(64, 16, RED_RGB).countdown("00:03")
    r = TimerRenderer(64, 16, RED_RGB)
    assert frames == [r.render("00:03"), r.render("00:02"), r.render("00:01"), r.render("00:00")]
    assert len(TimerRenderer(64, 16, RED_RGB).countdown("00:10", max_frames=4)) == 4


def test_rotated_180_mirrors_drawable_area_and_keeps_row0_clear():
    fr = TimerRenderer(64, 16, RED_RGB).render("09:58", "03/20")
    rot = fr.rotated_180()
    assert not any(rot.px[0])                                  # ligne 0 toujours inatteignable
    for y in range(1, 16):
        for x in range(64):
            assert rot.px[16 - y][63 - x] == fr.px[y][x]
    assert rot != fr
    assert rot.rotated_180() == fr                             # involution
    assert Frame().rotated_180() == Frame()                    # écran noir inchangé


def test_renderer_rotate_180_applies_to_every_frame():
    plain, upside = TimerRenderer(64, 16, RED_RGB), TimerRenderer(64, 16, RED_RGB, rotate_180=True)
    assert upside.render("09:58", "03/20") == plain.render("09:58", "03/20").rotated_180()
    assert upside.render("12:34") == plain.render("12:34").rotated_180()
    assert upside.countdown("00:02") == [f.rotated_180() for f in plain.countdown("00:02")]
    # tours à gauche à l'endroit -> à droite une fois tourné (le panneau, lui, est à l'envers)
    fr = upside.render("09:58", "03/20")
    assert lit(fr, 0, 30) > 0 and lit(fr, 34, 64) > 0


# ---- programme RHX8 -------------------------------------------------------


def decode_program(program: bytes) -> list[Frame]:
    """Inverse de build_program : relit les lignes via la table de pointeurs et défait le mapping physique."""
    nf = int.from_bytes(program[166:168], "big")
    frames = []
    for f in range(nf):
        planes = [[bytearray(8) for _ in range(17)] for _ in range(3)]
        for e in range(48):
            ptr = int.from_bytes(program[2887 + 4 * (f * 48 + e):2887 + 4 * (f * 48 + e) + 4], "big")
            data = program[ptr:ptr + 8]
            plane, row = e // 16, e % 16
            planes[plane][row][2:8] = data[0:6]
            planes[plane][row + 1][0:2] = data[6:8]
        fr = Frame()
        for y in range(16):
            for x in range(64):
                c = sum(((planes[b][y][x // 8] >> (7 - x % 8)) & 1) << b for b in range(3))
                fr.set(x, y, c)
        frames.append(fr)
    return frames


def test_program_roundtrip_all_pixels_and_colors():
    r = TimerRenderer(64, 16, RED_RGB)
    a, b = r.render("12:34", "03/20"), Frame()
    for y in range(1, 16):
        for x in range(64):
            b.set(x, y, (x + y) % 7 + 1)
    program = build_program([a, b])
    assert decode_program(program) == [a, b]
    assert program_length(program) == len(program) - 12   # n exclut somme de contrôle, horodatage et somme finale
    assert program_size(2) == len(program)
    assert int.from_bytes(program[-4:], "big") == sum(program[:-4]) & 0xFFFFFFFF


def test_program_rejects_empty():
    with pytest.raises(ValueError):
        build_program([])


# ---- pilotage Wi-Fi (panneau simulé) ----------------------------------------


class FakePanel:
    """Serveur RHX8 simulé au bout d'un faux socket : login RC5, luminosité, transfert de programme."""

    def __init__(self):
        self.sockets: list["FakeSocket"] = []
        self.uploads: list[bytes] = []
        self.brightness: list[int] = []
        self.heartbeats = 0
        self.fail_connects = 0
        self.upload_delay = 0.0
        self.password = PASSWORD
        self.lock = threading.Lock()

    def create_connection(self, address, timeout=None):
        if self.fail_connects > 0:
            self.fail_connects -= 1
            raise OSError("panneau introuvable")
        s = FakeSocket(self, address)
        self.sockets.append(s)
        return s

    def handle(self, sock: "FakeSocket", data: bytes) -> bytes:
        if data[:6] != bytes.fromhex("aa55aa550000"):
            if self.upload_delay:
                time.sleep(self.upload_delay)
            with self.lock:
                self.uploads.append(data)
            return b"\x88"
        op = data[6]
        if op == 0xFF:
            sock.nonce = bytes([len(self.sockets)] * 8)
            return bytes.fromhex("aa55aa55000059a008") + sock.nonce + b"\x04"
        if op == 0x89:
            ok = data[9:25] == protocol.login_response(sock.nonce, self.password)
            sock.logged_in = ok
            return bytes.fromhex("aa55aa55000059a1") if ok else bytes.fromhex("aa55aa55000059a3")
        if not sock.logged_in:
            return b"\x00"
        if op == 0x0A:
            self.brightness.append(data[7] - 0xEF)
            return b"\x88"
        if op == 0x78:
            return b"\xe1"
        if op == 0x82:                      # battement de cœur
            self.heartbeats += 1
            return bytes(64)
        return b"\x00"

    @property
    def last_frames(self) -> list[Frame]:
        with self.lock:
            return decode_program(self.uploads[-1]) if self.uploads else []


class FakeSocket:
    def __init__(self, panel: FakePanel, address):
        self.panel, self.address = panel, address
        self.nonce = b""
        self.logged_in = False
        self.closed = False
        self.dropped = False
        self._reply = b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def settimeout(self, t):
        pass

    def sendall(self, data: bytes):
        if self.closed or self.dropped:
            raise OSError("connexion perdue")
        self._reply = self.panel.handle(self, bytes(data))

    def recv(self, n: int) -> bytes:
        if self.dropped:
            raise OSError("connexion perdue")
        reply, self._reply = self._reply, b""
        return reply

    def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    fp = FakePanel()
    monkeypatch.setattr(panel_mod.socket, "create_connection", fp.create_connection)
    monkeypatch.setattr(panel_mod, "RETRY_MIN_S", 0.01)
    monkeypatch.setattr(panel_mod, "RETRY_MAX_S", 0.02)
    return fp


@pytest.fixture
def led(fake):
    p = LedPanel(64, 16, RED_RGB, BLUE_RGB, logging.getLogger("test_led"), password=PASSWORD, brightness=7)
    yield p
    p.shutdown()


def colors_of(frame: Frame) -> set:
    return {c for row in frame.px for c in row if c}


def wait_until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition non atteinte")


def frames_for(time_text, laps_text=None, rgb=RED_RGB):
    return TimerRenderer(64, 16, rgb).countdown(time_text, laps_text)


def test_connect_logs_in_sets_brightness_then_clears_screen(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    sock = fake.sockets[-1]
    assert sock.address == ("192.168.47.1", protocol.DEFAULT_PORT) and sock.logged_in
    assert fake.brightness == [7]
    assert fake.last_frames == [Frame()]


def test_host_with_port(led, fake):
    led.connect("10.0.0.5:2000")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    assert fake.sockets[-1].address == ("10.0.0.5", 2000)


def test_wrong_password_is_reported(fake, monkeypatch):
    fake.password = "autre"
    p = LedPanel(64, 16, RED_RGB, BLUE_RGB, logging.getLogger("test_led"), password=PASSWORD)
    try:
        p.connect("192.168.47.1")
        wait_until(lambda: p.status == LedStatus.RETRYING and "login" in p.status_detail)
        assert not fake.uploads
    finally:
        p.shutdown()


def test_show_sends_whole_countdown_then_blank(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05", "03/20"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert fake.last_frames == frames_for("00:05", "03/20")   # 6 trames, 00:05 -> 00:00
    led.show(None)
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == [Frame()]


def test_countdown_in_progress_is_not_resent(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.show(PanelContent("00:08"))
    led.show(PanelContent("00:07"))
    time.sleep(0.2)
    assert len(fake.uploads) == 2                              # le panneau déroule tout seul


def test_countdown_resyncs_when_timer_jumps(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.show(PanelContent("00:04"))                            # écart de 5 s > tolérance
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == frames_for("00:04")


def test_paused_timer_becomes_static_then_resumes(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "FROZEN_S", 0.3)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09"))
    wait_until(lambda: len(fake.uploads) == 2)
    wait_until(lambda: len(fake.uploads) == 3)                 # valeur figée -> image fixe 00:09
    assert fake.last_frames == [TimerRenderer(64, 16, RED_RGB).render("00:09")]
    time.sleep(0.6)
    assert len(fake.uploads) == 3                              # et on n'y touche plus
    led.show(PanelContent("00:08"))                            # le chrono repart
    wait_until(lambda: len(fake.uploads) == 4)
    assert fake.last_frames == frames_for("00:08")


def test_countdown_is_sent_in_chunks(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "CHUNK_EXTRA_S", 1)
    monkeypatch.setattr(panel_mod, "FROZEN_S", 10.0)
    led._chunk_s = 2                                           # tranches de 2 s (2 min en réel)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert fake.last_frames == frames_for("00:09")[:4]         # 00:09 -> 00:06 : tranche + réserve
    time.sleep(1.0)
    led.show(PanelContent("00:08"))
    time.sleep(1.0)
    led.show(PanelContent("00:07"))
    wait_until(lambda: len(fake.uploads) == 3)                 # tranche suivante 2 s après la 1re
    assert fake.last_frames == frames_for("00:07")[:4]
    led.show(PanelContent("00:02"))                            # dernière tranche : jusqu'à 00:00
    wait_until(lambda: len(fake.uploads) == 4)
    assert fake.last_frames == frames_for("00:02")


def test_clock_is_static_and_follows_the_minute(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("16:05", clock=True))
    wait_until(lambda: len(fake.uploads) == 2)
    assert fake.last_frames == [TimerRenderer(64, 16, RED_RGB).render("16:05")]   # pas un décompte
    time.sleep(0.2)
    assert len(fake.uploads) == 2
    led.show(PanelContent("16:06", clock=True))
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == [TimerRenderer(64, 16, RED_RGB).render("16:06")]


def test_alert_frames_are_precolored(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "RESYNC_TOLERANCE_S", 5)    # le test saute des secondes sans attendre
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05", alert_below=2))
    wait_until(lambda: len(fake.uploads) == 2)
    frames = fake.last_frames
    assert [colors_of(f) for f in frames] == [{RED}] * 3 + [{BLUE}] * 3      # 00:02, 00:01, 00:00 en alerte
    led.show(PanelContent("00:04", alert_below=2))
    led.show(PanelContent("00:02", alert=True, alert_below=2))                 # prévu dans les trames
    time.sleep(0.2)
    assert len(fake.uploads) == 2


def test_alert_from_laps_recolors_everything(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09", "15/20", alert=True, alert_below=2))
    wait_until(lambda: len(fake.uploads) == 2)
    assert all(colors_of(f) == {BLUE} for f in fake.last_frames)
    led.set_alert_color((40, 220, 90))
    wait_until(lambda: len(fake.uploads) == 3)
    assert all(colors_of(f) == {GREEN} for f in fake.last_frames)


def test_clock_blip_during_countdown_is_absorbed(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "CLOCK_GRACE_S", 1.0)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:30"))
    wait_until(lambda: len(fake.uploads) == 2)
    n = len(fake.uploads)
    led.show(PanelContent("16:59", clock=True))   # trou de lecture OCR : l'appli demande l'horloge
    led.show(PanelContent("00:29"))               # lecture revenue avant la fin de la grâce
    time.sleep(0.3)
    assert len(fake.uploads) == n                 # le décompte n'a pas été coupé, aucune horloge envoyée


def test_clock_shown_after_grace_when_countdown_really_stops(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "CLOCK_GRACE_S", 0.3)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:30"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.show(PanelContent("16:59", clock=True))   # l'horloge persiste (course finie)
    wait_until(lambda: len(fake.last_frames) == 1)  # après la grâce, l'horloge s'affiche


def test_zero_is_static(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:00"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert len(fake.last_frames) == 1
    time.sleep(0.2)
    assert len(fake.uploads) == 2


def test_laps_change_resends(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09", "01/20"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.show(PanelContent("00:08", "02/20"))
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == frames_for("00:08", "02/20")


def test_slow_upload_starts_from_predicted_time(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "UPLOAD_OVERHEAD_S", 2.0)   # simule un transfert long (~2 s)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:09"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert fake.last_frames == frames_for("00:07")             # 00:09 moins les 2 s de transfert
    led.show(PanelContent("00:07"))
    time.sleep(0.2)
    assert len(fake.uploads) == 2


def test_laps_hidden_when_disabled(fake):
    p = LedPanel(64, 16, RED_RGB, BLUE_RGB, logging.getLogger("test_led"), show_laps=False)
    try:
        p.connect("192.168.47.1")
        wait_until(lambda: p.status == LedStatus.CONNECTED and fake.uploads)
        p.show(PanelContent("00:03", "03/20"))
        wait_until(lambda: len(fake.uploads) == 2)
        assert fake.last_frames == frames_for("00:03")
        p.show(PanelContent("00:02", "04/20"))
        time.sleep(0.2)
        assert len(fake.uploads) == 2
    finally:
        p.shutdown()


def test_non_numeric_time_is_shown_static(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("--:--"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert len(fake.last_frames) == 1


def test_retries_until_panel_available(led, fake):
    fake.fail_connects = 3
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    assert len(fake.sockets) == 1


def test_reconnects_and_resends_after_drop(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05"))
    wait_until(lambda: len(fake.uploads) == 2)
    fake.sockets[-1].dropped = True
    led.show(PanelContent("00:04", "01/10"))
    wait_until(lambda: len(fake.sockets) == 2 and len(fake.uploads) == 3)
    assert fake.last_frames == frames_for("00:04", "01/10")


def test_disconnect_clears_screen_and_closes(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.disconnect()
    wait_until(lambda: led.status == LedStatus.DISABLED)
    assert fake.last_frames == [Frame()]
    assert fake.sockets[-1].closed


def test_shutdown_blanks_the_panel(fake):
    p = LedPanel(64, 16, RED_RGB, BLUE_RGB, logging.getLogger("test_led"), password=PASSWORD)
    p.connect("192.168.47.1")
    wait_until(lambda: p.status == LedStatus.CONNECTED and fake.uploads)
    p.show(PanelContent("00:05"))
    wait_until(lambda: len(fake.uploads) >= 2)
    p.shutdown()                                  # « quitter » : l'écran est éteint et la connexion fermée
    assert fake.last_frames == [Frame()]          # sinon le panneau bouclerait le dernier décompte
    assert fake.sockets[-1].closed


def test_color_change_resends_current_value(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.set_color((40, 220, 90))
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == frames_for("00:05", rgb=(40, 220, 90))


def test_brightness_change_is_sent(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.set_brightness(16)
    wait_until(lambda: fake.brightness == [7, 16])


def test_heartbeat_detects_dead_link_without_new_content(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "HEARTBEAT_S", 0.05)   # ping rapide pour le test
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    wait_until(lambda: fake.heartbeats >= 1)               # ping émis sans changement d'affichage
    fake.fail_connects = 100                               # le Wi-Fi tombe : les reconnexions échouent aussi
    fake.sockets[-1].dropped = True                        # lien courant coupé, aucun show() derrière
    wait_until(lambda: led.status == LedStatus.RETRYING)   # détecté par le battement de cœur
    n = len(fake.sockets)
    fake.fail_connects = 0                                 # « Wi-Fi revenu »
    wait_until(lambda: len(fake.sockets) > n and fake.sockets[-1].logged_in and led.status == LedStatus.CONNECTED)


def test_set_show_laps_resends_current_content(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05", "03/20"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert fake.last_frames == frames_for("00:05", "03/20")
    led.set_show_laps(False)                                   # temps seul : renvoi immédiat
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == frames_for("00:05")
    led.set_show_laps(True)
    wait_until(lambda: len(fake.uploads) == 4)
    assert fake.last_frames == frames_for("00:05", "03/20")


def test_set_rotate_180_resends_current_content_upside_down(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.show(PanelContent("00:05", "03/20"))
    wait_until(lambda: len(fake.uploads) == 2)
    led.set_rotate_180(True)                                   # panneau retourné : renvoi immédiat
    wait_until(lambda: len(fake.uploads) == 3)
    assert fake.last_frames == [f.rotated_180() for f in frames_for("00:05", "03/20")]
    led.set_rotate_180(False)
    wait_until(lambda: len(fake.uploads) == 4)
    assert fake.last_frames == frames_for("00:05", "03/20")


def test_panel_created_upside_down_renders_rotated(fake):
    p = LedPanel(64, 16, RED_RGB, BLUE_RGB, logging.getLogger("test_led"), password=PASSWORD, rotate_180=True)
    try:
        p.connect("192.168.47.1")
        wait_until(lambda: p.status == LedStatus.CONNECTED and fake.uploads)
        p.show(PanelContent("00:03"))
        wait_until(lambda: len(fake.uploads) == 2)
        assert fake.last_frames == [f.rotated_180() for f in frames_for("00:03")]
    finally:
        p.shutdown()


def test_set_password_reconnects_with_new_password(led, fake):
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    fake.password = "NOUVEAU"                                  # le panneau change de mot de passe
    led.set_password("NOUVEAU")                                # l'appli aussi -> reconnexion immédiate
    wait_until(lambda: len(fake.sockets) == 2 and fake.sockets[-1].logged_in and led.status == LedStatus.CONNECTED)
    assert fake.sockets[0].closed


def test_set_password_while_disconnected_applies_at_next_connect(led, fake):
    fake.password = "AUTRE"
    led.set_password("AUTRE")
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED)
    assert len(fake.sockets) == 1


def test_set_chunk_minutes_changes_next_chunk(led, fake, monkeypatch):
    monkeypatch.setattr(panel_mod, "CHUNK_EXTRA_S", 0)
    led.connect("192.168.47.1")
    wait_until(lambda: led.status == LedStatus.CONNECTED and fake.uploads)
    led.set_chunk_minutes(1)
    led.show(PanelContent("05:00"))
    wait_until(lambda: len(fake.uploads) == 2)
    assert len(fake.last_frames) == 61                         # 1 min de trames (+ trame de départ)


def test_scan_reports_reachable_panel(led, fake):
    assert led.scan(timeout=0.1).result(2) == [("RHX8", protocol.DEFAULT_HOST)]
    fake.fail_connects = 1
    assert led.scan(timeout=0.1).result(2) == []
