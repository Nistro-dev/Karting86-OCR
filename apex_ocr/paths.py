"""Emplacements sur disque : données persistées, logs, sortie timer.txt."""
from __future__ import annotations

import os
import sys

DATA_DIR_NAME = "NewKartPanneauLed"
LEGACY_DATA_DIR_NAME = "ApexTimingOCR"   # versions <= 2.x : la config LED y est reprise au premier lancement


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _base_dir() -> str:
    if sys.platform == "win32":
        return os.environ.get("LOCALAPPDATA", app_dir())
    return app_dir()


def data_dir() -> str:
    return os.path.join(_base_dir(), DATA_DIR_NAME) if sys.platform == "win32" else app_dir()


APP_DIR = app_dir()
DATA_DIR = data_dir()
LEGACY_CONFIG_PATH = os.path.join(_base_dir(), LEGACY_DATA_DIR_NAME, "config.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "timer.txt")

os.makedirs(DATA_DIR, exist_ok=True)
