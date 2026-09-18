"""Logger applicatif : rotation quotidienne, rétention configurable.

Un seul fichier de log sert à la fois de journal des changements de timer
(INFO) et d'historique des incidents (WARNING pour un début de panne, INFO
pour le retour à la normale) — greppable par niveau au besoin.
"""
from __future__ import annotations

import logging
import logging.handlers
import os

from apex_ocr.paths import LOG_DIR

_LOGGER_NAME = "apex_ocr"


def setup_logging(retention_days: int = 30) -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "apex_ocr.log"),
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
