"""Chargement de la configuration : clés inconnues ignorées, nouveaux champs par défaut,
reprise de la config d'une version 2.x (Apex Timing OCR)."""
from __future__ import annotations

import json

from apex_ocr import config as config_mod
from apex_ocr.config import AppConfig


def _write(tmp_path, monkeypatch, data: dict, name: str = "config.json") -> None:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json"))


def test_old_ocr_and_external_keys_are_ignored(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {
        "window_title": "GoKarts", "zone": [1, 2, 3, 4], "threshold": 128, "tesseract_path": "x",   # OCR (<= 2.x)
        "external_enabled": True, "source": "apex_live",                                            # réglages supprimés
        "led_brightness": 16,
    })
    cfg = AppConfig.load()
    assert cfg.led_brightness == 16
    for key in ("window_title", "zone", "threshold", "tesseract_path", "external_enabled", "source"):
        assert not hasattr(cfg, key)


def test_new_fields_have_defaults(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"led_host": "192.168.47.1"})
    cfg = AppConfig.load()
    assert cfg.led_idle_clock is True and cfg.led_rotate_180 is False
    assert cfg.led_enabled is True and cfg.led_wifi_autoconnect is True
    assert cfg.log_level == "INFO"
    assert cfg.apex_data_dir.endswith("Data") and cfg.apex_db_user == "SYSDBA" and cfg.apex_poll_ms == 500
    assert cfg.apex_stale_seconds == 10.0


def test_legacy_config_is_reused_when_new_one_is_missing(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, {"led_rotate_180": True, "led_brightness": 9, "window_title": "GoKarts"}, name="legacy.json")
    cfg = AppConfig.load()
    assert cfg.loaded_from_legacy and cfg.led_rotate_180 is True and cfg.led_brightness == 9
    cfg.save()
    assert not AppConfig.load().loaded_from_legacy
    assert AppConfig.load().led_brightness == 9


def test_single_threshold_config_becomes_two_levels(tmp_path, monkeypatch):
    """Config < 3.1 : « rouge à 60 s / 5 tours » devient « jaune à 60 s / 5 tours, rouge à 30 s / 2 tours »."""
    _write(tmp_path, monkeypatch, {"led_alert_seconds": 60, "led_alert_laps": 5})
    cfg = AppConfig.load()
    assert (cfg.led_warn_seconds, cfg.led_alert_seconds, cfg.led_warn_laps, cfg.led_alert_laps) == (60, 30, 5, 2)
    _write(tmp_path, monkeypatch, {"led_alert_seconds": 20, "led_alert_laps": 1})            # rouge plus court que 30 s
    cfg = AppConfig.load()
    assert (cfg.led_warn_seconds, cfg.led_alert_seconds, cfg.led_warn_laps, cfg.led_alert_laps) == (20, 20, 1, 1)
    _write(tmp_path, monkeypatch, {"led_warn_seconds": 90, "led_alert_seconds": 45})         # config 3.1 : inchangée
    cfg = AppConfig.load()
    assert (cfg.led_warn_seconds, cfg.led_alert_seconds) == (90, 45)


def test_config_with_utf8_bom_is_still_read(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"led_brightness": 3}).encode())
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(path))
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json"))
    assert AppConfig.load().led_brightness == 3


def test_corrupt_config_falls_back_to_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{ pas du json", encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(path))
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json"))
    cfg = AppConfig.load()
    assert cfg.led_brightness == 12 and cfg.apex_db_host == "localhost"
