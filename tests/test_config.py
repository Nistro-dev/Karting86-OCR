"""Chargement de la configuration : clés inconnues ignorées, nouveaux champs par défaut."""
from __future__ import annotations

import json

from apex_ocr import config as config_mod
from apex_ocr.config import AppConfig


def _write(tmp_path, monkeypatch, data: dict) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(path))


def test_old_external_display_keys_are_ignored(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {
        "window_title": "Apex", "zone": [1, 2, 3, 4],
        "external_enabled": True, "external_monitor_index": 2,   # réglages supprimés
    })
    cfg = AppConfig.load()
    assert cfg.window_title == "Apex" and cfg.zone == [1, 2, 3, 4]
    assert not hasattr(cfg, "external_enabled") and not hasattr(cfg, "external_monitor_index")


def test_new_led_fields_have_defaults(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"window_title": "Apex"})
    cfg = AppConfig.load()
    assert cfg.led_idle_clock is True
    assert cfg.led_rotate_180 is False
    assert cfg.led_enabled is True and cfg.led_wifi_autoconnect is True
    assert cfg.log_level == "INFO"


def test_corrupt_config_falls_back_to_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{ pas du json", encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(path))
    cfg = AppConfig.load()
    assert cfg.window_title == "" and not cfg.is_ready
