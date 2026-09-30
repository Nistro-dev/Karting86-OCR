"""Source directe Apex Timing : décodage des lignes de T1_SESSIONS_V8 (échantillons relevés dans
la base réelle les 27/09 et 30/09/2026) -> lectures, arbitrage source directe / repli OCR, et
intégration avec le suivi de session. Sans Firebird ni réseau."""
from __future__ import annotations

import dataclasses
import datetime
import logging
import time

import pytest

from apex_ocr.readings import seconds_from_time, time_from_seconds
from apex_ocr.session import SessionEvent, SessionState, SessionTracker, StopReason, current_display
from apex_ocr.source import apex_live
from apex_ocr.source.apex_live import (ApexLiveSource, LiveStatus, SessionRow, db_path_for, format_remaining,
                                       from_us, make_reading, pick_live_session, probe_database, remaining_us,
                                       to_us)

US = 1_000_000
# Session test 1 du 30/09/2026 : départ 11:17:02.350, 10 min, pause à 11:20:16.371, reprise après 6,368 s.
START = 3999928622350000
PAUSE_AT = 3999928816371000
RUNNING = SessionRow(idx=1, status=0x10011, start_us=START, pause_us=0, finish_us=0, duration_us=600 * US, laps_total=0)
PAUSED = SessionRow(idx=1, status=0x10005, start_us=START, pause_us=PAUSE_AT, finish_us=0, duration_us=600 * US, laps_total=0)
RESUMED = SessionRow(idx=1, status=0x10011, start_us=START, pause_us=6368000, finish_us=0, duration_us=600 * US, laps_total=0)
# Session du 27/09 : 8:30, finie normalement (CFINISHTIME posé, bit 0x20).
FINISHED = SessionRow(idx=3, status=0x30120, start_us=3999680164773000, pause_us=0, finish_us=3999680675773000,
                      duration_us=510 * US, laps_total=0)
# Ligne « démarrée » mais jamais active ni finie (résidu du 27/09) : à ignorer.
STALE = SessionRow(idx=1, status=0x10010, start_us=3999660316921000, pause_us=0, finish_us=0, duration_us=600 * US, laps_total=0)


def test_timestamps_are_microseconds_since_delphi_epoch():
    assert from_us(START) == datetime.datetime(2026, 9, 30, 11, 17, 2, 350000)
    assert to_us(datetime.datetime(2026, 9, 30, 11, 17, 2, 350000)) == START
    assert db_path_for(r"C:\ApexTiming\Data", datetime.date(2026, 9, 30)) == r"C:\ApexTiming\Data\DAY20260930.GO"


def test_pick_live_session_ignores_stale_finished_and_just_ended():
    assert pick_live_session([STALE, FINISHED]) is None
    assert pick_live_session([STALE, FINISHED, RUNNING]) == RUNNING
    assert pick_live_session([RUNNING], ignore=RUNNING.key) is None          # réécriture ~1 s après un STOP
    later = SessionRow(2, 0x20011, START + 60 * US, 0, 0, 600 * US, 0)
    assert pick_live_session([RUNNING, later]) == later                       # la plus récente


def test_remaining_matches_gokarts_display_rounded_up():
    # Captures du 30/09 : 494,46 s restantes -> GoKarts affiche 08:15 ; 499,55 -> 08:20 ; 489,36 -> 08:10.
    for rem_s, shown in ((494.46, "08:15"), (499.55, "08:20"), (489.36, "08:10"), (0.2, "00:01"), (0, "00:00"), (-3, "00:00")):
        assert format_remaining(int(rem_s * US), False) == shown
    assert format_remaining(7200 * US, True) == "2:00:00"
    assert format_remaining(3599 * US + 1, True) == "1:00:00"
    now = START + int(105.54 * US)
    assert remaining_us(RUNNING, now) == int(494.46 * US)
    r = make_reading(RUNNING, now, None)
    assert (r.time_text, r.laps_done, r.laps_total, r.paused) == ("08:15", None, None, False)
    assert abs(r.remaining_s - 494.46) < 1e-6
    early = make_reading(RUNNING, START - int(0.4 * US), None)   # départ horodaté après l'horloge PC
    assert early.time_text == "10:00" and early.remaining_s == 600.0


def test_pause_freezes_then_resume_accounts_for_accumulated_pause():
    at_pause = remaining_us(RUNNING, PAUSE_AT)
    assert remaining_us(PAUSED, PAUSE_AT + 5 * US) == at_pause                 # 1re pause : gelé au début de pause
    resumed_at = PAUSE_AT + 6368000
    assert remaining_us(RESUMED, resumed_at) == at_pause                       # reprise : cumul déduit
    # 2e pause 30 s après la reprise : CPAUSETIME redevient un horodatage, le cumul (6,368 s) vient de la ligne précédente
    second = SessionRow(1, 0x10005, START, resumed_at + 30 * US, 0, 600 * US, 0)
    assert remaining_us(second, resumed_at + 45 * US, accum_pause_us=6368000) == at_pause - 30 * US
    assert make_reading(PAUSED, PAUSE_AT + 5 * US, None).paused is True


def test_laps_only_when_session_has_a_lap_count():
    laps = SessionRow(4, 0x40011, START, 0, 0, 900 * US, 20)
    r = make_reading(laps, START + 30 * US, 3)
    assert (r.laps_done, r.laps_total, r.time_text) == (3, 20, "14:30")
    assert make_reading(laps, START, None).laps_done == 0                        # aucun passage encore
    assert r.strict().has_laps and r.lenient().laps_done == 3


def test_readings_time_conversions():
    assert seconds_from_time("08:15") == 495 and seconds_from_time("1:02:03") == 3723
    assert seconds_from_time("abc") is None and seconds_from_time("1:2:3:4") is None
    assert time_from_seconds(495, False) == "08:15" and time_from_seconds(3723, True) == "01:02:03"
    assert time_from_seconds(0.2, False, round_up=True) == "00:01" and time_from_seconds(0.2, False) == "00:00"
    assert time_from_seconds(-5, False) == "00:00"


def test_probe_database_reports_missing_file_and_client(tmp_path, monkeypatch):
    clock = lambda: from_us(START)
    assert "absente" in probe_database(str(tmp_path), "localhost", "SYSDBA", "masterkey", clock=clock)
    (tmp_path / "DAY20260930.GO").write_bytes(b"")
    monkeypatch.setattr(apex_live, "FBCLIENT_CANDIDATES", [])
    assert "fbclient.dll" in probe_database(str(tmp_path), "localhost", "SYSDBA", "masterkey", clock=clock)
    report = probe_database(str(tmp_path), "localhost", "SYSDBA", "masterkey", str(tmp_path / "absent.dll"), clock=clock)
    assert report.startswith("échec (")


def test_tracker_round_up_pause_and_forced_stop():
    t = SessionTracker()
    t.round_up = True
    t.on_strict_reading(make_reading(RUNNING, START, None).strict(), now=0.0)
    t.on_strict_reading(make_reading(RUNNING, START + 1 * US, None).strict(), now=1.0)
    assert t.on_strict_reading(make_reading(RUNNING, START + 2 * US, None).strict(), now=2.0) == [SessionEvent.STARTED]
    t.sync_exact(597.6, now=2.0)
    assert t.live_display(2.0).time_text == "09:58"                              # ceil(597.6)
    assert t.live_display(2.7).time_text == "09:57"
    t.set_paused(True, now=3.0)
    frozen = t.live_display(3.0).time_text
    assert t.paused and t.live_display(8.0).time_text == frozen == "09:57"
    t.set_paused(False, now=9.0)
    assert not t.paused and t.live_display(9.0).time_text == frozen        # reprend là où c'était gelé
    assert t.live_display(10.0).time_text == "09:56"
    assert t.force_stop(10.0) == [SessionEvent.STOPPED]
    assert t.state == SessionState.WAITING and t.last_completed.reason == StopReason.SOURCE_ENDED
    assert t.force_stop(11.0) == []                                              # déjà arrêté : sans effet
    assert current_display(t, 11.0).time_text == t.last_completed.time_text


# ---- thread de lecture, base simulée ---------------------------------------------------

class FakeCursor:
    def __init__(self, db):
        self.db, self._rows = db, []

    def execute(self, sql, params=None):
        if sql.startswith("select CIDX"):
            self._rows = [dataclasses.astuple(r) for r in self.db.rows]
        elif sql.startswith("select max(CTLP)"):
            self._rows = [(self.db.max_lap,)]
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


class FakeTransaction:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        if self.db.fail:
            raise ConnectionError("base injoignable")
        return FakeCursor(self.db)

    def rollback(self):
        self.db.rollbacks += 1


class FakeConnection:
    def __init__(self, db):
        self.db = db
        self.closed = False

    def transaction_manager(self, default_tpb=None):
        return FakeTransaction(self.db)

    def close(self):
        self.closed = True


class FakeDb:
    def __init__(self):
        self.rows: list[tuple] = []
        self.max_lap = 0
        self.fail = False
        self.rollbacks = 0
        self.connections: list[FakeConnection] = []


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    db = FakeDb()
    (tmp_path / "DAY20260930.GO").write_bytes(b"")
    monkeypatch.setattr(apex_live, "RETRY_MIN_S", 0.01)
    monkeypatch.setattr(apex_live, "RETRY_MAX_S", 0.02)

    def fake_connect(self):
        if db.fail:
            raise ConnectionError("login refusé")
        con = FakeConnection(db)
        db.connections.append(con)
        self._con = con
        self.db_path = db_path_for(str(tmp_path), datetime.date(2026, 9, 30))
        self._set_status(LiveStatus.CONNECTED)

    def ensure(self):
        if self._con is None:
            fake_connect(self)

    monkeypatch.setattr(ApexLiveSource, "_ensure_connection", ensure)
    monkeypatch.setattr(ApexLiveSource, "_read_only_transaction", lambda self: self._con.transaction_manager())
    return db


def wait_until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition non atteinte")


def make_source(tmp_path, clock):
    return ApexLiveSource(logging.getLogger("test_apex_live"), str(tmp_path), poll_s=0.02, clock=clock)


def test_source_reads_session_then_end_and_ignores_rewrite(fake_db, tmp_path):
    now = {"dt": from_us(START + 10 * US)}
    src = make_source(tmp_path, lambda: now["dt"])
    src.start()
    try:
        wait_until(lambda: src.latest()[1] > 0)
        assert src.latest()[0] is None and src.status == LiveStatus.CONNECTED
        fake_db.rows = [RUNNING]
        wait_until(lambda: src.latest()[0] is not None)
        r, _ = src.latest()
        assert (r.time_text, r.session_idx, r.paused) == ("09:50", 1, False)
        fake_db.rows = [PAUSED]
        now["dt"] = from_us(PAUSE_AT + 3 * US)
        wait_until(lambda: src.latest()[0] is not None and src.latest()[0].paused)
        assert src.latest()[0].time_text == format_remaining(remaining_us(RUNNING, PAUSE_AT), False) == "06:46"
        fake_db.rows = [RESUMED]
        now["dt"] = from_us(PAUSE_AT + 6368000 + 10 * US)                       # reprise + 10 s
        wait_until(lambda: src.latest()[0] is not None and not src.latest()[0].paused)
        assert src.latest()[0].time_text == "06:36"
        fake_db.rows = [SessionRow(1, 0x10005, START, PAUSE_AT + 6368000 + 20 * US, 0, 600 * US, 0)]   # 2e pause à +20 s
        now["dt"] = from_us(PAUSE_AT + 6368000 + 25 * US)
        wait_until(lambda: src.latest()[0] is not None and src.latest()[0].paused)
        assert src.latest()[0].time_text == "06:26"                              # cumul de la 1re pause bien déduit
        fake_db.rows = []                                                        # STOP : ligne remise à zéro
        wait_until(lambda: src.latest()[0] is None)
        fake_db.rows = [RUNNING]                                                 # réécriture fugace de la même session
        time.sleep(0.1)
        assert src.latest()[0] is None
        fresh = SessionRow(2, 0x20011, PAUSE_AT + 60 * US, 0, 0, 600 * US, 0)   # vraie session suivante
        fake_db.rows = [fresh]
        now["dt"] = from_us(PAUSE_AT + 61 * US)
        wait_until(lambda: src.latest()[0] is not None and src.latest()[0].session_idx == 2)
        assert fake_db.rollbacks > 0                                             # chaque lecture est refermée
    finally:
        src.stop()
    assert src.status == LiveStatus.DISABLED


def test_source_retries_and_reports_detail(fake_db, tmp_path):
    fake_db.fail = True
    src = make_source(tmp_path, lambda: from_us(START))
    src.start()
    try:
        wait_until(lambda: src.status == LiveStatus.RETRYING)
        assert "login refusé" in src.status_detail
        assert src.latest() == (None, 0.0)
        fake_db.fail = False
        wait_until(lambda: src.status == LiveStatus.CONNECTED and src.latest()[1] > 0)
    finally:
        src.stop()


def test_source_reconnects_when_a_poll_fails(fake_db, tmp_path):
    fake_db.rows = [RUNNING]
    src = make_source(tmp_path, lambda: from_us(START + 5 * US))
    src.start()
    try:
        wait_until(lambda: src.latest()[0] is not None)
        n = len(fake_db.connections)
        fake_db.fail = True
        wait_until(lambda: src.status == LiveStatus.RETRYING)
        assert src.latest()[0] is None and fake_db.connections[-1].closed
        fake_db.fail = False
        wait_until(lambda: len(fake_db.connections) > n and src.latest()[0] is not None)
    finally:
        src.stop()
