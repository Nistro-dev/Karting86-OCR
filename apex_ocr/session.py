"""Machine à états d'une session de course.

waiting -> armed -> running -> (stop) -> waiting

- Le départ n'est confirmé que si le temps observé DIMINUE, et ce sur
  ``REQUIRED_CONFIRMATIONS`` lectures de suite (pas une seule) : une frame
  OCR bruitée peut faire lire une valeur ponctuellement plus basse sur un
  timer pourtant à l'arrêt, une seule lecture ne suffit donc pas.
- Une fois en course, le temps affiché suit une horloge interne fluide,
  resynchronisée discrètement seulement si l'écart avec l'OCR dépasse la
  tolérance. Les tours, eux, sont mis à jour immédiatement à chaque lecture.
  Une remontée du temps au-delà de la tolérance, confirmée sur
  ``REQUIRED_CONFIRMATIONS`` lectures de suite, est traitée comme une
  annulation (cf. ``StopReason.CANCELLED``) plutôt qu'une resynchro.
- L'arrêt est déclenché par : temps à zéro, tours au total, ou perte de
  lecture OCR prolongée (filet de sécurité, basé sur une vraie durée sans
  lecture valide plutôt qu'un nombre de sondages ratés : une lecture rejetée
  ponctuellement ne doit pas couper une course qui se déroule normalement).
  Après arrêt, l'état repart aussitôt en attente d'un nouveau départ
  (réarmement automatique) ; la dernière valeur reste disponible via
  ``last_completed`` pour l'affichage.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from apex_ocr.ocr.parsing import LenientReading, StrictReading, seconds_from_time, time_from_seconds

OCR_LOST_TIMEOUT_SECONDS = 10.0
REQUIRED_CONFIRMATIONS = 2


class SessionState(Enum):
    WAITING = auto()
    ARMED = auto()
    RUNNING = auto()


class StopReason(Enum):
    TIME_ZERO = auto()
    LAPS_COMPLETE = auto()
    OCR_LOST = auto()
    CANCELLED = auto()


class SessionEvent(Enum):
    ARMED = auto()
    STARTED = auto()
    LAPS_UPDATED = auto()
    RESYNCED = auto()
    STOPPED = auto()


@dataclass(frozen=True)
class CompletedResult:
    time_text: str
    laps_done: Optional[int]
    laps_total: Optional[int]
    reason: StopReason


@dataclass(frozen=True)
class LiveDisplay:
    time_text: str
    laps_done: Optional[int]
    laps_total: Optional[int]


@dataclass(frozen=True)
class DisplayValue:
    """Valeur unique à afficher (UI principale et affichage externe) : en direct,
    figée sur le dernier résultat, ou placeholder si rien n'a encore été vu."""

    time_text: str
    laps_done: Optional[int]
    laps_total: Optional[int]
    is_live: bool


class SessionTracker:
    def __init__(
        self,
        resync_tolerance_seconds: int = 3,
        ocr_lost_timeout_seconds: float = OCR_LOST_TIMEOUT_SECONDS,
        required_confirmations: int = REQUIRED_CONFIRMATIONS,
    ):
        self.resync_tolerance_seconds = resync_tolerance_seconds
        self.ocr_lost_timeout_seconds = ocr_lost_timeout_seconds
        self.required_confirmations = required_confirmations
        self.state = SessionState.WAITING
        self.last_completed: Optional[CompletedResult] = None

        self._with_hours = False
        self._has_laps = False
        self._laps_done: Optional[int] = None
        self._laps_total: Optional[int] = None
        self._pending_seconds: Optional[int] = None
        self._decrease_streak = 0
        self._cancel_streak = 0
        self._cancel_candidate: Optional[float] = None
        self._session_start_wall: Optional[float] = None
        self._session_start_seconds: int = 0
        self._last_good_time_wall: Optional[float] = None

    @property
    def has_laps(self) -> bool:
        return self._has_laps

    def reset(self) -> None:
        self.state = SessionState.WAITING
        self._pending_seconds = None
        self._decrease_streak = 0
        self._cancel_streak = 0
        self._cancel_candidate = None
        self._session_start_wall = None
        self._last_good_time_wall = None
        self._laps_done = None
        self._laps_total = None
        self._has_laps = False

    def on_strict_reading(self, reading: Optional[StrictReading], now: float) -> list[SessionEvent]:
        """Lecture stricte : utilisée tant qu'on n'est pas encore ``RUNNING``."""
        if self.state == SessionState.RUNNING or reading is None:
            return []

        seconds = seconds_from_time(reading.time_text)
        if seconds is None:
            return []

        self._apply_time_format(reading.time_text)
        # La présence des tours suit elle aussi la dernière lecture valide,
        # comme le format horaire : pas figée sur la toute première lecture
        # d'armement (qui peut avoir raté le "/tt" ce coup-ci).
        self._has_laps = reading.has_laps
        self._laps_done = reading.laps_done
        self._laps_total = reading.laps_total

        if self.state == SessionState.WAITING:
            self.state = SessionState.ARMED
            self._pending_seconds = seconds
            self._decrease_streak = 0
            return [SessionEvent.ARMED]

        # ARMED
        if seconds < self._pending_seconds:
            self._pending_seconds = seconds
            self._decrease_streak += 1
            if self._decrease_streak >= self.required_confirmations:
                self._start(reading, seconds, now)
                return [SessionEvent.STARTED]
            return []
        if seconds > self._pending_seconds:
            # Une remontée annule la progression : probablement du bruit OCR
            # ponctuel, ou le timer n'a en fait pas encore vraiment démarré.
            self._pending_seconds = seconds
            self._decrease_streak = 0
        return []

    def _apply_time_format(self, time_text: str) -> None:
        """Le format (mm:ss / hh:mm:ss) suit la dernière lecture valide : pas
        figé pour toute la session, car Apex Timing peut afficher/masquer les
        heures selon la valeur (ex: repasse en mm:ss sous 1h)."""
        self._with_hours = time_text.count(":") == 2

    def _start(self, reading: StrictReading, seconds: int, now: float) -> None:
        self.state = SessionState.RUNNING
        self._session_start_wall = now
        self._session_start_seconds = seconds
        self._has_laps = reading.has_laps
        self._laps_done = reading.laps_done
        self._laps_total = reading.laps_total
        self._last_good_time_wall = now
        self._cancel_streak = 0
        self._cancel_candidate = None

    def on_lenient_reading(self, reading: LenientReading, now: float) -> list[SessionEvent]:
        """Lecture tolérante : utilisée pendant ``RUNNING``."""
        if self.state != SessionState.RUNNING:
            return []

        events: list[SessionEvent] = []

        if reading.laps_done is not None:
            # Les tours ne redescendent jamais pendant une course : une
            # lecture plus basse que ce qu'on a déjà confirmé est forcément
            # du bruit OCR (ex: un 5 lu comme 1) -> on l'ignore.
            if self._laps_done is None or reading.laps_done >= self._laps_done:
                self._has_laps = True
                if reading.laps_done != self._laps_done:
                    self._laps_done = reading.laps_done
                    events.append(SessionEvent.LAPS_UPDATED)
                if reading.laps_total:
                    self._laps_total = reading.laps_total
                if (
                    self._laps_total is not None
                    and self._laps_done is not None
                    and self._laps_done >= self._laps_total
                ):
                    events.append(self._stop(StopReason.LAPS_COMPLETE, now))
                    return events

        if reading.time_text is not None:
            self._last_good_time_wall = now
            self._apply_time_format(reading.time_text)
            seconds = seconds_from_time(reading.time_text)
            if seconds is not None:
                remaining = self._remaining_seconds(now)
                drift = seconds - remaining
                if drift > self.resync_tolerance_seconds:
                    # Le temps affiché a augmenté au lieu de descendre : la
                    # source a été réinitialisée/annulée (ex: bouton "Stop"
                    # sur Apex Timing qui revient au temps de base), pas un
                    # simple bruit OCR -> on arrête la session sur cette
                    # nouvelle valeur. Confirmé sur 2 lectures de suite pour
                    # ne pas annuler une vraie course sur une frame bruitée ;
                    # en attendant la confirmation, on affiche déjà la
                    # nouvelle valeur (candidate) pour ne pas rester visible-
                    # ment bloqué sur l'ancienne horloge interne.
                    if self._cancel_candidate is not None and abs(seconds - self._cancel_candidate) <= self.resync_tolerance_seconds:
                        self._cancel_streak += 1
                    else:
                        self._cancel_streak = 1
                    self._cancel_candidate = seconds
                    if self._cancel_streak >= self.required_confirmations:
                        events.append(self._stop(StopReason.CANCELLED, now, override_seconds=seconds))
                        return events
                else:
                    self._cancel_streak = 0
                    self._cancel_candidate = None
                    if drift < -self.resync_tolerance_seconds:
                        self._session_start_wall = now
                        self._session_start_seconds = seconds
                        events.append(SessionEvent.RESYNCED)
        elif (
            self._last_good_time_wall is not None
            and now - self._last_good_time_wall >= self.ocr_lost_timeout_seconds
        ):
            events.append(self._stop(StopReason.OCR_LOST, now))

        return events

    def tick(self, now: float) -> list[SessionEvent]:
        """Fait avancer l'horloge interne ; à appeler ~1x/seconde pendant ``RUNNING``."""
        if self.state != SessionState.RUNNING:
            return []
        if self._remaining_seconds(now) <= 0:
            return [self._stop(StopReason.TIME_ZERO, now)]
        return []

    def live_display(self, now: float) -> Optional[LiveDisplay]:
        if self.state != SessionState.RUNNING:
            return None
        if self._cancel_candidate is not None:
            remaining = max(0.0, self._cancel_candidate)
        else:
            remaining = max(0.0, self._remaining_seconds(now))
        return LiveDisplay(
            time_text=time_from_seconds(remaining, self._with_hours),
            laps_done=self._laps_done,
            laps_total=self._laps_total,
        )

    def armed_display(self) -> Optional[LiveDisplay]:
        """Valeur actuellement détectée avant confirmation du départ : dès
        qu'une lecture arrive (même statique), on l'affiche telle quelle
        plutôt que de rester bloqué sur le résultat de la session précédente
        (ex: la source repasse d'un format à un autre, ou une nouvelle
        valeur statique apparaît après un arrêt)."""
        if self.state != SessionState.ARMED or self._pending_seconds is None:
            return None
        return LiveDisplay(
            time_text=time_from_seconds(self._pending_seconds, self._with_hours),
            laps_done=self._laps_done,
            laps_total=self._laps_total,
        )

    def _remaining_seconds(self, now: float) -> float:
        return self._session_start_seconds - (now - self._session_start_wall)

    def _stop(self, reason: StopReason, now: float, override_seconds: Optional[float] = None) -> SessionEvent:
        remaining = override_seconds if override_seconds is not None else max(0.0, self._remaining_seconds(now))
        remaining = max(0.0, remaining)
        self.last_completed = CompletedResult(
            time_text=time_from_seconds(remaining, self._with_hours),
            laps_done=self._laps_done,
            laps_total=self._laps_total,
            reason=reason,
        )
        self.reset()
        return SessionEvent.STOPPED


def current_display(tracker: SessionTracker, now: float) -> DisplayValue:
    """Valeur à afficher : en direct si une session tourne, sinon la valeur
    en cours d'armement si une lecture est disponible, sinon figée sur le
    dernier résultat connu, sinon un placeholder."""
    live = tracker.live_display(now)
    if live is not None:
        return DisplayValue(live.time_text, live.laps_done, live.laps_total, is_live=True)
    armed = tracker.armed_display()
    if armed is not None:
        return DisplayValue(armed.time_text, armed.laps_done, armed.laps_total, is_live=True)
    completed = tracker.last_completed
    if completed is not None:
        return DisplayValue(completed.time_text, completed.laps_done, completed.laps_total, is_live=False)
    return DisplayValue("--:--", None, None, is_live=False)
