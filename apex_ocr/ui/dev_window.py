"""Fenêtre "dev" : configuration, calibration, test OCR, panneau LED, journal.
Masquée par défaut, ouverte via le raccourci Ctrl+Maj+D sur la fenêtre
principale (voir ``MainWindow``). Trois onglets : « Capture & OCR »,
« Panneau LED », « Diagnostics »."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import colorchooser
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from apex_ocr.config import AppConfig
from apex_ocr.health import HealthStatus
from apex_ocr.led.panel import LedStatus
from apex_ocr.led.rendering import COLOR_HEX, color_index
from apex_ocr.ui import branding

LED_BRIGHTNESS_DEBOUNCE_MS = 400

# Bornes des champs numériques (valeur hors plage ou vide -> ancienne valeur rétablie).
OCR_INTERVAL_MIN_MS, OCR_INTERVAL_MAX_MS = 150, 5000     # Tesseract met ~150 ms par lecture
TOLERANCE_MIN_S, TOLERANCE_MAX_S = 1, 30
LOST_TIMEOUT_MIN_S, LOST_TIMEOUT_MAX_S = 3, 120
ALERT_SECONDS_MIN, ALERT_SECONDS_MAX = 5, 600
ALERT_LAPS_MIN, ALERT_LAPS_MAX = 1, 50
CHUNK_MIN, CHUNK_MAX = 1, 3


@dataclass
class DevWindowCallbacks:
    on_refresh_windows: Callable[[], None]          # asynchrone : le résultat arrive via set_window_titles()
    on_browse_tesseract: Callable[[], Optional[str]]
    on_select_zone: Callable[[], None]
    on_test_ocr: Callable[[], None]
    on_start: Callable[[], None]
    on_stop: Callable[[], None]
    on_open_test_page: Callable[[], None]
    on_config_changed: Callable[[], None]
    on_auto_calibrate: Callable[[], None]
    on_cancel_calibrate: Callable[[], None]
    on_clear_errors: Callable[[], None]
    on_open_logs: Callable[[], None]
    on_open_config: Callable[[], None]
    on_led_scan: Callable[[], None]
    on_led_toggle: Callable[[], None]
    on_led_color: Callable[[tuple], None]
    on_led_brightness: Callable[[int], None]
    on_led_alert_color: Callable[[tuple], None]
    on_led_alert_seconds: Callable[[int], None]
    on_led_alert_laps: Callable[[int], None]
    on_led_laps_only: Callable[[bool], None]
    on_led_show_laps: Callable[[bool], None]
    on_led_idle_clock: Callable[[bool], None]
    on_led_wifi_autoconnect: Callable[[bool], None]
    on_led_chunk_minutes: Callable[[int], None]
    on_led_password: Callable[[str], None]
    on_log_level: Callable[[str], None]


class DevWindow(ctk.CTkToplevel):
    def __init__(self, parent, config: AppConfig, callbacks: DevWindowCallbacks):
        super().__init__(parent)
        self._cb = callbacks
        self.title("Apex Timing OCR — Dev")
        self.geometry("960x680")
        self.minsize(820, 560)   # tient sur un portable 1366×768 (barre des tâches comprise)
        # Fermer la fenêtre (croix, Échap) la cache plutôt que la détruit :
        # elle garde son état (journal, aperçu) prête à rouvrir instantanément.
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda e: self.withdraw())

        self._preview_photo: Optional[ImageTk.PhotoImage] = None
        self._preview_raw: Optional[Image.Image] = None
        self._preview_processed: Optional[Image.Image] = None
        self._led_brightness_after: Optional[str] = None  # timer de debounce du curseur de luminosité

        self._build_layout(config)
        self.withdraw()

    # ---- construction ----------------------------------------------------

    def _build_layout(self, config: AppConfig) -> None:
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.tab_capture = self.tabs.add("Capture & OCR")
        self.tab_led = self.tabs.add("Panneau LED")
        self.tab_diag = self.tabs.add("Diagnostics")

        self._build_capture_tab(config)
        self._build_led_tab(config)
        self._build_diag_tab(config)

    # -- onglet Capture & OCR ---------------------------------------------------

    def _build_capture_tab(self, config: AppConfig) -> None:
        tab = self.tab_capture
        pad = {"padx": 12, "pady": 5}
        label_w = 110

        cfg_frame = ctk.CTkFrame(tab)
        cfg_frame.pack(fill="x", padx=6, pady=(6, 6))

        self.tess_var = tk.StringVar(value=config.tesseract_path)
        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Tesseract :", width=label_w, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=self.tess_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(row, text="...", width=32, command=self._on_browse_tess).pack(side="left")

        self.window_var = tk.StringVar(value=config.window_title)
        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Fenêtre :", width=label_w, anchor="w").pack(side="left")
        self.window_combo = ctk.CTkComboBox(row, variable=self.window_var, values=[])
        self.window_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.refresh_btn = ctk.CTkButton(row, text="↻", width=32, command=self._on_refresh_windows)
        self.refresh_btn.pack(side="left")

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Zone :", width=label_w, anchor="w").pack(side="left")
        self.zone_label = ctk.CTkLabel(row, text=self.format_zone(config.zone))
        self.zone_label.pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text="Définir la zone", command=self._cb.on_select_zone).pack(side="left")

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Seuil :", width=label_w, anchor="w").pack(side="left")
        self.threshold_var = tk.IntVar(value=config.threshold)
        ctk.CTkSlider(row, from_=0, to=255, variable=self.threshold_var, width=220).pack(side="left")
        self.threshold_lbl = ctk.CTkLabel(row, text=str(config.threshold), width=36)
        self.threshold_lbl.pack(side="left", padx=6)
        self.threshold_var.trace_add(
            "write", lambda *_: self.threshold_lbl.configure(text=str(self.threshold_var.get()))
        )
        self.calibrate_btn = ctk.CTkButton(row, text="Auto", width=60, command=self._cb.on_auto_calibrate)
        self.calibrate_btn.pack(side="left", padx=(6, 0))
        self.cancel_calibrate_btn = ctk.CTkButton(
            row, text="Annuler", width=70, state="disabled", command=self._cb.on_cancel_calibrate,
        )
        self.cancel_calibrate_btn.pack(side="left", padx=(6, 0))

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Intervalle :", width=label_w, anchor="w").pack(side="left")
        self.interval_var = tk.StringVar(value=str(config.ocr_interval_ms))
        self._numeric_entry(row, self.interval_var, 60, OCR_INTERVAL_MIN_MS, OCR_INTERVAL_MAX_MS,
                            "Intervalle OCR", self._cb.on_config_changed).pack(side="left")
        ctk.CTkLabel(row, text=f"ms (≥ {OCR_INTERVAL_MIN_MS} ms, Tesseract ~150 ms/lecture)").pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row, text="Tolérance :").pack(side="left")
        self.tolerance_var = tk.StringVar(value=str(config.resync_tolerance_seconds))
        self._numeric_entry(row, self.tolerance_var, 44, TOLERANCE_MIN_S, TOLERANCE_MAX_S,
                            "Tolérance de resynchronisation", self._cb.on_config_changed).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(row, text="s").pack(side="left", padx=4)

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Signal perdu :", width=label_w, anchor="w").pack(side="left")
        self.ocr_lost_timeout_var = tk.StringVar(value=str(int(config.ocr_lost_timeout_seconds)))
        self._numeric_entry(row, self.ocr_lost_timeout_var, 50, LOST_TIMEOUT_MIN_S, LOST_TIMEOUT_MAX_S,
                            "Signal perdu", self._cb.on_config_changed).pack(side="left")
        ctk.CTkLabel(row, text=f"s sans lecture valide avant d'arrêter la session ({LOST_TIMEOUT_MIN_S}–{LOST_TIMEOUT_MAX_S})").pack(side="left", padx=4)

        prev_frame = ctk.CTkFrame(tab)
        prev_frame.pack(fill="x", padx=6, pady=6)
        head = ctk.CTkFrame(prev_frame, fg_color="transparent")
        head.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(head, text="Aperçu de la zone capturée", anchor="w").pack(side="left")
        self.preview_mode_var = tk.StringVar(value="Brute")
        ctk.CTkSegmentedButton(
            head, values=["Brute", "Prétraitée"], variable=self.preview_mode_var,
            command=lambda _v: self._redraw_preview(), width=180,
        ).pack(side="left", padx=(16, 0))
        ctk.CTkLabel(head, text="Dernière lecture :").pack(side="left", padx=(24, 4))
        self.last_ocr_lbl = ctk.CTkLabel(head, text="—", font=("Consolas", 13, "bold"), anchor="w")
        self.last_ocr_lbl.pack(side="left", fill="x", expand=True)
        self.preview_canvas = tk.Canvas(prev_frame, height=64, bg="#1e1e1e", highlightthickness=0)
        self.preview_canvas.pack(fill="x", padx=8, pady=8)
        self.preview_canvas.bind("<Configure>", lambda e: self._redraw_preview())

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=6, pady=4)
        self.start_btn = ctk.CTkButton(btn_row, text="▶  Démarrer", command=self._cb.on_start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(btn_row, text="■  Arrêter", command=self._cb.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.test_ocr_btn = ctk.CTkButton(btn_row, text="Test OCR", command=self._cb.on_test_ocr)
        self.test_ocr_btn.pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Page de test", command=self._cb.on_open_test_page).pack(side="right", padx=4)

        self.refresh_windows(config.window_title)

    # -- onglet Panneau LED -----------------------------------------------------

    def _build_led_tab(self, config: AppConfig) -> None:
        tab = self.tab_led
        pad = {"padx": 12, "pady": 5}
        label_w = 130

        conn_frame = ctk.CTkFrame(tab)
        conn_frame.pack(fill="x", padx=6, pady=(6, 6))

        row = ctk.CTkFrame(conn_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Panneau LED (IP) :", width=label_w, anchor="w").pack(side="left")
        self.led_host_var = tk.StringVar(value=config.led_host)
        ctk.CTkEntry(row, textvariable=self.led_host_var, width=160).pack(side="left", padx=(0, 6))
        self.led_scan_btn = ctk.CTkButton(row, text="Tester", width=80, command=self._cb.on_led_scan)
        self.led_scan_btn.pack(side="left", padx=(0, 6))
        self.led_connect_btn = ctk.CTkButton(row, text="Connecter", width=110, command=self._cb.on_led_toggle)
        self.led_connect_btn.pack(side="left")

        row = ctk.CTkFrame(conn_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Mot de passe :", width=label_w, anchor="w").pack(side="left")
        self.led_password_var = tk.StringVar(value=config.led_password)
        pw_entry = ctk.CTkEntry(row, textvariable=self.led_password_var, width=160, show="•")
        pw_entry.pack(side="left", padx=(0, 6))
        pw_entry.bind("<FocusOut>", lambda e: self._emit_password())
        pw_entry.bind("<Return>", lambda e: self._emit_password())
        self._led_password_applied = config.led_password
        self.led_wifi_var = tk.BooleanVar(value=config.led_wifi_autoconnect)
        ctk.CTkSwitch(
            row, text="Rejoindre le Wi-Fi RHX8 automatiquement", variable=self.led_wifi_var,
            command=lambda: self._cb.on_led_wifi_autoconnect(self.led_wifi_var.get()),
        ).pack(side="left", padx=(10, 0))

        row = ctk.CTkFrame(conn_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Statut :", width=label_w, anchor="w").pack(side="left")
        self.led_dot = tk.Canvas(row, width=14, height=14, highlightthickness=0)
        self.led_dot.pack(side="left")
        self._led_dot_id = self.led_dot.create_oval(2, 2, 12, 12, fill=branding.STATUS_GREY, outline="")
        self.led_status_lbl = ctk.CTkLabel(row, text="Non connecté", anchor="w")
        self.led_status_lbl.pack(side="left", fill="x", expand=True, padx=(6, 10))

        disp_frame = ctk.CTkFrame(tab)
        disp_frame.pack(fill="x", padx=6, pady=6)

        row = ctk.CTkFrame(disp_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Couleur du texte :", width=label_w, anchor="w").pack(side="left")
        self._led_color_hex = COLOR_HEX[color_index(config.led_color)]
        self.led_color_btn = ctk.CTkButton(
            row, text="", width=60, fg_color=self._led_color_hex, hover_color=self._led_color_hex,
            border_width=1, border_color=branding.STATUS_GREY, command=self._on_pick_led_color,
        )
        self.led_color_btn.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row, text="Luminosité :").pack(side="left")
        level = max(1, min(16, int(config.led_brightness)))
        self.led_brightness_slider = ctk.CTkSlider(
            row, from_=1, to=16, number_of_steps=15, width=190, command=self._on_led_brightness_moved,
        )
        self.led_brightness_slider.set(level)
        self.led_brightness_slider.pack(side="left", padx=(6, 0))
        self.led_brightness_lbl = ctk.CTkLabel(row, text=f"{level}/16", width=44)
        self.led_brightness_lbl.pack(side="left", padx=6)

        row = ctk.CTkFrame(disp_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Affichage :", width=label_w, anchor="w").pack(side="left")
        self.led_show_laps_var = tk.BooleanVar(value=config.led_show_laps)
        ctk.CTkSwitch(
            row, text="Tours à côté du temps", variable=self.led_show_laps_var,
            command=lambda: self._cb.on_led_show_laps(self.led_show_laps_var.get()),
        ).pack(side="left", padx=(0, 14))
        self.led_laps_only_var = tk.BooleanVar(value=config.led_laps_only)
        ctk.CTkSwitch(
            row, text="Tours seuls", variable=self.led_laps_only_var,
            command=lambda: self._cb.on_led_laps_only(self.led_laps_only_var.get()),
        ).pack(side="left", padx=(0, 14))
        self.led_idle_clock_var = tk.BooleanVar(value=config.led_idle_clock)
        ctk.CTkSwitch(
            row, text="Hors course : afficher l'heure", variable=self.led_idle_clock_var,
            command=lambda: self._cb.on_led_idle_clock(self.led_idle_clock_var.get()),
        ).pack(side="left")

        row = ctk.CTkFrame(disp_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Tranches :", width=label_w, anchor="w").pack(side="left")
        self.led_chunk_var = tk.StringVar(value=str(config.led_resync_minutes))
        self._numeric_entry(row, self.led_chunk_var, 40, CHUNK_MIN, CHUNK_MAX, "Tranches du décompte",
                            lambda: self._cb.on_led_chunk_minutes(int(self.led_chunk_var.get()))).pack(side="left")
        ctk.CTkLabel(row, text=f"min par programme envoyé au panneau ({CHUNK_MIN}–{CHUNK_MAX})").pack(side="left", padx=4)
        ctk.CTkLabel(
            disp_frame, anchor="w", justify="left", wraplength=660, text_color=branding.ACCENT_GREY,
            text="Le panneau joue chaque tranche tout seul (pas de clignotement à l'intérieur) mais repart du "
                 "début au bout de ~4 min : un bref clignotement à chaque changement de tranche est inévitable.",
        ).pack(fill="x", padx=(12 + label_w, 12), pady=(0, 4))

        row = ctk.CTkFrame(disp_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Alerte :", width=label_w, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text="Couleur :").pack(side="left")
        self._led_alert_color_hex = COLOR_HEX[color_index(config.led_alert_color)]
        self.led_alert_color_btn = ctk.CTkButton(
            row, text="", width=60, fg_color=self._led_alert_color_hex, hover_color=self._led_alert_color_hex,
            border_width=1, border_color=branding.STATUS_GREY, command=self._on_pick_led_alert_color,
        )
        self.led_alert_color_btn.pack(side="left", padx=6)
        ctk.CTkLabel(row, text="Dernières").pack(side="left", padx=(6, 2))
        self.led_alert_seconds_var = tk.StringVar(value=str(config.led_alert_seconds))
        self._numeric_entry(row, self.led_alert_seconds_var, 50, ALERT_SECONDS_MIN, ALERT_SECONDS_MAX, "Alerte (secondes)",
                            lambda: self._cb.on_led_alert_seconds(int(self.led_alert_seconds_var.get()))).pack(side="left")
        ctk.CTkLabel(row, text="s  /").pack(side="left", padx=(2, 8))
        self.led_alert_laps_var = tk.StringVar(value=str(config.led_alert_laps))
        self._numeric_entry(row, self.led_alert_laps_var, 40, ALERT_LAPS_MIN, ALERT_LAPS_MAX, "Alerte (tours)",
                            lambda: self._cb.on_led_alert_laps(int(self.led_alert_laps_var.get()))).pack(side="left")
        ctk.CTkLabel(row, text="derniers tours").pack(side="left", padx=(2, 0))
        self.led_alert_warn_lbl = ctk.CTkLabel(disp_frame, text="", text_color=branding.STATUS_AMBER, anchor="w")
        self.led_alert_warn_lbl.pack(fill="x", padx=12, pady=(0, 6))
        self._check_alert_color_visible()

    # -- onglet Diagnostics -----------------------------------------------------

    def _build_diag_tab(self, config: AppConfig) -> None:
        tab = self.tab_diag
        diag_frame = ctk.CTkFrame(tab)
        diag_frame.pack(fill="x", padx=6, pady=(6, 6))
        diag_row = ctk.CTkFrame(diag_frame, fg_color="transparent")
        diag_row.pack(fill="x", padx=8, pady=(8, 2))

        self.status_dot = tk.Canvas(diag_row, width=14, height=14, highlightthickness=0)
        self.status_dot.pack(side="left")
        self._status_dot_id = self.status_dot.create_oval(2, 2, 12, 12, fill=branding.STATUS_GREY, outline="")
        self.status_lbl = ctk.CTkLabel(diag_row, text="En attente", width=110, anchor="w")
        self.status_lbl.pack(side="left", padx=(6, 16))
        self.error_count_lbl = ctk.CTkLabel(diag_row, text="Erreurs détectées : 0")
        self.error_count_lbl.pack(side="left", padx=(0, 16))
        self.last_error_lbl = ctk.CTkLabel(diag_row, text="Depuis la dernière erreur : —")
        self.last_error_lbl.pack(side="left", padx=(0, 16))
        ctk.CTkButton(diag_row, text="Effacer", width=70, command=self._cb.on_clear_errors).pack(side="right")

        self.health_detail_lbl = ctk.CTkLabel(diag_frame, text="", anchor="w", text_color=branding.PRIMARY_RED,
                                              wraplength=860, justify="left")
        self.health_detail_lbl.pack(fill="x", padx=8, pady=(0, 8))

        tools_row = ctk.CTkFrame(diag_frame, fg_color="transparent")
        tools_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(tools_row, text="Ouvrir le dossier des journaux", command=self._cb.on_open_logs).pack(side="left", padx=(0, 8))
        ctk.CTkButton(tools_row, text="Ouvrir config.json", command=self._cb.on_open_config).pack(side="left")
        ctk.CTkLabel(tools_row, text="Niveau de journal :").pack(side="left", padx=(24, 4))
        self.log_level_var = tk.StringVar(value=config.log_level)
        ctk.CTkOptionMenu(
            tools_row, variable=self.log_level_var, values=["DEBUG", "INFO", "WARNING"],
            width=110, command=lambda v: self._cb.on_log_level(v),
        ).pack(side="left")

        log_frame = ctk.CTkFrame(tab)
        log_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        ctk.CTkLabel(log_frame, text="Journal de la session (l'historique complet est dans apex_ocr.log)",
                     anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.log_text = ctk.CTkTextbox(log_frame, state="disabled", font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    # ---- champs numériques validés -----------------------------------------

    def _numeric_entry(self, parent, var: tk.StringVar, width: int, minimum: int, maximum: int,
                       label: str, on_valid: Callable[[], None]) -> ctk.CTkEntry:
        """Champ entier appliqué à la sortie du champ / Entrée seulement : une valeur vide
        ou hors [minimum, maximum] est refusée, l'ancienne valeur revient et le journal le dit.
        (Pas de sauvegarde à chaque frappe : « 60 » tapé chiffre par chiffre ne passe plus par « 6 ».)"""
        state = {"last": var.get()}
        vcmd = (self.register(self._validate_digits), "%P")
        entry = ctk.CTkEntry(parent, textvariable=var, width=width, validate="key", validatecommand=vcmd)

        def commit(_event=None):
            text = var.get().strip()
            if text.isdigit() and minimum <= int(text) <= maximum:
                if text != state["last"]:
                    state["last"] = text
                    on_valid()
                return
            self.log(f"{label} : valeur « {text or 'vide'} » refusée (attendu {minimum}–{maximum}), "
                     f"{state['last']} conservé.")
            var.set(state["last"])

        entry.bind("<FocusOut>", commit)
        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry._apex_commit = commit  # pour les tests / relecture forcée
        entry._apex_state = state
        return entry

    @staticmethod
    def _validate_digits(proposed: str) -> bool:
        return proposed == "" or proposed.isdigit()

    # ---- panneau LED : actions ------------------------------------------------

    def _on_pick_led_color(self) -> None:
        rgb, _ = colorchooser.askcolor(color=self._led_color_hex, parent=self, title="Couleur du texte LED")
        if rgb is None:
            return
        rgb = tuple(int(c) for c in rgb)
        self._led_color_hex = COLOR_HEX[color_index(rgb)]   # 8 couleurs : montrer la vraie
        self.led_color_btn.configure(fg_color=self._led_color_hex, hover_color=self._led_color_hex)
        self._check_alert_color_visible()
        self._cb.on_led_color(rgb)

    def _on_pick_led_alert_color(self) -> None:
        rgb, _ = colorchooser.askcolor(color=self._led_alert_color_hex, parent=self, title="Couleur d'alerte LED")
        if rgb is None:
            return
        rgb = tuple(int(c) for c in rgb)
        self._led_alert_color_hex = COLOR_HEX[color_index(rgb)]
        self.led_alert_color_btn.configure(fg_color=self._led_alert_color_hex, hover_color=self._led_alert_color_hex)
        self._check_alert_color_visible()
        self._cb.on_led_alert_color(rgb)

    def _check_alert_color_visible(self) -> None:
        """Texte et alerte ramenés à la même des 8 couleurs = alerte invisible : prévenir."""
        same = self._led_color_hex == self._led_alert_color_hex
        self.led_alert_warn_lbl.configure(
            text="⚠ La couleur d'alerte est identique à celle du texte sur le panneau : l'alerte ne se verra pas."
            if same else ""
        )

    def _emit_password(self) -> None:
        pw = self.led_password_var.get()
        if pw and pw != self._led_password_applied:
            self._led_password_applied = pw
            self._cb.on_led_password(pw)

    def _on_led_brightness_moved(self, value: float) -> None:
        # Appelé à chaque pixel de glissement : l'étiquette suit tout de suite,
        # le panneau n'est prévenu qu'une fois le curseur immobile.
        level = int(round(value))
        self.led_brightness_lbl.configure(text=f"{level}/16")
        if self._led_brightness_after is not None:
            self.after_cancel(self._led_brightness_after)
        self._led_brightness_after = self.after(LED_BRIGHTNESS_DEBOUNCE_MS, self._emit_led_brightness, level)

    def _emit_led_brightness(self, level: int) -> None:
        self._led_brightness_after = None
        self._cb.on_led_brightness(level)

    # ---- capture : actions ----------------------------------------------------

    def _on_browse_tess(self) -> None:
        path = self._cb.on_browse_tesseract()
        if path:
            self.tess_var.set(path)
            self._cb.on_config_changed()

    def _on_refresh_windows(self) -> None:
        self.refresh_windows(self.window_var.get())

    def refresh_windows(self, keep_selected: str = "") -> None:
        """Demande la liste des fenêtres (en tâche de fond côté appli) ; ``set_window_titles``
        la reçoit. La sélection courante est conservée."""
        self._keep_selected = keep_selected
        self.refresh_btn.configure(state="disabled")
        self._cb.on_refresh_windows()

    def set_window_titles(self, titles: list[str]) -> None:
        self.window_combo.configure(values=titles)
        self.refresh_btn.configure(state="normal")
        if getattr(self, "_keep_selected", ""):
            self.window_var.set(self._keep_selected)

    def toggle(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

    @staticmethod
    def format_zone(zone) -> str:
        if zone:
            x, y, w, h = zone
            return f"x={x}  y={y}  {w}×{h} px"
        return "Non définie"

    # ---- lecture des valeurs courantes -----------------------------------

    @staticmethod
    def _parse_int(var: tk.StringVar, fallback: int, minimum: int, maximum: int) -> int:
        """Lit un champ numérique en tolérant un champ vide ou invalide (les champs sont
        validés à la sortie, mais on peut lire pendant l'édition) -> repli sur la
        dernière valeur de config connue plutôt qu'une exception."""
        text = var.get().strip()
        if not text.isdigit():
            return fallback
        value = int(text)
        return value if minimum <= value <= maximum else fallback

    def current_config_values(self, fallback: AppConfig) -> dict:
        return {
            "window_title": self.window_var.get().strip(),
            "tesseract_path": self.tess_var.get().strip(),
            "threshold": int(self.threshold_var.get()),
            "ocr_interval_ms": self._parse_int(self.interval_var, fallback.ocr_interval_ms,
                                               OCR_INTERVAL_MIN_MS, OCR_INTERVAL_MAX_MS),
            "resync_tolerance_seconds": self._parse_int(self.tolerance_var, fallback.resync_tolerance_seconds,
                                                        TOLERANCE_MIN_S, TOLERANCE_MAX_S),
            "ocr_lost_timeout_seconds": float(self._parse_int(
                self.ocr_lost_timeout_var, int(fallback.ocr_lost_timeout_seconds),
                LOST_TIMEOUT_MIN_S, LOST_TIMEOUT_MAX_S)),
        }

    # ---- mise à jour depuis l'orchestrateur ------------------------------

    def set_zone(self, zone) -> None:
        self.zone_label.configure(text=self.format_zone(zone))

    def set_threshold(self, value: int) -> None:
        self.threshold_var.set(value)

    def set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def set_calibrating(self, calibrating: bool) -> None:
        self.calibrate_btn.configure(state="disabled" if calibrating else "normal",
                                     text="Calibration..." if calibrating else "Auto")
        self.cancel_calibrate_btn.configure(state="normal" if calibrating else "disabled")

    def set_testing_ocr(self, testing: bool) -> None:
        self.test_ocr_btn.configure(state="disabled" if testing else "normal",
                                    text="Lecture..." if testing else "Test OCR")

    def led_host_input(self) -> str:
        """IP (ou « ip:port ») saisie pour le panneau LED, sans espaces autour."""
        return self.led_host_var.get().strip()

    def set_led_host(self, host: str) -> None:
        self.led_host_var.set(host)

    def set_led_scanning(self, scanning: bool) -> None:
        self.led_scan_btn.configure(state="disabled" if scanning else "normal",
                                    text="Test..." if scanning else "Tester")

    def set_led_control(self, wanted: bool, status: LedStatus) -> None:
        """Libellé du bouton d'après l'état réel : « Déconnecter » seulement quand le
        panneau est vraiment relié, « Annuler » pendant une tentative (sinon on
        afficherait « Déconnecter » alors que rien n'est connecté), « Connecter » sinon."""
        if not wanted:
            text = "Connecter"
        elif status == LedStatus.CONNECTED:
            text = "Déconnecter"
        else:
            text = "Annuler"
        self.led_connect_btn.configure(text=text)

    def set_led_status(self, status: LedStatus, detail: str = "") -> None:
        label, color = branding.LED_LABELS[status]
        if detail and status == LedStatus.RETRYING:
            label = f"{label} — {detail}"
        self.led_dot.itemconfig(self._led_dot_id, fill=color)
        self.led_status_lbl.configure(text=label)

    def set_health(self, status: HealthStatus, detail: str = "") -> None:
        label, color = branding.HEALTH_LABELS[status]
        self.status_dot.itemconfig(self._status_dot_id, fill=color)
        self.status_lbl.configure(text=label)
        self.health_detail_lbl.configure(text=detail)

    def set_diagnostics(self, error_count: int, since_last_error: str) -> None:
        self.error_count_lbl.configure(text=f"Erreurs détectées : {error_count}")
        self.last_error_lbl.configure(text=f"Depuis la dernière erreur : {since_last_error}")

    def set_last_ocr_text(self, text: str) -> None:
        self.last_ocr_lbl.configure(text=text if text else "(rien)")

    def set_preview_image(self, raw: Image.Image, processed: Optional[Image.Image] = None) -> None:
        """Aperçu : image brute de la zone et, si fournie, l'image prétraitée (celle
        réellement envoyée à Tesseract) ; la bascule choisit laquelle est affichée."""
        self._preview_raw = raw
        self._preview_processed = processed
        self._redraw_preview()

    def _redraw_preview(self) -> None:
        img = self._preview_processed if self.preview_mode_var.get() == "Prétraitée" else self._preview_raw
        if img is None:
            img = self._preview_raw
        if img is None:
            return
        cw = self.preview_canvas.winfo_width() or 640
        ch = int(self.preview_canvas.cget("height")) or 64
        iw, ih = img.size
        scale = min(cw / iw, ch / ih, 4.0)
        dw, dh = max(1, int(iw * scale)), max(1, int(ih * scale))
        disp = img.resize((dw, dh), Image.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(disp)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._preview_photo)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
