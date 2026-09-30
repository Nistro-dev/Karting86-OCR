"""Source directe : la session en cours lue dans la base Firebird de GoKarts / GoServer
(Apex Timing), sans OCR. Voir ``docs/apex_findings.md`` pour ce qui a été trouvé.

- Une base par jour : ``<apex_data_dir>\\DAYAAAAMMJJ.GO`` (créée par GoKarts à son lancement).
- Table ``T1_SESSIONS_V8`` : ``CSTARTTIME`` / ``CPAUSETIME`` / ``CFINISHTIME`` en microsecondes depuis
  le 30/12/1899 (TDateTime Delphi, heure locale du PC), ``CDURATION`` en microsecondes, ``CLAPS``
  tours de la session (0 = au temps), ``CSTATUS`` = ``CIDX << 16`` + bits d'état.
- Pendant une pause, ``CPAUSETIME`` est l'horodatage du début de pause ; après reprise, c'est le
  cumul des pauses. Un arrêt manuel remet la ligne à « non démarrée » (``CSTARTTIME = 0``) ; une fin
  normale pose ``CFINISHTIME`` et le bit « terminée ».
- Tours : ``max(CTLP)`` de ``T1_S<CIDX>_RC`` (le leader).
- GoKarts affiche le temps restant arrondi **au supérieur**.

Tout est en **lecture seule** (transactions read-only) ; un thread dédié interroge la base
toutes les ``poll_s`` secondes et se reconnecte tout seul (base du jour absente, GoServer
redémarré, mot de passe changé...). Le thread Tk ne fait que lire ``latest()``.
"""
from __future__ import annotations

import datetime
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from apex_ocr.readings import LenientReading, StrictReading

EPOCH = datetime.datetime(1899, 12, 30)
US = 1_000_000
STATUS_ACTIVE = 0x01     # chrono qui tourne (ou en pause, avec STATUS_PAUSED)
STATUS_PAUSED = 0x04
STATUS_STARTED = 0x10
STATUS_FINISHED = 0x20
FBCLIENT_CANDIDATES = [
    r"C:\Program Files\Firebird\Firebird_5_0\fbclient.dll",
    r"C:\Program Files\Firebird\Firebird_4_0\fbclient.dll",
    r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll",
    r"C:\Windows\System32\fbclient.dll",
]
RETRY_MIN_S = 2.0
RETRY_MAX_S = 15.0
SESSIONS_SQL = ("select CIDX, CSTATUS, CSTARTTIME, CPAUSETIME, CFINISHTIME, CDURATION, CLAPS "
                "from T1_SESSIONS_V8 where CSTARTTIME > 0")


class LiveStatus(Enum):
    DISABLED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RETRYING = auto()


@dataclass(frozen=True)
class SessionRow:
    idx: int
    status: int
    start_us: int
    pause_us: int
    finish_us: int
    duration_us: int
    laps_total: int

    @property
    def active(self) -> bool:
        return bool(self.status & STATUS_ACTIVE) and self.start_us > 0 and self.finish_us == 0

    @property
    def paused(self) -> bool:
        return bool(self.status & STATUS_PAUSED)

    @property
    def key(self) -> tuple[int, int]:
        """Identité d'une session démarrée : même ligne + même heure de départ."""
        return self.idx, self.start_us


@dataclass(frozen=True)
class LiveReading:
    """Ce que la base dit de la session en cours, dans les formats de l'OCR
    (``MM:SS`` / ``H:MM:SS``, ``NN/NN``) plus le restant exact en secondes."""
    time_text: str
    remaining_s: float
    laps_done: Optional[int]
    laps_total: Optional[int]
    paused: bool
    session_idx: int
    start_us: int

    def strict(self) -> StrictReading:
        return StrictReading(time_text=self.time_text, laps_done=self.laps_done, laps_total=self.laps_total)

    def lenient(self) -> LenientReading:
        return LenientReading(time_text=self.time_text, laps_done=self.laps_done, laps_total=self.laps_total)


# ---- logique pure (testée sans Firebird) ----------------------------------------------

def to_us(dt: datetime.datetime) -> int:
    return int((dt - EPOCH).total_seconds() * US)


def from_us(us: int) -> datetime.datetime:
    return EPOCH + datetime.timedelta(microseconds=us)


def db_path_for(data_dir: str, day: datetime.date) -> str:
    return os.path.join(data_dir, "DAY%s.GO" % day.strftime("%Y%m%d"))


def find_fbclient(explicit: str = "") -> str:
    """fbclient.dll 64 bits : chemin explicite, sinon les emplacements standard du serveur Firebird."""
    if explicit:
        return explicit
    for path in FBCLIENT_CANDIDATES:
        if os.path.exists(path):
            return path
    return ""


def pick_live_session(rows: list[SessionRow], ignore: Optional[tuple[int, int]] = None) -> Optional[SessionRow]:
    """La session en cours : active, démarrée, non finie ; la plus récente si plusieurs.
    ``ignore`` = la session qui vient de se terminer (GoKarts la réécrit parfois ~1 s après
    un arrêt manuel avant de la remettre à zéro : ne pas la « redémarrer » pour autant)."""
    live = [r for r in rows if r.active and r.key != ignore]
    if not live:
        return None
    return max(live, key=lambda r: r.start_us)


def remaining_us(row: SessionRow, now_us: int, accum_pause_us: int = 0) -> int:
    """Temps restant en µs (peut être négatif juste avant que GoKarts clôture).
    En pause, ``CPAUSETIME`` est le début de la pause en cours et ``accum_pause_us`` le cumul
    des pauses précédentes (dernier ``CPAUSETIME`` vu hors pause) ; hors pause, ``CPAUSETIME``
    est ce cumul."""
    if row.paused:
        return row.duration_us - (row.pause_us - row.start_us - accum_pause_us)
    return row.duration_us - (now_us - row.start_us - row.pause_us)


def format_remaining(us: int, with_hours: bool) -> str:
    """Comme GoKarts : arrondi au supérieur, ``MM:SS`` ou ``H:MM:SS``."""
    secs = max(0, math.ceil(us / US))
    if with_hours:
        return "%d:%02d:%02d" % (secs // 3600, secs % 3600 // 60, secs % 60)
    return "%02d:%02d" % (secs // 60, secs % 60)


def make_reading(row: SessionRow, now_us: int, laps_done: Optional[int], accum_pause_us: int = 0) -> LiveReading:
    rem = remaining_us(row, now_us, accum_pause_us)
    with_hours = row.duration_us >= 3600 * US
    has_laps = row.laps_total > 0
    return LiveReading(
        time_text=format_remaining(rem, with_hours),
        remaining_s=max(0.0, rem / US),
        laps_done=(laps_done or 0) if has_laps else None,
        laps_total=row.laps_total if has_laps else None,
        paused=row.paused,
        session_idx=row.idx,
        start_us=row.start_us,
    )


def probe_database(data_dir: str, host: str, user: str, password: str, fbclient_path: str = "",
                   clock: Callable[[], datetime.datetime] = datetime.datetime.now) -> str:
    """Ouverture ponctuelle de la base du jour (lecture seule) : compte rendu lisible."""
    path = db_path_for(data_dir, clock().date())
    if not os.path.exists(path):
        return f"base du jour absente ({path}) — GoKarts n'a pas encore été lancé aujourd'hui ?"
    client = find_fbclient(fbclient_path)
    if not client:
        return "fbclient.dll 64 bits introuvable (serveur Firebird installé ? sinon renseigner apex_fbclient_path)"
    try:
        from firebird.driver import Isolation, TraAccessMode, connect, driver_config, tpb
        driver_config.fb_client_library.value = client
        con = connect(f"{host}:{path}", user=user, password=password)
        try:
            tra = con.transaction_manager(default_tpb=tpb(isolation=Isolation.READ_COMMITTED,
                                                          access_mode=TraAccessMode.READ))
            cur = tra.cursor()
            cur.execute(SESSIONS_SQL)
            rows = [SessionRow(*[int(v or 0) for v in r]) for r in cur.fetchall()]
            tra.rollback()
        finally:
            con.close()
    except Exception as exc:
        return f"échec ({str(exc).strip().splitlines()[0][:160] or type(exc).__name__})"
    live = pick_live_session(rows)
    state = (f"session {live.idx} en cours ({format_remaining(remaining_us(live, to_us(clock())), live.duration_us >= 3600 * US)} restant)"
             if live else "aucune session en cours")
    return f"OK — {os.path.basename(path)}, {len(rows)} session(s) démarrée(s) aujourd'hui, {state}."


# ---- thread de lecture -------------------------------------------------------------

class ApexLiveSource:
    def __init__(self, logger: logging.Logger, data_dir: str, host: str = "localhost", user: str = "SYSDBA",
                 password: str = "masterkey", fbclient_path: str = "", poll_s: float = 0.5,
                 clock: Callable[[], datetime.datetime] = datetime.datetime.now):
        self._log = logger
        self._data_dir, self._host, self._user, self._password = data_dir, host, user, password
        self._fbclient = fbclient_path
        self._poll_s = max(0.1, poll_s)
        self._clock = clock
        self.status = LiveStatus.DISABLED
        self.status_detail = ""
        self.db_path = ""
        self._lock = threading.Lock()
        self._latest: Optional[LiveReading] = None
        self._last_ok = 0.0
        self._con = None
        self._ended: Optional[tuple[int, int]] = None
        self._current: Optional[tuple[int, int]] = None
        self._accum_pause_us = 0   # cumul des pauses vu hors pause (pour une 2e pause)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="apex-live")

    # -- API (thread Tk) --

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(self._poll_s + 5.0)

    def latest(self) -> tuple[Optional[LiveReading], float]:
        """(dernière lecture ou None si aucune session en cours, instant monotonic de la
        dernière interrogation réussie — 0 tant qu'aucune)."""
        with self._lock:
            return self._latest, self._last_ok

    # -- interne --

    def _set_status(self, status: LiveStatus, detail: str = "") -> None:
        if status != self.status or detail != self.status_detail:
            self._log.log(logging.WARNING if status == LiveStatus.RETRYING else logging.INFO,
                          "Base Apex Timing : %s%s", status.name, f" ({detail})" if detail else "")
        self.status, self.status_detail = status, detail

    def _run(self) -> None:
        backoff = RETRY_MIN_S
        while not self._stop.is_set():
            try:
                self._ensure_connection()
                self._poll()
                backoff = RETRY_MIN_S
                self._stop.wait(self._poll_s)
            except Exception as exc:
                self._close()
                with self._lock:
                    self._latest = None
                self._set_status(LiveStatus.RETRYING, str(exc).strip().splitlines()[0][:160] or type(exc).__name__)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, RETRY_MAX_S)
        self._close()
        self._set_status(LiveStatus.DISABLED)

    def _ensure_connection(self) -> None:
        path = db_path_for(self._data_dir, self._clock().date())
        if self._con is not None and path == self.db_path:
            return
        self._close()
        if not os.path.exists(path):
            raise FileNotFoundError(f"base du jour absente : {path} (GoKarts pas encore lancé ?)")
        from firebird.driver import connect, driver_config   # import tardif : dépendance optionnelle
        client = find_fbclient(self._fbclient)
        if not client:
            raise FileNotFoundError("fbclient.dll 64 bits introuvable (serveur Firebird installé ?)")
        driver_config.fb_client_library.value = client
        self._set_status(LiveStatus.CONNECTING)
        self._con = connect(f"{self._host}:{path}", user=self._user, password=self._password)
        self.db_path = path
        self._set_status(LiveStatus.CONNECTED)
        self._log.info("Base Apex Timing ouverte en lecture seule : %s", path)

    def _close(self) -> None:
        con, self._con = self._con, None
        self.db_path = ""
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    def _read_only_transaction(self):
        from firebird.driver import Isolation, TraAccessMode, tpb
        return self._con.transaction_manager(default_tpb=tpb(isolation=Isolation.READ_COMMITTED,
                                                             access_mode=TraAccessMode.READ))

    def _poll(self) -> None:
        tra = self._read_only_transaction()
        try:
            cur = tra.cursor()
            cur.execute(SESSIONS_SQL)
            rows = [SessionRow(*[int(v or 0) for v in r]) for r in cur.fetchall()]
            live = pick_live_session(rows, ignore=self._ended)
            laps_done = None
            if live is not None and live.laps_total > 0:
                cur.execute("select max(CTLP) from T1_S%d_RC" % live.idx)
                laps_done = cur.fetchone()[0]
        finally:
            tra.rollback()
        now_us = to_us(self._clock())
        reading = None
        if live is not None:
            if live.key != self._current:
                self._current = live.key
                self._accum_pause_us = 0
                self._log.info("Session %d démarrée à %s (durée %s, tours %d)", live.idx,
                               from_us(live.start_us).strftime("%H:%M:%S"),
                               format_remaining(live.duration_us, live.duration_us >= 3600 * US), live.laps_total)
            if not live.paused:
                self._accum_pause_us = live.pause_us
            reading = make_reading(live, now_us, laps_done, self._accum_pause_us)
        elif self._current is not None:
            self._log.info("Session %d terminée ou remise à zéro dans Apex Timing", self._current[0])
            self._ended, self._current, self._accum_pause_us = self._current, None, 0
        with self._lock:
            self._latest = reading
            self._last_ok = time.monotonic()
