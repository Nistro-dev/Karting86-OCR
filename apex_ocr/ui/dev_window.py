"""Fenêtre "dev" : configuration, calibration, test OCR, journal, affichage
externe. Masquée par défaut, ouverte via le raccourci Ctrl+Maj+D sur la
fenêtre principale (voir ``MainWindow``)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import colorchooser
from dataclasses import dataclass
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from apex_ocr.config import AppConfig
from apex_ocr.health import HealthStatus
from apex_ocr.led.panel import LedStatus

_HEALTH_LABELS = {
    HealthStatus.IDLE: ("En attente", "#8a8a8a"),
    HealthStatus.ACTIVE: ("Course suivie", "#00c94a"),
    HealthStatus.ERROR: ("Problème", "#ED1B24"),
}

_LED_LABELS = {
    LedStatus.DISABLED: ("Non connecté", "#8a8a8a"),
    LedStatus.CONNECTING: ("Connexion...", "#e0a000"),
    LedStatus.CONNECTED: ("Connecté", "#00c94a"),
    LedStatus.RETRYING: ("Reconnexion...", "#ED1B24"),
}


@dataclass
class DevWindowCallbacks:
    on_refresh_windows: Callable[[], list[str]]
    on_browse_tesseract: Callable[[], Optional[str]]
    on_select_zone: Callable[[], None]
    on_test_ocr: Callable[[], None]
    on_start: Callable[[], None]
    on_stop: Callable[[], None]
    on_open_external: Callable[[], None]
    on_external_enabled: Callable[[bool], None]
    on_config_changed: Callable[[], None]
    on_auto_calibrate: Callable[[], None]
    on_clear_errors: Callable[[], None]
    on_led_scan: Callable[[], None]
    on_led_toggle: Callable[[], None]
    on_led_color: Callable[[tuple], None]


class DevWindow(ctk.CTkToplevel):
    def __init__(self, parent, config: AppConfig, callbacks: DevWindowCallbacks):
        super().__init__(parent)
        self._cb = callbacks
        self.title("Apex Timing OCR — Dev")
        self.geometry("720x760")
        self.minsize(620, 640)
        # Fermer la fenêtre (croix, Échap) la cache plutôt que la détruit :
        # elle garde son état (journal, aperçu) prête à rouvrir instantanément.
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda e: self.withdraw())

        self._preview_photo: Optional[ImageTk.PhotoImage] = None

        self._build_layout(config)
        self.withdraw()

    # ---- construction ----------------------------------------------------

    def _build_layout(self, config: AppConfig) -> None:
        pad = {"padx": 12, "pady": 6}

        cfg_frame = ctk.CTkFrame(self)
        cfg_frame.pack(fill="x", padx=14, pady=(14, 8))

        self.tess_var = tk.StringVar(value=config.tesseract_path)
        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Tesseract :", width=100, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=self.tess_var, width=380).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="...", width=32, command=self._on_browse_tess).pack(side="left")

        self.window_var = tk.StringVar(value=config.window_title)
        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Fenêtre :", width=100, anchor="w").pack(side="left")
        self.window_combo = ctk.CTkComboBox(row, variable=self.window_var, values=[], width=380)
        self.window_combo.pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="↻", width=32, command=self._on_refresh_windows).pack(side="left")

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Zone :", width=100, anchor="w").pack(side="left")
        self.zone_label = ctk.CTkLabel(row, text=self.format_zone(config.zone))
        self.zone_label.pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text="Définir la zone", command=self._cb.on_select_zone).pack(side="left")

        digit_vcmd = (self.register(self._validate_digits), "%P")

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Seuil :", width=100, anchor="w").pack(side="left")
        self.threshold_var = tk.IntVar(value=config.threshold)
        ctk.CTkSlider(row, from_=0, to=255, variable=self.threshold_var, width=190).pack(side="left")
        self.threshold_lbl = ctk.CTkLabel(row, text=str(config.threshold), width=36)
        self.threshold_lbl.pack(side="left", padx=6)
        self.threshold_var.trace_add(
            "write", lambda *_: self.threshold_lbl.configure(text=str(self.threshold_var.get()))
        )
        ctk.CTkButton(row, text="Auto", width=50, command=self._cb.on_auto_calibrate).pack(side="left", padx=(6, 0))

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Intervalle :", width=100, anchor="w").pack(side="left")
        self.interval_var = tk.StringVar(value=str(config.ocr_interval_ms))
        ctk.CTkEntry(
            row, textvariable=self.interval_var, width=60, validate="key", validatecommand=digit_vcmd
        ).pack(side="left")
        ctk.CTkLabel(row, text="ms").pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row, text="Tolérance :", width=70, anchor="w").pack(side="left")
        self.tolerance_var = tk.StringVar(value=str(config.resync_tolerance_seconds))
        ctk.CTkEntry(
            row, textvariable=self.tolerance_var, width=40, validate="key", validatecommand=digit_vcmd
        ).pack(side="left")
        ctk.CTkLabel(row, text="s").pack(side="left", padx=4)

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Signal perdu :", width=100, anchor="w").pack(side="left")
        self.ocr_lost_timeout_var = tk.StringVar(value=str(int(config.ocr_lost_timeout_seconds)))
        ctk.CTkEntry(
            row, textvariable=self.ocr_lost_timeout_var, width=50, validate="key", validatecommand=digit_vcmd
        ).pack(side="left")
        ctk.CTkLabel(row, text="s sans lecture valide avant d'arrêter la session").pack(side="left", padx=4)

        self._build_led_frame(config, pad)

        prev_frame = ctk.CTkFrame(self)
        prev_frame.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(prev_frame, text="Aperçu zone capturée", anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.preview_canvas = tk.Canvas(prev_frame, height=60, bg="#1e1e1e", highlightthickness=0)
        self.preview_canvas.pack(fill="x", padx=8, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=4)
        self.start_btn = ctk.CTkButton(btn_row, text="▶  Démarrer", command=self._cb.on_start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(btn_row, text="■  Arrêter", command=self._cb.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.external_btn = ctk.CTkButton(btn_row, text="Affichage externe", command=self._cb.on_open_external)
        self.external_btn.pack(side="left", padx=4)
        self.external_enabled_var = tk.BooleanVar(value=config.external_enabled)
        ctk.CTkSwitch(
            btn_row, text="Activé", variable=self.external_enabled_var, width=60,
            command=lambda: self._cb.on_external_enabled(self.external_enabled_var.get()),
        ).pack(side="left", padx=(2, 4))
        self.set_external_enabled(config.external_enabled)
        ctk.CTkButton(btn_row, text="Test OCR", command=self._cb.on_test_ocr).pack(side="right", padx=4)

        diag_frame = ctk.CTkFrame(self)
        diag_frame.pack(fill="x", padx=14, pady=(0, 8))
        diag_row = ctk.CTkFrame(diag_frame, fg_color="transparent")
        diag_row.pack(fill="x", padx=8, pady=8)

        self.status_dot = tk.Canvas(diag_row, width=14, height=14, highlightthickness=0)
        self.status_dot.pack(side="left")
        self._status_dot_id = self.status_dot.create_oval(2, 2, 12, 12, fill="#8a8a8a", outline="")
        self.status_lbl = ctk.CTkLabel(diag_row, text="En attente", width=110, anchor="w")
        self.status_lbl.pack(side="left", padx=(6, 16))

        self.error_count_lbl = ctk.CTkLabel(diag_row, text="Erreurs détectées : 0")
        self.error_count_lbl.pack(side="left", padx=(0, 16))

        self.last_error_lbl = ctk.CTkLabel(diag_row, text="Depuis la dernière erreur : —")
        self.last_error_lbl.pack(side="left", padx=(0, 16))

        ctk.CTkButton(diag_row, text="Effacer", width=70, command=self._cb.on_clear_errors).pack(side="right")

        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(8, 14))
        ctk.CTkLabel(log_frame, text="Journal", anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.log_text = ctk.CTkTextbox(log_frame, height=140, state="disabled", font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.refresh_windows(config.window_title)

    def _build_led_frame(self, config: AppConfig, pad: dict) -> None:
        led_frame = ctk.CTkFrame(self)
        led_frame.pack(fill="x", padx=14, pady=8)

        row = ctk.CTkFrame(led_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Panneau LED :", width=100, anchor="w").pack(side="left")
        self.led_var = tk.StringVar(value=self._led_label_for(config.led_address, config.led_known_devices))
        self.led_combo = ctk.CTkComboBox(row, variable=self.led_var, values=[], width=300)
        self.led_combo.pack(side="left", padx=(0, 6))
        self.set_led_devices(config.led_known_devices)
        self.led_scan_btn = ctk.CTkButton(row, text="Scanner", width=80, command=self._cb.on_led_scan)
        self.led_scan_btn.pack(side="left", padx=(0, 6))
        self.led_connect_btn = ctk.CTkButton(row, text="Connecter", width=100, command=self._cb.on_led_toggle)
        self.led_connect_btn.pack(side="left")

        row = ctk.CTkFrame(led_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Statut :", width=100, anchor="w").pack(side="left")
        self.led_dot = tk.Canvas(row, width=14, height=14, highlightthickness=0)
        self.led_dot.pack(side="left")
        self._led_dot_id = self.led_dot.create_oval(2, 2, 12, 12, fill="#8a8a8a", outline="")
        self.led_status_lbl = ctk.CTkLabel(row, text="Non connecté", width=230, anchor="w")
        self.led_status_lbl.pack(side="left", padx=(6, 10))
        ctk.CTkLabel(row, text="Couleur :").pack(side="left")
        self._led_color_hex = "#%02x%02x%02x" % tuple(config.led_color)
        self.led_color_btn = ctk.CTkButton(
            row, text="", width=60, fg_color=self._led_color_hex, hover_color=self._led_color_hex,
            border_width=1, border_color="#8a8a8a", command=self._on_pick_led_color,
        )
        self.led_color_btn.pack(side="left", padx=6)

    def _on_pick_led_color(self) -> None:
        rgb, hex_ = colorchooser.askcolor(color=self._led_color_hex, parent=self, title="Couleur du texte LED")
        if rgb is None:
            return
        self._led_color_hex = hex_
        self.led_color_btn.configure(fg_color=hex_, hover_color=hex_)
        self._cb.on_led_color(tuple(int(c) for c in rgb))

    @staticmethod
    def _led_label(name: str, address: str) -> str:
        return f"{name} ({address})"

    def _led_label_for(self, address: str, devices: list) -> str:
        for name, addr in devices:
            if addr == address:
                return self._led_label(name, addr)
        return address

    def _on_browse_tess(self) -> None:
        path = self._cb.on_browse_tesseract()
        if path:
            self.tess_var.set(path)
            self._cb.on_config_changed()

    def _on_refresh_windows(self) -> None:
        self.refresh_windows(self.window_var.get())

    def refresh_windows(self, keep_selected: str = "") -> None:
        titles = self._cb.on_refresh_windows()
        self.window_combo.configure(values=titles)
        if keep_selected:
            self.window_var.set(keep_selected)

    def toggle(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

    @staticmethod
    def _validate_digits(proposed: str) -> bool:
        return proposed == "" or proposed.isdigit()

    @staticmethod
    def format_zone(zone) -> str:
        if zone:
            x, y, w, h = zone
            return f"x={x}  y={y}  {w}×{h} px"
        return "Non définie"

    # ---- lecture des valeurs courantes -----------------------------------

    @staticmethod
    def _parse_int(var: tk.StringVar, fallback: int, minimum: int = 0) -> int:
        """Lit un champ numérique en tolérant un champ vide ou invalide (la
        saisie clavier est déjà filtrée aux chiffres, mais un champ peut
        transiter par un état vide pendant l'édition) -> repli sur la
        dernière valeur de config connue plutôt qu'une exception."""
        text = var.get().strip()
        if not text:
            return fallback
        try:
            value = int(text)
        except ValueError:
            return fallback
        return max(minimum, value)

    def current_config_values(self, fallback: AppConfig) -> dict:
        return {
            "window_title": self.window_var.get().strip(),
            "tesseract_path": self.tess_var.get().strip(),
            "threshold": int(self.threshold_var.get()),
            "ocr_interval_ms": self._parse_int(self.interval_var, fallback.ocr_interval_ms, minimum=50),
            "resync_tolerance_seconds": self._parse_int(
                self.tolerance_var, fallback.resync_tolerance_seconds, minimum=1
            ),
            "ocr_lost_timeout_seconds": float(
                self._parse_int(
                    self.ocr_lost_timeout_var, int(fallback.ocr_lost_timeout_seconds), minimum=1
                )
            ),
        }

    # ---- mise à jour depuis l'orchestrateur ------------------------------

    def set_zone(self, zone) -> None:
        self.zone_label.configure(text=self.format_zone(zone))

    def set_threshold(self, value: int) -> None:
        self.threshold_var.set(value)

    def set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def set_external_enabled(self, enabled: bool) -> None:
        self.external_btn.configure(state="normal" if enabled else "disabled")

    def set_external_open(self, is_open: bool) -> None:
        self.external_btn.configure(text="Fermer l'affichage externe" if is_open else "Affichage externe")

    def led_address_input(self) -> str:
        """Adresse saisie ou choisie : « LED_BLE_x (AA:BB:...) » ou adresse brute."""
        value = self.led_var.get().strip()
        match = re.search(r"\(([^()]+)\)\s*$", value)
        return match.group(1).strip() if match else value

    def set_led_devices(self, devices: list, select_first: bool = False) -> None:
        labels = [self._led_label(n, a) for n, a in devices]
        self.led_combo.configure(values=labels)
        if select_first and labels:
            self.led_var.set(labels[0])

    def set_led_scanning(self, scanning: bool) -> None:
        self.led_scan_btn.configure(state="disabled" if scanning else "normal",
                                    text="Scan..." if scanning else "Scanner")

    def set_led_enabled(self, enabled: bool) -> None:
        self.led_connect_btn.configure(text="Déconnecter" if enabled else "Connecter")

    def set_led_status(self, status: LedStatus, detail: str = "") -> None:
        label, color = _LED_LABELS[status]
        if detail and status == LedStatus.RETRYING:
            label = f"{label} ({detail[:40]})"
        self.led_dot.itemconfig(self._led_dot_id, fill=color)
        self.led_status_lbl.configure(text=label)

    def set_health(self, status: HealthStatus) -> None:
        label, color = _HEALTH_LABELS[status]
        self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self.status_lbl.configure(text=label)

    def set_diagnostics(self, error_count: int, since_last_error: str) -> None:
        self.error_count_lbl.configure(text=f"Erreurs détectées : {error_count}")
        self.last_error_lbl.configure(text=f"Depuis la dernière erreur : {since_last_error}")

    def set_preview_image(self, pil_img: Image.Image) -> None:
        cw = self.preview_canvas.winfo_width() or 640
        iw, ih = pil_img.size
        scale = min(cw / iw, 60 / ih, 4.0)
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        disp = pil_img.resize((dw, dh), Image.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(disp)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(cw // 2, 30, anchor="center", image=self._preview_photo)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
