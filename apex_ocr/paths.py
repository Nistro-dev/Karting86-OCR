"""Emplacements sur disque : données persistées, logs, sortie timer.txt."""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", app_dir())
        return os.path.join(base, "ApexTimingOCR")
    return app_dir()


APP_DIR = app_dir()
DATA_DIR = data_dir()
LOG_DIR = os.path.join(DATA_DIR, "logs")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "timer.txt")

os.makedirs(DATA_DIR, exist_ok=True)
