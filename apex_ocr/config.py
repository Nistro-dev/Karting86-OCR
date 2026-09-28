"""Configuration de l'application : valeurs par défaut et persistance sur disque."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from apex_ocr.led.protocol import DEFAULT_HOST, DEFAULT_PASSWORD
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


def _looks_like_ipv4(value) -> bool:
    """« a.b.c.d » (port optionnel « :n ») -> True ; adresse Bluetooth ou autre -> False."""
    if not isinstance(value, str):
        return False
    host = value.strip()
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts)


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
    # Panneau LED Wi-Fi (RHX8 64×16 à 8 couleurs, voir apex_ocr/led) : le PC
    # rejoint le réseau « RHX8-… » du panneau, l'appli s'y reconnecte toute
    # seule au lancement si led_enabled (hôte « ip » ou « ip:port »).
    led_enabled: bool = False
    led_host: str = DEFAULT_HOST
    led_password: str = DEFAULT_PASSWORD
    led_brightness: int = 12  # 1..16
    led_show_laps: bool = True  # afficher les tours à gauche du temps
    led_resync_minutes: int = 2  # longueur des tranches du décompte (le panneau repart du début au bout de ~4 min) ; bref clignotement à chaque tranche
    led_wifi_autoconnect: bool = False  # rejoindre le Wi-Fi RHX8-… automatiquement avant de se connecter (netsh, Windows)
    led_width: int = 64
    led_height: int = 16
    led_color: list[int] = field(default_factory=lambda: [0, 255, 0])
    led_alert_color: list[int] = field(default_factory=lambda: [255, 0, 0])
    led_alert_seconds: int = 60
    led_alert_laps: int = 5
    led_laps_only: bool = False
    log_level: str = "DEBUG"

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
            # Ancienne config (panneau Bluetooth) : « led_address » n'existe plus.
            # Une IP y a peut-être été saisie -> reprise comme hôte ; une adresse
            # BLE (AA:BB:...) est ignorée.
            if "led_host" not in data and _looks_like_ipv4(data.get("led_address")):
                cfg.led_host = data["led_address"].strip()
        return cfg

    def save(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @property
    def is_ready(self) -> bool:
        return bool(self.window_title and self.zone)
