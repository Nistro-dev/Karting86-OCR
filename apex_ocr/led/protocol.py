"""Protocole BLE du panneau iPixel Color (repris de newkart-led-panel) :
construction de paquets uniquement, pas d'I/O ici."""
from __future__ import annotations

import struct
import zlib

UUID_WRITE = "0000fa02-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_PREFIX = "LED_BLE_"


def build_data_packet(cmd: int, data: bytes, buffer_number: int = 1) -> bytes:
    """cmd = 0x0002 pour une image PNG."""
    size = len(data)
    crc = zlib.crc32(data) & 0xFFFFFFFF
    header_wo_len = (
        bytes([cmd & 0xFF, (cmd >> 8) & 0xFF])
        + bytes([0x00])
        + struct.pack("<I", size)
        + struct.pack("<I", crc)
        + bytes([0x00, buffer_number])
    )
    total_len = 2 + len(header_wo_len) + size
    return struct.pack("<H", total_len) + header_wo_len + data


def build_png_packet(png_data: bytes) -> bytes:
    return build_data_packet(0x0002, png_data)


def power_command(on: bool) -> bytes:
    return bytes([0x05, 0x00, 0x07, 0x01, 0x01 if on else 0x00])


def brightness_command(level: int) -> bytes:
    return bytes([0x05, 0x00, 0x04, 0x80, max(1, min(100, level))])
