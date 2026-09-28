"""Pilotage Wi-Fi du panneau LED RHX8 (voir protocol.py / rendering.py).

Un thread dédié gère connexion, reconnexion et envoi ; le thread Tk ne fait
que déposer le contenu *voulu*. Le panneau ne sait pas mettre à jour une trame
à la volée sans clignoter : on lui envoie donc, au départ de la course, **un
programme contenant toutes les trames du décompte** (1 trame ≈ 1 s), qu'il joue
tout seul. Ensuite on ne renvoie quelque chose que si le temps demandé s'écarte
de la séquence en cours (resynchronisation), si les tours changent, si le chrono
s'arrête (image fixe), ou pour vider l'écran (fin / annulation de la course).

Le panneau repart du début d'un programme au bout de ~4 min : le décompte est
donc envoyé par tranches (2 min par défaut, avec 10 s de trames de réserve), la
tranche suivante partant du temps *prévu* à la fin de son transfert. Chaque
envoi provoque un bref clignotement, d'où des tranches aussi longues que possible.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum, auto
from typing import Optional

from apex_ocr.led import protocol
from apex_ocr.led.content import PanelContent
from apex_ocr.led.rendering import (Frame, TimerRenderer, blank_frame, build_program, color_index,
                                    format_like, parse_seconds, program_length, program_size)

CONNECT_TIMEOUT_S = 5.0
IO_TIMEOUT_S = 30.0
HEARTBEAT_S = 4.0             # ping régulier : détecte un lien mort (Wi-Fi coupé) sans attendre un changement d'affichage
HEARTBEAT_TIMEOUT_S = 3.0     # le ping n'attend pas 30 s si le panneau ne répond plus
RETRY_MIN_S = 2.0
RETRY_MAX_S = 5.0    # on retente souvent : après une coupure, la carte RHX8 garde son ancienne connexion un moment et il faut saisir le créneau dès qu'il se libère
SHUTDOWN_TIMEOUT_S = 3.0
RESYNC_TOLERANCE_S = 2         # écart toléré entre le temps demandé et la séquence en cours
FROZEN_S = 2.5                 # valeur OCR inchangée depuis ce délai = chrono arrêté -> image fixe
CLOCK_GRACE_S = 6.0            # pendant un décompte, un passage transitoire à l'horloge (trou de lecture OCR) est ignoré ce temps
DEFAULT_CHUNK_MIN = 2          # le panneau repart du début après ~4 min : décompte envoyé par tranches
CHUNK_EXTRA_S = 10             # trames de réserve au-delà de la tranche, le temps d'envoyer la suivante
UPLOAD_RATE_DEFAULT = 120_000  # octets/s (mesuré : 349 Ko en 2,9 s), affiné à chaque envoi
UPLOAD_OVERHEAD_S = 0.3

_UNSENT = object()


class LedStatus(Enum):
    DISABLED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RETRYING = auto()


class _Sequence:
    """Décompte joué par le panneau : ``secs0`` à l'instant ``t0``, ``n`` trames ; la tranche
    suivante est à envoyer ``renew_at`` secondes après ``t0`` (None = dernière tranche)."""

    def __init__(self, secs0: int, t0: float, n: int, template: str, laps: Optional[str],
                 renew_at: Optional[float] = None, alert_below: Optional[int] = None):
        self.secs0, self.t0, self.n, self.template, self.laps = secs0, t0, n, template, laps
        self.renew_at = renew_at
        self.alert_below = alert_below   # les trames à ce nombre de secondes ou moins sont en couleur d'alerte

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    @property
    def static(self) -> bool:
        return self.n == 1

    def expected(self) -> int:
        return self.secs0 if self.static else max(0, self.secs0 - int(self.elapsed()))

    def alert_at(self, secs: int) -> bool:
        return self.alert_below is not None and secs <= self.alert_below

    def exhausted(self) -> bool:
        return self.renew_at is not None and self.elapsed() >= self.renew_at


class LedPanel:
    def __init__(self, width: int, height: int, rgb: tuple, alert_rgb: tuple, logger: logging.Logger, *,
                 password: str = protocol.DEFAULT_PASSWORD, brightness: int = 12,
                 show_laps: bool = True, resync_minutes: int = DEFAULT_CHUNK_MIN):
        self._renderer = TimerRenderer(width, height, rgb)
        self._alert_rgb = tuple(alert_rgb)
        self._logger = logger
        self._password = password
        self._brightness = max(1, min(16, int(brightness)))
        self._show_laps = show_laps
        self._chunk_s = max(1, min(60, int(resync_minutes or DEFAULT_CHUNK_MIN))) * 60

        self.status = LedStatus.DISABLED
        self.status_detail = ""

        self._lock = threading.Condition()
        self._host: Optional[str] = None
        self._desired: Optional[PanelContent] = None
        self._desired_since = time.monotonic()
        self._brightness_dirty = True
        self._wake = False

        self._sock: Optional[socket.socket] = None
        self._sent: object = _UNSENT          # contenu (ou None) matérialisé par le programme envoyé
        self._seq: Optional[_Sequence] = None
        self._clock_since: Optional[float] = None   # depuis quand l'horloge est demandée (anti-flash)
        self._last_io = 0.0                   # dernier échange réussi (pour cadencer le battement de cœur)
        self._upload_rate = float(UPLOAD_RATE_DEFAULT)
        self._last_requested: object = _UNSENT
        self._stopping = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="led-probe")
        self._thread = threading.Thread(target=self._run, daemon=True, name="led-panel")
        self._thread.start()

    # ---- API (thread-safe, appelée depuis Tk) -----------------------------

    def connect(self, host: str) -> None:
        self._set(host=(host or "").strip() or None)

    def disconnect(self) -> None:
        self._set(host=None)

    def show(self, content: Optional[PanelContent]) -> None:
        """Contenu voulu (``None`` = écran vide)."""
        if content == self._last_requested:
            return
        prev = self._last_requested
        self._last_requested = content
        now = time.monotonic()
        with self._lock:
            self._desired = content
            self._desired_since = now
            # Début d'une demande d'horloge (pour la grâce anti-flash) : on note l'instant
            # où l'on est passé du décompte à l'horloge, pas chaque rafraîchissement de l'heure.
            if content is not None and content.clock:
                if not (isinstance(prev, PanelContent) and prev.clock):
                    self._clock_since = now
            else:
                self._clock_since = None
            self._wake = True
            self._lock.notify()

    def set_color(self, rgb: tuple) -> None:
        with self._lock:
            self._renderer.rgb = tuple(rgb)
            self._sent = _UNSENT
            self._wake = True
            self._lock.notify()

    def set_alert_color(self, rgb: tuple) -> None:
        with self._lock:
            self._alert_rgb = tuple(rgb)
            self._sent = _UNSENT
            self._wake = True
            self._lock.notify()

    def set_brightness(self, level: int) -> None:
        with self._lock:
            self._brightness = max(1, min(16, int(level)))
            self._brightness_dirty = True
            self._wake = True
            self._lock.notify()

    def scan(self, timeout: float = 3.0) -> Future:
        """Future -> [(nom, hôte)] si le panneau répond sur le réseau."""
        host = self._host or protocol.DEFAULT_HOST
        return self._pool.submit(self._probe, host, timeout)

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            self._host = None
            self._wake = True
            self._lock.notify()
        self._thread.join(SHUTDOWN_TIMEOUT_S)
        self._pool.shutdown(wait=False)

    # ---- interne -----------------------------------------------------------

    def _set(self, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(self, "_" + k, v)
            self._wake = True
            self._lock.notify()

    def _set_status(self, status: LedStatus, detail: str = "") -> None:
        if status != self.status:
            self._logger.info("Panneau LED : %s%s", status.name, f" ({detail})" if detail else "")
        self.status = status
        self.status_detail = detail

    def _wait_wake(self, timeout: Optional[float] = None) -> None:
        with self._lock:
            if not self._wake:
                self._lock.wait(timeout)
            self._wake = False

    @staticmethod
    def _probe(host: str, timeout: float) -> list[tuple[str, str]]:
        h, p = _split_host(host)
        try:
            with socket.create_connection((h, p), timeout):
                return [("RHX8", host)]
        except OSError:
            return []

    def _run(self) -> None:
        backoff = RETRY_MIN_S
        while not self._stopping:
            try:
                host = self._host
                if host is None:
                    self._blank_and_close()
                    self._set_status(LedStatus.DISABLED)
                    self._wait_wake()
                    continue
                if self._sock is None:
                    self._set_status(LedStatus.CONNECTING if backoff == RETRY_MIN_S else LedStatus.RETRYING,
                                     self.status_detail)
                    try:
                        self._open(host)
                    except Exception as exc:
                        self._close()
                        self._set_status(LedStatus.RETRYING, str(exc) or type(exc).__name__)
                        self._wait_wake(backoff)
                        backoff = min(backoff * 2, RETRY_MAX_S)
                        continue
                    backoff = RETRY_MIN_S
                    self._set_status(LedStatus.CONNECTED)

                if self._brightness_dirty:
                    self._send_brightness()
                if self._needs_send():
                    self._send_content(self._desired)
                elif time.monotonic() - self._last_io >= HEARTBEAT_S:
                    self._heartbeat()
                else:
                    self._wait_wake(1.0)
            except Exception as exc:
                self._logger.warning("Panneau LED : envoi échoué (%s)", exc)
                self._set_status(LedStatus.RETRYING, str(exc) or type(exc).__name__)
                self._close()
        self._blank_and_close()

    # ---- décision d'envoi ---------------------------------------------------

    def _frozen(self) -> bool:
        """Le temps demandé n'a pas changé depuis FROZEN_S : le chrono est arrêté (pause, fin)."""
        return time.monotonic() - self._desired_since >= FROZEN_S

    def _playing_countdown(self) -> bool:
        return self._seq is not None and not self._seq.static

    def _needs_send(self) -> bool:
        target = self._desired
        if self._sent is _UNSENT:
            return True
        # Anti-flash : le panneau joue le décompte tout seul ; un passage transitoire à
        # l'horloge (trou de lecture OCR) est ignoré quelques secondes — on ne coupe pas
        # le décompte pour afficher l'heure puis le renvoyer aussitôt.
        if (target is not None and target.clock and self._playing_countdown()
                and self._clock_since is not None and time.monotonic() - self._clock_since < CLOCK_GRACE_S):
            return False
        if target is None or self._sent is None:
            return target != self._sent
        return self._sequence_deviates(target)

    def _sequence_deviates(self, target: PanelContent) -> bool:
        sent = self._sent
        laps = target.laps_text if self._show_laps else None
        if laps != (sent.laps_text if self._show_laps else None):
            return True
        seq = self._seq
        if seq is None:
            return target.time_text != sent.time_text
        want = parse_seconds(target.time_text)
        if want is None or target.time_text.count(":") != seq.template.count(":"):
            return True
        if seq.static:
            return want != seq.secs0 or target.alert != sent.alert   # le chrono repart / alerte -> renvoyer
        if self._frozen():
            return True                              # le chrono s'est arrêté -> image fixe
        if abs(want - seq.expected()) > RESYNC_TOLERANCE_S:
            return True
        if target.alert != seq.alert_at(want):
            return True                              # alerte pas prévue dans les trames (tours, seuil modifié)
        return seq.exhausted()                       # tranche finie -> envoyer la suivante

    # ---- I/O ----------------------------------------------------------------

    def _open(self, host: str) -> None:
        h, p = _split_host(host)
        sock = socket.create_connection((h, p), CONNECT_TIMEOUT_S)
        sock.settimeout(IO_TIMEOUT_S)
        self._sock = sock
        reply = self._xfer(protocol.hello_packet())
        if not protocol.is_challenge(reply):
            raise ConnectionError("pas de défi de login (%s)" % reply.hex())
        reply = self._xfer(protocol.login_packet(protocol.challenge_nonce(reply), self._password))
        if not protocol.is_login_ok(reply):
            raise ConnectionError("login refusé (mot de passe ?)")
        self._sent = _UNSENT
        self._seq = None
        self._last_io = time.monotonic()
        self._brightness_dirty = True

    def _xfer(self, packet: bytes) -> bytes:
        if self._sock is None:
            raise ConnectionError("non connecté")
        self._sock.sendall(packet)
        reply = self._sock.recv(64)
        if not reply:
            raise ConnectionError("connexion fermée")
        self._last_io = time.monotonic()
        return reply

    def _heartbeat(self) -> None:
        """Vérifie que le lien est vivant ; en cas d'échec, l'exception fait passer le
        panneau en RETRYING (traité dans _run), ce qui déclenche la reconnexion."""
        self._sock.settimeout(HEARTBEAT_TIMEOUT_S)
        try:
            self._xfer(protocol.status_packet())
        finally:
            if self._sock is not None:
                self._sock.settimeout(IO_TIMEOUT_S)

    def _send_brightness(self) -> None:
        reply = self._xfer(protocol.brightness_packet(self._brightness))
        if not protocol.is_upload_done(reply):
            raise ConnectionError("luminosité refusée (%s)" % reply.hex())
        self._brightness_dirty = False

    def _send_content(self, content: Optional[PanelContent]) -> None:
        if content is None:
            self._upload([blank_frame()])
            self._sent, self._seq = None, None
            return
        laps = content.laps_text if self._show_laps else None
        secs = parse_seconds(content.time_text)
        alert_color = color_index(self._alert_rgb)
        if secs is None or secs == 0 or content.clock or self._frozen():
            color = alert_color if content.alert else None
            self._upload([self._renderer.render(content.time_text, laps, color)])
            self._sent = content
            self._seq = None if secs is None else _Sequence(secs, time.monotonic(), 1, content.time_text, laps)
            self._logger.info("Panneau LED : affiche %s (fixe)", content.time_text)
            return
        # Le panneau démarre la séquence à la fin du transfert : on part du temps prévu à cet instant.
        span = self._chunk_s + CHUNK_EXTRA_S
        delay = round(program_size(min(secs, span) + 1) / self._upload_rate + UPLOAD_OVERHEAD_S)
        start = max(0, secs - delay)
        last = start <= span
        alert_below = start if content.alert else content.alert_below   # déjà en alerte : toutes les trames
        frames = self._renderer.countdown(format_like(start, content.time_text), laps, max_frames=span + 1,
                                          alert_below=alert_below, alert_color=alert_color)
        t = time.monotonic()
        size = self._upload(frames)
        t0 = time.monotonic()
        if t0 - t > 0.5:
            self._upload_rate = size / (t0 - t)
        self._sent = content
        self._seq = _Sequence(start, t0, len(frames), content.time_text, laps,
                              None if last else self._chunk_s, alert_below)
        self._logger.info("Panneau LED : décompte envoyé depuis %s (%d trames%s, %.1f s de transfert)",
                          format_like(start, content.time_text), len(frames),
                          "" if last else ", suite dans %d s" % self._chunk_s, t0 - t)

    def _upload(self, frames: list[Frame]) -> int:
        program = build_program(frames)
        reply = self._xfer(protocol.upload_header(program_length(program)))
        if not protocol.is_upload_accepted(reply):
            raise ConnectionError("transfert refusé (%s)" % reply.hex())
        reply = self._xfer(program)
        if not protocol.is_upload_done(reply):
            raise ConnectionError("programme refusé (%s)" % reply.hex())
        return len(program)

    def _close(self) -> None:
        sock, self._sock = self._sock, None
        self._sent = _UNSENT
        self._seq = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _blank_and_close(self) -> None:
        if self._sock is not None and self._sent is not None:
            try:
                self._send_content(None)
            except Exception:
                pass
        self._close()


def _split_host(host: str) -> tuple[str, int]:
    if ":" in host:
        h, p = host.rsplit(":", 1)
        return h, int(p)
    return host, protocol.DEFAULT_PORT
