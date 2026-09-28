"""Rattachement (optionnel) du PC au réseau Wi-Fi du panneau RHX8 via ``netsh wlan``
— Windows uniquement.

Tout est gardé : hors Windows, sans carte Wi-Fi ou si netsh échoue, les fonctions
renvoient ``None`` / ``False`` / ``[]`` sans jamais lever. Le réseau doit déjà être
connu de Windows (profil créé lors d'une première connexion manuelle) :
``netsh wlan connect`` ne crée pas de profil.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import Optional

NETSH_TIMEOUT_S = 15.0
CONNECT_WAIT_S = 12.0    # délai max pour que l'interface passe sur le réseau demandé
_POLL_S = 1.0

# Sorties netsh « libellé : valeur » : libellés localisés et, en français, espace
# insécable avant le deux-points. Blancs horizontaux seulement, pour ne jamais
# enjamber une ligne (une valeur vide, réseau masqué, avalerait la suivante).
_HS = r"[ \t\xa0]"
_INTERFACE_SSID_RE = re.compile(rf"^{_HS}*SSID{_HS}*:{_HS}*(.*?){_HS}*\r?$", re.MULTILINE)       # « SSID : x » (pas BSSID)
_NETWORK_SSID_RE = re.compile(rf"^{_HS}*SSID{_HS}+\d+{_HS}*:{_HS}*(.*?){_HS}*\r?$", re.MULTILINE)  # « SSID 2 : x »
_KEY_VALUE_RE = re.compile(rf"^{_HS}*[^:\r\n]+?{_HS}*:{_HS}*(.*?){_HS}*\r?$", re.MULTILINE)


def current_ssid() -> Optional[str]:
    """SSID du réseau Wi-Fi courant, ou None (déconnecté, pas de Wi-Fi, hors Windows)."""
    out = _netsh("show interfaces")
    match = _INTERFACE_SSID_RE.search(out) if out else None
    return (match.group(1) or None) if match else None


def visible_ssids() -> list[str]:
    """SSID des réseaux visibles (cache Windows du dernier balayage), réseaux masqués exclus."""
    out = _netsh("show networks")
    return [s for s in _NETWORK_SSID_RE.findall(out) if s] if out else []


def saved_profiles() -> list[str]:
    """Noms des profils Wi-Fi enregistrés dans Windows (réseaux déjà rejoints depuis ce PC)."""
    out = _netsh("show profiles")
    return [s for s in _KEY_VALUE_RE.findall(out) if s] if out else []


def connect_to_prefix(prefix: str, timeout: float = CONNECT_WAIT_S) -> bool:
    """Rejoint un réseau dont le SSID commence par ``prefix`` : d'abord ceux à la
    fois visibles et connus de Windows, puis les profils enregistrés (le cache des
    réseaux visibles peut être vide juste après l'allumage du panneau), enfin les
    réseaux visibles sans profil (netsh les refusera, sauf profil nommé autrement).

    True si, à la sortie, l'interface est sur un tel réseau (déjà le cas, ou
    connexion aboutie dans le délai) ; False sinon (réseau absent, profil inconnu
    de Windows, échec, plateforme non gérée)."""
    try:
        if _on_prefix(prefix):
            return True
        visible = [s for s in visible_ssids() if s.startswith(prefix)]
        profiles = [p for p in saved_profiles() if p.startswith(prefix)]
        ordered = ([s for s in visible if s in profiles]
                   + [p for p in profiles if p not in visible]
                   + [s for s in visible if s not in profiles])
        for ssid in ordered:
            if _connect(ssid) and _wait_on_prefix(prefix, timeout):
                return True
        return False
    except Exception:
        return False


def _on_prefix(prefix: str) -> bool:
    ssid = current_ssid()
    return ssid is not None and ssid.startswith(prefix)


def _connect(ssid: str) -> bool:
    """Demande la connexion (asynchrone côté Windows) ; False si netsh refuse (profil inconnu...)."""
    safe = ssid.replace('"', "")
    return _netsh(f'connect name="{safe}" ssid="{safe}"') is not None


def _wait_on_prefix(prefix: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(_POLL_S)
        if _on_prefix(prefix):
            return True
    return False


def _netsh(args: str) -> Optional[str]:
    """Sortie texte de ``netsh wlan <args>`` ; None hors Windows, en cas d'échec ou de code de retour non nul."""
    if sys.platform != "win32":
        return None
    try:
        proc = subprocess.run(
            "netsh wlan " + args,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=NETSH_TIMEOUT_S, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # pas de console furtive (exe --windowed)
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return _decode(proc.stdout)


def _decode(raw: bytes) -> str:
    # netsh écrit dans la page de code de la console : OEM (cp850 en français) sans
    # console, UTF-8 si celle-ci est en 65001. L'UTF-8 strict rejette les accents
    # cp850 (0x82, 0xFF...), on le tente donc en premier.
    for encoding in ("utf-8", "oem", "cp850"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")
