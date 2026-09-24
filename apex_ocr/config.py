"""Configuration de l'application : valeurs par défaut et persistance sur disque."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from apex_ocr.paths import CONFIG_PATH

_TESSERACT_SEARCH_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]


def find_tesseract() -> str:
    for path in _TESSERACT_SEARCH_PATHS:
        if os.path.exists(path):
            return path
    return ""


@dataclass
class AppConfig:
    window_title: str = ""
    zone: Optional[list[int]] = None
    tesseract_path: str = field(default_factory=find_tesseract)
    ocr_interval_ms: int = 200
    threshold: int = 127
    resync_tolerance_seconds: int = 3
    ocr_lost_timeout_seconds: float = 10.0
    log_retention_days: int = 30
    external_monitor_index: Optional[int] = None
    # Désactivé : l'affichage externe ne s'ouvre jamais (ni au démarrage, ni via le bouton).
    # Désactivé par défaut : à activer dans la fenêtre dev seulement s'il y a un écran piste.
    external_enabled: bool = False
    # Panneau LED Bluetooth (iPixel Color, voir apex_ocr/led) : reconnexion
    # automatique au lancement si led_enabled et une adresse est mémorisée.
    led_address: str = ""
    led_enabled: bool = False
    led_known_devices: list[list[str]] = field(default_factory=list)  # [[nom, adresse], ...] du dernier scan
    led_width: int = 64
    led_height: int = 16
    led_color: list[int] = field(default_factory=lambda: [255, 30, 20])
    led_laps_only: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        return cfg

    def save(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @property
    def is_ready(self) -> bool:
        return bool(self.window_title and self.zone)
