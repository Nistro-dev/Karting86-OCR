"""Configuration de l'application : valeurs par défaut et persistance sur disque."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from apex_ocr.led.protocol import DEFAULT_HOST, DEFAULT_PASSWORD
from apex_ocr.paths import CONFIG_PATH, LEGACY_CONFIG_PATH

DEFAULT_APEX_DATA_DIR = r"C:\ApexTiming\Data"


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
    # Source du chrono : la base Firebird de GoKarts / GoServer (Apex Timing), lue en lecture
    # seule (voir apex_ocr/source/apex_live.py et docs/apex_findings.md).
    apex_data_dir: str = DEFAULT_APEX_DATA_DIR   # dossier des bases journalières DAYAAAAMMJJ.GO
    apex_db_host: str = "localhost"
    apex_db_user: str = "SYSDBA"
    apex_db_password: str = "masterkey"
    apex_fbclient_path: str = ""                 # fbclient.dll 64 bits ; vide = détection automatique
    apex_poll_ms: int = 500                      # cadence de lecture de la base
    apex_stale_seconds: float = 10.0             # base muette depuis ce délai -> statut rouge, session abandonnée
    log_retention_days: int = 30
    # Panneau LED Wi-Fi (RHX8 64×16 à 8 couleurs, voir apex_ocr/led) : à chaque
    # lancement l'appli rejoint elle-même le réseau « RHX8-… » du panneau et s'y
    # connecte (hôte « ip » ou « ip:port », l'IP du panneau ne change jamais), puis
    # réessaie tant qu'il est injoignable. led_enabled = false pour s'en passer
    # (« Déconnecter » dans la fenêtre dev ne vaut que pour la session en cours).
    led_enabled: bool = True
    led_host: str = DEFAULT_HOST
    led_password: str = DEFAULT_PASSWORD
    led_brightness: int = 12  # 1..16
    led_show_laps: bool = True  # afficher les tours à gauche du temps
    led_resync_minutes: int = 2  # longueur des tranches du décompte (le panneau repart du début au bout de ~4 min) ; bref clignotement à chaque tranche
    led_wifi_autoconnect: bool = True  # rejoindre le Wi-Fi RHX8-… automatiquement (netsh, profil créé au besoin) ; false = ne pas toucher au Wi-Fi du PC
    led_width: int = 64
    led_height: int = 16
    led_color: list[int] = field(default_factory=lambda: [0, 255, 0])
    led_alert_color: list[int] = field(default_factory=lambda: [255, 0, 0])
    led_alert_seconds: int = 60
    led_alert_laps: int = 5
    led_laps_only: bool = False
    led_idle_clock: bool = True  # hors course : afficher l'heure (sinon écran noir)
    led_rotate_180: bool = False  # panneau monté tête en bas : toute l'image est tournée de 180°
    log_level: str = "INFO"  # DEBUG activable à chaud dans la fenêtre dev

    @classmethod
    def load(cls) -> "AppConfig":
        """Config du dossier de l'appli ; à défaut, celle d'une version 2.x (« Apex Timing OCR »)
        dont les réglages du panneau LED sont repris tels quels."""
        cfg = cls()
        path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else LEGACY_CONFIG_PATH
        if os.path.exists(path):
            try:
                # utf-8-sig : un config.json réenregistré avec un BOM (Bloc-notes, PowerShell)
                # doit rester lisible, sinon tout repart aux valeurs par défaut.
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                data = {}
            # Les clés inconnues (réglages OCR des versions 2.x : window_title, zone, threshold,
            # tesseract_path..., « external_* », « led_address »...) sont ignorées sans erreur.
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
            if "led_host" not in data and _looks_like_ipv4(data.get("led_address")):
                cfg.led_host = data["led_address"].strip()
        return cfg

    @property
    def loaded_from_legacy(self) -> bool:
        return not os.path.exists(CONFIG_PATH) and os.path.exists(LEGACY_CONFIG_PATH)

    def save(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
