"""Logger applicatif : rotation quotidienne, rétention configurable, plafond de taille.

Un seul fichier de log sert à la fois de journal des changements de timer
(INFO) et d'historique des incidents (WARNING pour un début de panne, INFO
pour le retour à la normale) — greppable par niveau au besoin.
"""
from __future__ import annotations

import glob
import logging
import logging.handlers
import os
import time

from apex_ocr.paths import LOG_DIR

_LOGGER_NAME = "apex_ocr"
MAX_LOG_BYTES = 5_000_000   # au-delà, le fichier du jour est archivé (apex_ocr.log.AAAA-MM-JJ_HHMMSS)
MAX_SIZE_ARCHIVES = 3       # nombre d'archives « par taille » conservées


class DailyOrSizeHandler(logging.handlers.TimedRotatingFileHandler):
    """Rotation à minuit (rétention en jours) ET dès que le fichier dépasse
    ``max_bytes`` : en DEBUG, une journée de lectures OCR peut peser des dizaines
    de Mo, et un journal illisible ne sert à personne."""

    def __init__(self, *args, max_bytes: int = MAX_LOG_BYTES, size_archives: int = MAX_SIZE_ARCHIVES, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_bytes = max_bytes
        self.size_archives = size_archives
        self._size_rollover = False

    def shouldRollover(self, record) -> int:  # noqa: N802 (API logging)
        if super().shouldRollover(record):
            return 1
        if self.max_bytes <= 0:
            return 0
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        if self.stream.tell() + len(self.format(record).encode("utf-8", "replace")) >= self.max_bytes:
            self._size_rollover = True
            return 1
        return 0

    def doRollover(self) -> None:  # noqa: N802 (API logging)
        if not self._size_rollover:
            super().doRollover()
            return
        self._size_rollover = False
        if self.stream:
            self.stream.close()
            self.stream = None
        if os.path.exists(self.baseFilename):
            os.replace(self.baseFilename, self.baseFilename + time.strftime(".%Y-%m-%d_%H%M%S"))
        archives = sorted(glob.glob(self.baseFilename + ".????-??-??_??????"))
        for old in archives[: max(0, len(archives) - self.size_archives)]:
            try:
                os.remove(old)
            except OSError:
                pass
        if not self.delay:
            self.stream = self._open()


def setup_logging(retention_days: int = 30, level: str = "INFO") -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    log_level = getattr(logging, level.upper(), logging.INFO)
    if logger.handlers:
        logger.setLevel(log_level)
        return logger

    logger.setLevel(log_level)
    handler = DailyOrSizeHandler(
        os.path.join(LOG_DIR, "apex_ocr.log"),
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def set_log_level(level: str) -> None:
    """Change le niveau de log à chaud."""
    logger = logging.getLogger(_LOGGER_NAME)
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
