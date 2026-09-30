"""Fenêtre principale (prod) : logo, statut (avec le détail d'un problème), état du
panneau LED, gros timer. Minimaliste par design — les réglages et le journal vivent
dans la fenêtre "dev" (``DevWindow``), ouverte via Ctrl+Maj+D."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

import customtkinter as ctk
from PIL import ImageTk

from apex_ocr import __version__
from apex_ocr.config import AppConfig
from apex_ocr.health import HealthStatus
from apex_ocr.led.panel import LedStatus
from apex_ocr.session import DisplayValue
from apex_ocr.ui import branding

DEV_WINDOW_SHORTCUT = "<Control-Shift-KeyPress-D>"


@dataclass
class MainWindowCallbacks:
    on_toggle_dev: Callable[[], None]
    on_close: Callable[[], None]


class MainWindow(ctk.CTk):
    def __init__(self, config: AppConfig, callbacks: MainWindowCallbacks):
        super().__init__()
        ctk.set_appearance_mode("dark")
        try:
            ctk.set_default_color_theme(branding.THEME_PATH)
        except Exception:
            ctk.set_default_color_theme("green")

        self._cb = callbacks
        self.title(f"{branding.APP_NAME} — v{__version__}")
        self.geometry("480x460")
        self.minsize(400, 380)
        self.protocol("WM_DELETE_WINDOW", self._cb.on_close)
        self.bind(DEV_WINDOW_SHORTCUT, lambda e: self._cb.on_toggle_dev())

        self._build_layout()
        self.set_taskbar_icon(HealthStatus.IDLE)
        # CustomTkinter retouche la fenêtre (DPI, barre de titre sombre) juste
        # après sa création sur Windows, ce qui peut écraser l'icône posée
        # trop tôt -> on la repose après coup pour être sûr qu'elle tienne.
        self.after(300, lambda: self.set_taskbar_icon(HealthStatus.IDLE))

    def set_taskbar_icon(self, status: HealthStatus) -> None:
        """Icône de la fenêtre/barre des tâches, teintée selon le statut
        (même logique visuelle que l'icône systray)."""
        try:
            img = branding.build_status_icon(64, branding.HEALTH_TINTS[status])
            self._icon_photo = ImageTk.PhotoImage(img)
            self.wm_iconphoto(True, self._icon_photo)
        except Exception:
            pass

    # ---- construction ----------------------------------------------------

    def _build_layout(self) -> None:
        self._build_header()

        status_row = ctk.CTkFrame(self, fg_color="transparent")
        status_row.pack(fill="x", padx=16, pady=(6, 0))
        self.status_dot = tk.Canvas(status_row, width=14, height=14, highlightthickness=0)
        self.status_dot.pack(side="left")
        self._status_dot_id = self.status_dot.create_oval(2, 2, 12, 12, fill=branding.STATUS_GREY, outline="")
        self.status_lbl = ctk.CTkLabel(status_row, text="En attente")
        self.status_lbl.pack(side="left", padx=6)
        # Détail lisible du problème courant (« Base Apex Timing injoignable : … »).
        self.status_detail_lbl = ctk.CTkLabel(self, text="", text_color=branding.PRIMARY_RED,
                                              wraplength=440, justify="left", anchor="w")
        self.status_detail_lbl.pack(fill="x", padx=16)

        led_row = ctk.CTkFrame(self, fg_color="transparent")
        led_row.pack(fill="x", padx=16, pady=(2, 0))
        ctk.CTkLabel(led_row, text="Panneau LED :").pack(side="left")
        self.led_dot = tk.Canvas(led_row, width=14, height=14, highlightthickness=0)
        self.led_dot.pack(side="left", padx=(6, 0))
        self._led_dot_id = self.led_dot.create_oval(2, 2, 12, 12, fill=branding.STATUS_GREY, outline="")
        self.led_lbl = ctk.CTkLabel(led_row, text="Non connecté")
        self.led_lbl.pack(side="left", padx=6)

        timer_frame = ctk.CTkFrame(self)
        timer_frame.pack(fill="both", expand=True, padx=16, pady=12)
        timer_bg = tk.Frame(timer_frame, bg="black")
        timer_bg.pack(fill="both", expand=True, padx=10, pady=10)
        self.time_lbl = tk.Label(
            timer_bg, text="--:--", font=("", 52, "bold"), fg="#FFFFFF", bg="black"
        )
        self.time_lbl.pack(expand=True)
        self.laps_lbl = tk.Label(
            timer_bg, text="", font=("", 24, "bold"), fg=branding.PRIMARY_RED, bg="black"
        )
        self.laps_lbl.pack(pady=(0, 16))

    def _build_header(self) -> None:
        logo = branding.load_logo()
        if logo is None:
            return
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 0))
        display_w = 160
        display_h = int(logo.height * (display_w / logo.width))
        self._header_logo = ctk.CTkImage(light_image=logo, dark_image=logo, size=(display_w, display_h))
        ctk.CTkLabel(header, image=self._header_logo, text="").pack(side="left")

    # ---- mise à jour depuis l'orchestrateur ------------------------------

    def set_display(self, value: DisplayValue) -> None:
        self.time_lbl.configure(text=value.time_text)
        self.laps_lbl.configure(text=f"{value.laps_done} / {value.laps_total}" if value.laps_total is not None else "")

    def set_health(self, status: HealthStatus, detail: str = "") -> None:
        label, color = branding.HEALTH_LABELS[status]
        self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self.status_lbl.configure(text=label)
        self.status_detail_lbl.configure(text=detail)
        self.set_taskbar_icon(status)

    def set_led_status(self, status: LedStatus, detail: str = "") -> None:
        label, color = branding.LED_LABELS[status]
        if detail and status == LedStatus.RETRYING:
            label = f"{label} — {detail}"
        self.led_dot.itemconfig(self._led_dot_id, fill=color)
        self.led_lbl.configure(text=label)
