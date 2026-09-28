"""Protocole Wi-Fi du panneau LED RHX8 (Ruihe Xin, 64×16 RGB 8 couleurs), rétro-ingénieré
à partir de l'appli RHX Plus. Fonctions pures uniquement (pas d'I/O), testables.

Trame : ``aa 55 aa 55 00 00`` + opcode + données + ``04``.
Login : le panneau envoie un défi de 8 octets ; la réponse est calculée avec RC5-32/12
(clé fixe, 26 sous-clés extraites de l'appli) — voir ``login_response``.
"""
from __future__ import annotations

import struct

DEFAULT_HOST = "192.168.47.1"
DEFAULT_PORT = 25622
DEFAULT_PASSWORD = "LED12345678"
WIFI_SSID_PREFIX = "RHX8-"

_M = 0xFFFFFFFF
_SUBKEYS = list(struct.unpack("<26I", bytes.fromhex(
    "c06e548c7882c5efd06555f7355f4f34ae909be8a223b2c0fb464c978c5f5f48"
    "700619f36cee5ef2c166321f6670e1fd1dd97e600a7870fa68d3d2c21e4cac50"
    "48c937081c35484ab72c6ef969e558b5b0c96e471a93290061367a4a356fa84f"
    "29e06d056132f14f")))


def _rol(x: int, n: int) -> int:
    n &= 31
    return ((x << n) | (x >> (32 - n))) & _M if n else x & _M


def _ror(x: int, n: int) -> int:
    n &= 31
    return ((x >> n) | (x << (32 - n))) & _M if n else x & _M


def rc5_encrypt(block: bytes) -> bytes:
    a, b = struct.unpack("<2I", block)
    a = (a + _SUBKEYS[0]) & _M
    b = (b + _SUBKEYS[1]) & _M
    for i in range(1, 13):
        a = (_rol(a ^ b, b) + _SUBKEYS[2 * i]) & _M
        b = (_rol(b ^ a, a) + _SUBKEYS[2 * i + 1]) & _M
    return struct.pack("<2I", a, b)


def rc5_decrypt(block: bytes) -> bytes:
    a, b = struct.unpack("<2I", block)
    for i in range(12, 0, -1):
        b = _ror((b - _SUBKEYS[2 * i + 1]) & _M, a) ^ a
        a = _ror((a - _SUBKEYS[2 * i]) & _M, b) ^ b
    return struct.pack("<2I", (a - _SUBKEYS[0]) & _M, (b - _SUBKEYS[1]) & _M)


def login_response(nonce: bytes, password: str = DEFAULT_PASSWORD) -> bytes:
    """16 octets à renvoyer après ``89 a1 10`` : RC5-ECB(RC5⁻¹(nonce)[0:4] ‖ len ‖ mdp)[:16]."""
    d = rc5_decrypt(nonce)
    pw = password.encode()
    msg = d[:4] + bytes([len(pw)]) + pw
    msg += b"\x00" * ((-len(msg)) % 8)
    return b"".join(rc5_encrypt(msg[i:i + 8]) for i in range(0, len(msg), 8))[:16]


# ---- trames ---------------------------------------------------------------

def frame(*payload: int) -> bytes:
    return bytes.fromhex("aa55aa550000") + bytes(payload)


def hello_packet() -> bytes:
    return frame(0xFF, 0x04)


def is_challenge(reply: bytes) -> bool:
    return len(reply) >= 17 and reply[6:8] == b"\x59\xa0"


def challenge_nonce(reply: bytes) -> bytes:
    return reply[9:17]


def login_packet(nonce: bytes, password: str) -> bytes:
    return frame(0x89, 0xA1, 0x10) + login_response(nonce, password) + b"\x04"


def is_login_ok(reply: bytes) -> bool:
    return len(reply) >= 8 and reply[6:8] == b"\x59\xa1"


def brightness_packet(level: int) -> bytes:
    """Niveau 1..16 comme l'appli (0xf0..0xff)."""
    level = max(1, min(16, int(level)))
    return frame(0x0A, 0xEF + level, 0x04)


def upload_header(program_len: int) -> bytes:
    """Annonce d'un programme de ``program_len`` octets ; le panneau répond ``e1``."""
    return frame(0x78, 0xE1, 0, 0, 0, 0) + program_len.to_bytes(4, "big")


def is_upload_accepted(reply: bytes) -> bool:
    return reply[:1] == b"\xe1"


def is_upload_done(reply: bytes) -> bool:
    return reply[:1] == b"\x88"
