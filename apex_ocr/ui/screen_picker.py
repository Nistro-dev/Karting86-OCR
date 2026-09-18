"""Détection des écrans connectés et petite fenêtre de sélection."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

import customtkinter as ctk

try:
    import win32api

    WIN32_MONITORS_OK = True
except ImportError:
    WIN32_MONITORS_OK = False


@dataclass(frozen=True)
class MonitorInfo:
    index: int
    x: int
    y: int
    width: int
    height: int
    is_primary: bool

    @property
    def label(self) -> str:
        primary = " (principal)" if self.is_primary else ""
        return f"Écran {self.index + 1} — {self.width}×{self.height}{primary}"


def list_monitors() -> list[MonitorInfo]:
    if not WIN32_MONITORS_OK:
        return []
    monitors: list[MonitorInfo] = []
    for i, (hmon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors()):
        info = win32api.GetMonitorInfo(hmon)
        x1, y1, x2, y2 = info["Monitor"]
        monitors.append(
            MonitorInfo(
                index=i,
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
                is_primary=info.get("Flags", 0) == 1,
            )
        )
    return monitors


class MonitorHighlight(tk.Toplevel):
    """Cadre rouge affiché sur les bords d'un écran, pour le repérer au survol."""

    BORDER = 12

    def __init__(self, parent, monitor: MonitorInfo):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-disabled", True)  # ne vole ni le focus ni les clics
        except tk.TclError:
            pass
        self.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
        self.configure(bg="red")
        try:
            self.attributes("-transparentcolor", "black")
        except tk.TclError:
            pass
        inner_w = max(1, monitor.width - 2 * self.BORDER)
        inner_h = max(1, monitor.height - 2 * self.BORDER)
        tk.Frame(self, bg="black").place(x=self.BORDER, y=self.BORDER, width=inner_w, height=inner_h)


class ScreenPicker(ctk.CTkToplevel):
    def __init__(self, parent, on_selected: Callable[[MonitorInfo], None]):
        super().__init__(parent)
        self.title("Choisir l'écran")
        self.resizable(False, False)
        self._on_selected = on_selected
        self._highlight: Optional[MonitorHighlight] = None

        ctk.CTkLabel(
            self, text="Survolez pour repérer l'écran, cliquez pour l'utiliser", font=("Segoe UI", 13)
        ).pack(padx=24, pady=(18, 10))

        monitors = list_monitors()
        if not monitors:
            ctk.CTkLabel(self, text="Aucun écran détecté.").pack(padx=24, pady=10)
        for monitor in monitors:
            btn = ctk.CTkButton(self, text=monitor.label, width=260, command=lambda m=monitor: self._choose(m))
            btn.pack(padx=24, pady=6)
            btn.bind("<Enter>", lambda e, m=monitor: self._show_highlight(m))
            btn.bind("<Leave>", lambda e: self._hide_highlight())

        ctk.CTkButton(self, text="Annuler", fg_color="transparent", command=self._close).pack(
            padx=24, pady=(8, 18)
        )

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - self.winfo_width()) // 2}+{(sh - self.winfo_height()) // 2}")

    def _show_highlight(self, monitor: MonitorInfo) -> None:
        self._hide_highlight()
        self._highlight = MonitorHighlight(self, monitor)

    def _hide_highlight(self) -> None:
        if self._highlight is not None:
            self._highlight.destroy()
            self._highlight = None

    def _choose(self, monitor: MonitorInfo) -> None:
        self._hide_highlight()
        self.destroy()
        self._on_selected(monitor)

    def _close(self) -> None:
        self._hide_highlight()
        self.destroy()
