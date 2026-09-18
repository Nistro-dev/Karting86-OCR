"""Statut de santé remonté par l'icône systray.

gris (IDLE)   -> pipeline OK, en attente d'une course
vert (ACTIVE) -> une session est activement suivie
rouge (ERROR) -> fenêtre introuvable ou OCR mort depuis trop longtemps
"""
from __future__ import annotations

from enum import Enum, auto

from apex_ocr.session import SessionState

# ~5s d'échecs consécutifs à l'intervalle OCR par défaut (200ms) avant de
# passer en rouge : assez prompt sans déclencher sur un hoquet ponctuel.
DEFAULT_ERROR_THRESHOLD = 25


class HealthStatus(Enum):
    IDLE = auto()
    ACTIVE = auto()
    ERROR = auto()


class HealthMonitor:
    def __init__(self, error_threshold: int = DEFAULT_ERROR_THRESHOLD):
        self.error_threshold = error_threshold
        self._consecutive_failures = 0

    def record_capture_success(self) -> None:
        self._consecutive_failures = 0

    def record_capture_failure(self) -> None:
        self._consecutive_failures += 1

    @property
    def is_erroring(self) -> bool:
        return self._consecutive_failures >= self.error_threshold

    def status_for(self, session_state: SessionState) -> HealthStatus:
        if self.is_erroring:
            return HealthStatus.ERROR
        if session_state is SessionState.RUNNING:
            return HealthStatus.ACTIVE
        return HealthStatus.IDLE
