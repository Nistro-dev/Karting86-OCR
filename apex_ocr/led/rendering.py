"""Rendu pour le panneau RHX8 : framebuffer 64×16 à 8 couleurs (bits R,G,B) et
construction du programme envoyé au panneau (mono ou multi-trames).

Le mapping physique a été établi par calibration :
- colonnes : la donnée en colonne D s'affiche en colonne (D+16) mod 64 ;
- lignes   : colonnes 16-63 -> identité, colonnes 0-15 -> décalées d'une ligne.
Seul le pixel (ligne 0, colonnes 0-15) est physiquement inatteignable : on
laisse donc la ligne 0 vide.
"""
from __future__ import annotations

import os
import time
from typing import Optional

W, H = 64, 16
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rgb_template.bin")

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
COLOR_NAMES = ["noir", "rouge", "vert", "jaune", "bleu", "magenta", "cyan", "blanc"]
# Les mêmes 8 couleurs en hexadécimal (boutons de l'UI : montrer la couleur réellement affichée).
COLOR_HEX = ["#000000", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "#00ffff", "#ffffff"]


def color_index(rgb: tuple) -> int:
    """Quantifie une couleur RGB libre vers les 8 couleurs du panneau (jamais noir)."""
    r, g, b = (int(c) > 127 for c in rgb)
    idx = (1 if r else 0) | (2 if g else 0) | (4 if b else 0)
    return idx or WHITE


# Polices bitmap (largeur variable : ':' est plus étroit).
SMALL_DIGITS = {   # 5 x 7
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
    ":": [".", ".", "#", ".", "#", ".", "."],
    " ": ["....."] * 7,
}
TINY_DIGITS = {   # 3 x 5
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"], "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"], "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "###"],
    "/": ["..#", "..#", ".#.", "#..", "#.."], ":": [".", "#", ".", "#", "."], " ": ["..."] * 5,
}
_SEG = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
        "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


class Frame:
    """Framebuffer 64×16 ; ``px[y][x]`` = couleur 0..7."""

    def __init__(self):
        self.px = [[BLACK] * W for _ in range(H)]

    def set(self, x: int, y: int, color: int) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = color & 7

    def is_blank(self) -> bool:
        return not any(any(row) for row in self.px)

    def __eq__(self, other) -> bool:
        return isinstance(other, Frame) and self.px == other.px

    __hash__ = None

    # -- texte ----------------------------------------------------------------

    def bitmap_text(self, s: str, font: dict, color: int, x0: int, y0: int, gap: int = 1) -> int:
        """Écrit ``s`` avec une police bitmap ; renvoie la largeur utilisée."""
        x = x0
        for c in s:
            glyph = font.get(c, font[" "])
            for r, line in enumerate(glyph):
                for cc, ch in enumerate(line):
                    if ch == "#":
                        self.set(x + cc, y0 + r, color)
            x += len(glyph[0]) + gap
        return x - x0 - gap

    def seg7(self, s: str, color: int, x0: int, y0: int, w: int, h: int, stroke: int = 2,
             colon_w: int = 2, gap: int = 1) -> int:
        """Chiffres 7 segments ; renvoie la largeur utilisée."""
        mid = y0 + (h - stroke) // 2

        def rect(rx, ry, rw, rh):
            for yy in range(ry, ry + rh):
                for xx in range(rx, rx + rw):
                    self.set(xx, yy, color)
        x = x0
        for c in s:
            if c == ":":
                q = h // 4
                rect(x, y0 + q, colon_w, stroke)
                rect(x, y0 + h - q - stroke, colon_w, stroke)
                x += colon_w + gap
                continue
            sg = _SEG.get(c, "")
            if "a" in sg: rect(x, y0, w, stroke)
            if "d" in sg: rect(x, y0 + h - stroke, w, stroke)
            if "g" in sg: rect(x, mid, w, stroke)
            if "f" in sg: rect(x, y0, stroke, mid - y0 + stroke)
            if "b" in sg: rect(x + w - stroke, y0, stroke, mid - y0 + stroke)
            if "e" in sg: rect(x, mid, stroke, y0 + h - mid)
            if "c" in sg: rect(x + w - stroke, mid, stroke, y0 + h - mid)
            x += w + gap
        return x - x0 - gap


def seg7_width(s: str, w: int, colon_w: int = 2, gap: int = 1) -> int:
    return sum((colon_w if c == ":" else w) for c in s) + gap * (len(s) - 1)


def bitmap_width(s: str, font: dict, gap: int = 1) -> int:
    return sum(len(font.get(c, font[" "])[0]) for c in s) + gap * (len(s) - 1)


# ---- programme envoyé au panneau ---------------------------------------------

_TABLE_OFS = 2887
_FRAMECOUNT_OFS = 166          # 16 bits big-endian (166-167)
_M = 0xFFFFFFFF
MAX_FRAMES = 65535


def _plane_row(frame: Frame, y: int, bit: int) -> bytes:
    r = bytearray(8)
    if 0 <= y < H:
        for x in range(W):
            if (frame.px[y][x] >> bit) & 1:
                r[x // 8] |= 0x80 >> (x % 8)
    return bytes(r)


def _row_data(frame: Frame, bit: int, row: int) -> bytes:
    a = _plane_row(frame, row, bit)
    b = _plane_row(frame, row + 1, bit)
    return bytes([a[2], a[3], a[4], a[5], a[6], a[7], b[0], b[1]])


def program_size(n_frames: int) -> int:
    """Taille (octets) du programme pour ``n_frames`` trames, pour estimer la durée d'envoi."""
    return _TABLE_OFS + n_frames * 48 * (4 + 8) + 2 + 8 + 4 + 8 + 4


def build_program(frames: list[Frame], template_path: str = TEMPLATE_PATH) -> bytes:
    """Programme complet (N trames enchaînées par le panneau, ~1 s chacune)."""
    nf = len(frames)
    if not 1 <= nf <= MAX_FRAMES:
        raise ValueError("1 à %d trames" % MAX_FRAMES)
    with open(template_path, "rb") as f:
        t = f.read()
    content = bytearray(t[:_TABLE_OFS])
    content[_FRAMECOUNT_OFS:_FRAMECOUNT_OFS + 2] = nf.to_bytes(2, "big")
    table_end = _TABLE_OFS + nf * 48 * 4
    content += bytes(nf * 48 * 4)
    content += b"\x00\x00"
    rows_base = len(content)
    for fr in frames:
        for entry in range(48):
            content += _row_data(fr, entry // 16, entry % 16)
    for e in range(nf * 48):
        content[_TABLE_OFS + 4 * e:_TABLE_OFS + 4 * e + 4] = (rows_base + e * 8).to_bytes(4, "big")
    footer_start = len(content)
    data_len = footer_start - table_end - 1
    content += (nf * 48 * 8).to_bytes(3, "big") + data_len.to_bytes(4, "big") + b"\x04"
    n = len(content) + 4
    content[15:19] = n.to_bytes(4, "big")
    body = bytes(content) + (sum(content) & _M).to_bytes(4, "big")
    now = time.localtime()
    trailer = bytes([now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min, now.tm_sec]) + os.urandom(3)
    out = body + trailer
    return out + (sum(out) & _M).to_bytes(4, "big")


def program_length(program: bytes) -> int:
    """Longueur annoncée dans l'en-tête (``n``), à passer à ``upload_header``."""
    return int.from_bytes(program[15:19], "big")


# ---- mise en page temps / tours -----------------------------------------------

def parse_seconds(time_text: str) -> Optional[int]:
    """"MM:SS" ou "H:MM:SS" -> secondes, ou None si ce n'est pas un temps."""
    parts = time_text.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def format_like(seconds: int, template: str) -> str:
    """Formate ``seconds`` comme ``template`` ("MM:SS", "H:MM:SS", "HH:MM:SS")."""
    seconds = max(0, seconds)
    parts = template.split(":")
    if len(parts) == 3:
        return "%0*d:%02d:%02d" % (len(parts[0]), seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return "%0*d:%02d" % (len(parts[0]), seconds // 60, seconds % 60)


def _fit_seg7(text: str, width: int, gap: int, min_w: int) -> Optional[tuple[int, int]]:
    """Plus grande largeur de chiffre (et du ':') qui tient dans ``width``."""
    for w in range(14, min_w - 1, -1):
        cw = 3 if w >= 9 else 2
        if seg7_width(text, w, cw, gap) <= width:
            return w, cw
    return None


class TimerRenderer:
    """Compose une trame « temps » (+ tours à gauche), le plus grand possible."""

    def __init__(self, width: int = W, height: int = H, rgb: tuple = (255, 255, 255)):
        self.width, self.height = width, height
        self.rgb = rgb

    @property
    def color(self) -> int:
        return color_index(self.rgb)

    def render(self, time_text: str, laps_text: Optional[str] = None, color: Optional[int] = None) -> Frame:
        fr = Frame()
        color = self.color if color is None else color
        x0, avail, gap = 0, self.width, 2
        if laps_text:
            font = SMALL_DIGITS if bitmap_width(laps_text, SMALL_DIGITS) <= 30 else TINY_DIGITS
            lw = fr.bitmap_text(laps_text, font, color, 1, (self.height - len(font["0"])) // 2)
            x0, gap = lw + 3, 1
            avail = self.width - x0
        fit = _fit_seg7(time_text, avail, gap, 5)
        if fit:
            w, cw = fit
            tw = seg7_width(time_text, w, cw, gap)
            fr.seg7(time_text, color, x0 + (avail - tw) // 2, 1, w, self.height - 1, 2, cw, gap)
        else:
            font = SMALL_DIGITS if bitmap_width(time_text, SMALL_DIGITS) <= avail else TINY_DIGITS
            tw = bitmap_width(time_text, font)
            fr.bitmap_text(time_text, font, color, x0 + max(0, (avail - tw) // 2),
                           (self.height - len(font["0"])) // 2)
        return fr

    def countdown(self, time_text: str, laps_text: Optional[str] = None, max_frames: int = MAX_FRAMES,
                  alert_below: Optional[int] = None, alert_color: Optional[int] = None) -> list[Frame]:
        """Trames de ``time_text`` vers zéro (1 trame / seconde), au plus ``max_frames`` ; les trames
        à ``alert_below`` secondes ou moins sont rendues en ``alert_color``."""
        secs = parse_seconds(time_text)
        if secs is None:
            return [self.render(time_text, laps_text)]
        stop = max(-1, secs - max_frames)
        base = self.color
        return [self.render(format_like(s, time_text), laps_text,
                            alert_color if alert_below is not None and alert_color is not None
                            and s <= alert_below else base)
                for s in range(secs, stop, -1)]


def blank_frame() -> Frame:
    return Frame()
