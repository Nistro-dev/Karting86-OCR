"""Rattachement Wi-Fi au panneau : lecture des sorties netsh (localisées) et profil de réseau ouvert."""
from __future__ import annotations

import pytest

from apex_ocr.led import wifi

SSID = "RHX8-Q2C#NewKartLed"

INTERFACES_FR = (
    "\r\nIl existe 1 interface sur le système :\r\n\r\n"
    "    Nom                    : Wi-Fi\r\n"
    "    Description            : Intel(R) Wi-Fi 6\r\n"
    "    État                   : connecté\r\n"
    f"    SSID                   : {SSID}\r\n"
    "    BSSID                  : 00:50:c2:f1:d5:23\r\n"
)
NETWORKS_FR = (
    "\r\nInterface name : Wi-Fi\r\nIl existe 3 réseaux actuellement visibles.\r\n\r\n"
    "SSID 1\xa0: \r\n    Type de réseau          : Infrastructure\r\n\r\n"
    f"SSID 2\xa0: {SSID}\r\n    Type de réseau          : Infrastructure\r\n\r\n"
    "SSID 3\xa0: Livebox-1234\r\n    Type de réseau          : Infrastructure\r\n"
)
PROFILES_FR = (
    "\r\nProfils sur l'interface Wi-Fi :\r\n\r\nProfils utilisateur\r\n-------------------\r\n"
    "    Profil Tous les utilisateurs     : Livebox-1234\r\n"
    f"    Profil Tous les utilisateurs     : {SSID}\r\n"
)


@pytest.fixture
def netsh(monkeypatch):
    calls: list[str] = []
    outputs = {"show interfaces": INTERFACES_FR, "show networks": NETWORKS_FR, "show profiles": PROFILES_FR}

    def fake(args: str):
        calls.append(args)
        return outputs.get(args, "")

    monkeypatch.setattr(wifi, "_netsh", fake)
    return calls


def test_parses_french_netsh_output(netsh):
    assert wifi.current_ssid() == SSID
    assert wifi.visible_ssids() == [SSID, "Livebox-1234"]      # le réseau masqué (SSID vide) est ignoré
    assert wifi.saved_profiles() == ["Livebox-1234", SSID]


def test_connect_is_noop_when_already_on_prefix(netsh):
    assert wifi.connect_to_prefix("RHX8-") is True
    assert netsh == ["show interfaces"]


def test_open_network_profile_xml():
    xml = wifi.profile_xml("RHX8-Q2C#New&Kart")
    assert "<name>RHX8-Q2C#New&amp;Kart</name>" in xml
    assert "<hex>" + "RHX8-Q2C#New&Kart".encode().hex().upper() + "</hex>" in xml
    assert "<authentication>open</authentication>" in xml and "<connectionMode>auto</connectionMode>" in xml


def test_ensure_profile_creates_missing_profile(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(wifi, "saved_profiles", lambda: ["Livebox-1234"])
    monkeypatch.setattr(wifi, "_netsh", lambda args: calls.append(args) or "Profil ajouté")
    assert wifi.ensure_profile(SSID) is True
    assert len(calls) == 1 and calls[0].startswith('add profile filename="') and "user=current" in calls[0]


def test_ensure_profile_skips_existing(monkeypatch):
    monkeypatch.setattr(wifi, "saved_profiles", lambda: [SSID])
    monkeypatch.setattr(wifi, "_netsh", lambda args: pytest.fail("netsh ne doit pas être appelé"))
    assert wifi.ensure_profile(SSID) is True
