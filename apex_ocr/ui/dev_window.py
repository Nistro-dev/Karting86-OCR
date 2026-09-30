"""Fenêtre "dev" : réglages de la source Apex Timing, panneau LED, journal.
Masquée par défaut, ouverte via le raccourci Ctrl+Maj+D sur la fenêtre
principale (voir ``MainWindow``). Trois onglets : « Apex Timing »,
« Panneau LED », « Diagnostics »."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import colorchooser
from typing import Callable, Optional

import customtkinter as ctk

from apex_ocr.config import AppConfig
from apex_ocr.health import HealthStatus
from apex_ocr.led.panel import LedStatus
from apex_ocr.led.rendering import COLOR_HEX, color_index
from apex_ocr.ui import branding

LED_BRIGHTNESS_DEBOUNCE_MS = 400

# Bornes des champs numériques (valeur hors plage ou vide -> ancienne valeur rétablie).
POLL_MIN_MS, POLL_MAX_MS = 100, 5000
STALE_MIN_S, STALE_MAX_S = 3, 120
ALERT_SECONDS_MIN, ALERT_SECONDS_MAX = 5, 600
ALERT_LAPS_MIN, ALERT_LAPS_MAX = 1, 50
CHUNK_MIN, CHUNK_MAX = 1, 3


@dataclass
class DevWindowCallbacks:
    on_browse_data_dir: Callable[[], Optional[str]]
    on_start: Callable[[], None]
    on_stop: Callable[[], None]
    on_probe: Callable[[], None]
    on_config_changed: Callable[[], None]
    on_clear_errors: Callable[[], None]
    on_open_logs: Callable[[], None]
    on_open_config: Callable[[], None]
    on_led_scan: Callable[[], None]
    on_led_toggle: Callable[[], None]
    on_led_color: Callable[[tuple], None]
    on_led_brightness: Callable[[int], None]
    on_led_warn_color: Callable[[tuple], None]
    on_led_warn_seconds: Callable[[int], None]
    on_led_warn_laps: Callable[[int], None]
    on_led_alert_color: Callable[[tuple], None]
    on_led_alert_seconds: Callable[[int], None]
    on_led_alert_laps: Callable[[int], None]
    on_led_laps_only: Callable[[bool], None]
    on_led_show_laps: Callable[[bool], None]
    on_led_idle_clock: Callable[[bool], None]
    on_led_rotate_180: Callable[[bool], None]
    on_led_wifi_autoconnect: Callable[[bool], None]
    on_led_chunk_minutes: Callable[[int], None]
    on_led_password: Callable[[str], None]
    on_log_level: Callable[[str], None]


class DevWindow(ctk.CTkToplevel):
    def __init__(self, parent, config: AppConfig, callbacks: DevWindowCallbacks):
        super().__init__(parent)
        self._cb = callbacks
        self.title(f"{branding.APP_NAME} — Dev")
        self.geometry("960x640")
        self.minsize(820, 540)   # tient sur un portable 1366×768 (barre des tâches comprise)
        # Fermer la fenêtre (croix, Échap) la cache plutôt que la détruit :
        # elle garde son état (journal) prête à rouvrir instantanément.
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.bind("<Escape>", lambda e: self.withdraw())

        self._led_brightness_after: Optional[str] = None  # timer de debounce du curseur de luminosité

        self._build_layout(config)
        self.withdraw()

    # ---- construction ----------------------------------------------------

    def _build_layout(self, config: AppConfig) -> None:
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.tab_source = self.tabs.add("Apex Timing")
        self.tab_led = self.tabs.add("Panneau LED")
        self.tab_diag = self.tabs.add("Diagnostics")

        self._build_source_tab(config)
        self._build_led_tab(config)
        self._build_diag_tab(config)

    # -- onglet Apex Timing -----------------------------------------------------

    def _build_source_tab(self, config: AppConfig) -> None:
        tab = self.tab_source
        pad = {"padx": 12, "pady": 5}
        label_w = 150

        cfg_frame = ctk.CTkFrame(tab)
        cfg_frame.pack(fill="x", padx=6, pady=(6, 6))

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Base de données :", width=label_w, anchor="w").pack(side="left")
        self.source_dot = tk.Canvas(row, width=14, height=14, highlightthickness=0)
        self.source_dot.pack(side="left")
        self._source_dot_id = self.source_dot.create_oval(2, 2, 12, 12, fill=branding.STATUS_GREY, outline="")
        self.source_status_lbl = ctk.CTkLabel(row, text="Lecture arrêtée", anchor="w")
        self.source_status_lbl.pack(side="left", fill="x", expand=True, padx=(6, 10))

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Session en cours :", width=label_w, anchor="w").pack(side="left")
        self.last_reading_lbl = ctk.CTkLabel(row, text="—", font=("Consolas", 14, "bold"), anchor="w")
        self.last_reading_lbl.pack(side="left", fill="x", expand=True)

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Dossier des bases :", width=label_w, anchor="w").pack(side="left")
        self.data_dir_var = tk.StringVar(value=config.apex_data_dir)
        entry = ctk.CTkEntry(row, textvariable=self.data_dir_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<FocusOut>", lambda e: self._cb.on_config_changed())
        entry.bind("<Return>", lambda e: self._cb.on_config_changed())
        ctk.CTkButton(row, text="...", width=32, command=self._on_browse_data_dir).pack(side="left")

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Firebird :", width=label_w, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text="hôte").pack(side="left")
        self.db_host_var = tk.StringVar(value=config.apex_db_host)
        self._text_entry(row, self.db_host_var, 120).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(row, text="utilisateur").pack(side="left")
        self.db_user_var = tk.StringVar(value=config.apex_db_user)
        self._text_entry(row, self.db_user_var, 90).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(row, text="mot de passe").pack(side="left")
        self.db_password_var = tk.StringVar(value=config.apex_db_password)
        self._text_entry(row, self.db_password_var, 120, show="•").pack(side="left", padx=(4, 0))

        row = ctk.CTkFrame(cfg_frame, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text="Lecture :", width=label_w, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text="toutes les").pack(side="left")
        self.poll_var = tk.StringVar(value=str(config.apex_poll_ms))
        self._numeric_entry(row, self.poll_var, 60, POLL_MIN_MS, POLL_MAX_MS, "Cadence de lecture",
                            self._cb.on_config_changed).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(row, text=f"ms ({POLL_MIN_MS}–{POLL_MAX_MS})").pack(side="left", padx=(4, 16))
        ctk.CTkLabel(row, text="Base muette après").pack(side="left")
        self.stale_var = tk.StringVar(value=str(int(config.apex_stale_seconds)))
        self._numeric_entry(row, self.stale_var, 44, STALE_MIN_S, STALE_MAX_S, "Base muette",
                            self._cb.on_config_changed).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(row, text=f"s → statut rouge, session abandonnée ({STALE_MIN_S}–{STALE_MAX_S})").pack(side="left", padx=4)

        ctk.CTkLabel(
            cfg_frame, anchor="w", justify="left", wraplength=880, text_color=branding.ACCENT_GREY,
            text="La base du jour (DAYAAAAMMJJ.GO) est créée par GoKarts à son lancement et lue en lecture seule : "
                 "départ, pause, fin et durée de la session, tours du leader. Rien n'est écrit côté Apex Timing.",
        ).pack(fill="x", padx=12, pady=(0, 8))

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=6, pady=4)
        self.start_btn = ctk.CTkButton(btn_row, text="▶  Démarrer", command=self._cb.on_start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(btn_row, text="■  Arrêter", command=self._cb.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.probe_btn = ctk.CTkButton(btn_row, text="Tester la base", command=self._cb.on_probe)
        self.probe_btn.pack(side="right", padx=4)

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
        ctk.CTkLabel(row, text="Orientation :", width=label_w, anchor="w").pack(side="left")
        self.led_rotate_var = tk.BooleanVar(value=config.led_rotate_180)
        ctk.CTkSwitch(
            row, text="Panneau à l'envers (image tournée de 180°)", variable=self.led_rotate_var,
            command=lambda: self._cb.on_led_rotate_180(self.led_rotate_var.get()),
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

        self._led_warn_color_hex = COLOR_HEX[color_index(config.led_warn_color)]
        self._led_alert_color_hex = COLOR_HEX[color_index(config.led_alert_color)]
        self.led_warn_color_btn, self.led_warn_seconds_var, self.led_warn_laps_var = self._build_threshold_row(
            disp_frame, pad, label_w, "Avertissement :", self._led_warn_color_hex, self._on_pick_led_warn_color,
            config.led_warn_seconds, config.led_warn_laps, "Avertissement",
            lambda: self._cb.on_led_warn_seconds(int(self.led_warn_seconds_var.get())),
            lambda: self._cb.on_led_warn_laps(int(self.led_warn_laps_var.get())))
        self.led_alert_color_btn, self.led_alert_seconds_var, self.led_alert_laps_var = self._build_threshold_row(
            disp_frame, pad, label_w, "Alerte :", self._led_alert_color_hex, self._on_pick_led_alert_color,
            config.led_alert_seconds, config.led_alert_laps, "Alerte",
            lambda: self._cb.on_led_alert_seconds(int(self.led_alert_seconds_var.get())),
            lambda: self._cb.on_led_alert_laps(int(self.led_alert_laps_var.get())))
        ctk.CTkLabel(
            disp_frame, anchor="w", justify="left", wraplength=660, text_color=branding.ACCENT_GREY,
            text="À l'approche de la fin (temps ou tours), le texte passe d'abord en couleur d'avertissement, "
                 "puis en couleur d'alerte.",
        ).pack(fill="x", padx=(12 + label_w, 12), pady=(0, 4))
        self.led_alert_warn_lbl = ctk.CTkLabel(disp_frame, text="", text_color=branding.STATUS_AMBER, anchor="w")
        self.led_alert_warn_lbl.pack(fill="x", padx=12, pady=(0, 6))
        self._check_alert_color_visible()

    def _build_threshold_row(self, parent, pad, label_w, label, color_hex, pick_cmd, seconds, laps, name,
                             on_seconds, on_laps):
        """Ligne « Couleur [■] Dernières [N] s / [M] derniers tours » d'un palier."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", **pad)
        ctk.CTkLabel(row, text=label, width=label_w, anchor="w").pack(side="left")
        ctk.CTkLabel(row, text="Couleur :").pack(side="left")
        btn = ctk.CTkButton(row, text="", width=60, fg_color=color_hex, hover_color=color_hex,
                            border_width=1, border_color=branding.STATUS_GREY, command=pick_cmd)
        btn.pack(side="left", padx=6)
        ctk.CTkLabel(row, text="Dernières").pack(side="left", padx=(6, 2))
        seconds_var = tk.StringVar(value=str(seconds))
        self._numeric_entry(row, seconds_var, 50, ALERT_SECONDS_MIN, ALERT_SECONDS_MAX, f"{name} (secondes)",
                            on_seconds).pack(side="left")
        ctk.CTkLabel(row, text="s  /").pack(side="left", padx=(2, 8))
        laps_var = tk.StringVar(value=str(laps))
        self._numeric_entry(row, laps_var, 40, ALERT_LAPS_MIN, ALERT_LAPS_MAX, f"{name} (tours)", on_laps).pack(side="left")
        ctk.CTkLabel(row, text="derniers tours").pack(side="left", padx=(2, 0))
        return btn, seconds_var, laps_var

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
        ctk.CTkLabel(log_frame, text="Journal de la session (l'historique complet est dans le fichier de journal)",
                     anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.log_text = ctk.CTkTextbox(log_frame, state="disabled", font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    # ---- champs -------------------------------------------------------------

    def _text_entry(self, parent, var: tk.StringVar, width: int, show: Optional[str] = None) -> ctk.CTkEntry:
        """Champ texte appliqué à la sortie du champ / Entrée (comme les champs numériques)."""
        entry = ctk.CTkEntry(parent, textvariable=var, width=width, show=show)
        entry.bind("<FocusOut>", lambda e: self._cb.on_config_changed())
        entry.bind("<Return>", lambda e: self._cb.on_config_changed())
        return entry

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

    def _on_pick_led_warn_color(self) -> None:
        rgb, _ = colorchooser.askcolor(color=self._led_warn_color_hex, parent=self, title="Couleur d'avertissement LED")
        if rgb is None:
            return
        rgb = tuple(int(c) for c in rgb)
        self._led_warn_color_hex = COLOR_HEX[color_index(rgb)]
        self.led_warn_color_btn.configure(fg_color=self._led_warn_color_hex, hover_color=self._led_warn_color_hex)
        self._check_alert_color_visible()
        self._cb.on_led_warn_color(rgb)

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
        """Deux paliers ramenés à la même des 8 couleurs = palier invisible : prévenir."""
        hexes = (self._led_color_hex, self._led_warn_color_hex, self._led_alert_color_hex)
        same = len(set(hexes)) < 3
        self.led_alert_warn_lbl.configure(
            text="⚠ Deux des trois couleurs (texte, avertissement, alerte) sont identiques sur le panneau : "
                 "un des paliers ne se verra pas."
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

    # ---- source : actions -----------------------------------------------------

    def _on_browse_data_dir(self) -> None:
        path = self._cb.on_browse_data_dir()
        if path:
            self.data_dir_var.set(path)
            self._cb.on_config_changed()

    def toggle(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
            self.focus_force()
        else:
            self.withdraw()

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
            "apex_data_dir": self.data_dir_var.get().strip() or fallback.apex_data_dir,
            "apex_db_host": self.db_host_var.get().strip() or fallback.apex_db_host,
            "apex_db_user": self.db_user_var.get().strip() or fallback.apex_db_user,
            "apex_db_password": self.db_password_var.get(),
            "apex_poll_ms": self._parse_int(self.poll_var, fallback.apex_poll_ms, POLL_MIN_MS, POLL_MAX_MS),
            "apex_stale_seconds": float(self._parse_int(self.stale_var, int(fallback.apex_stale_seconds),
                                                        STALE_MIN_S, STALE_MAX_S)),
        }

    # ---- mise à jour depuis l'orchestrateur ------------------------------

    def set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def set_probing(self, probing: bool) -> None:
        self.probe_btn.configure(state="disabled" if probing else "normal",
                                 text="Test..." if probing else "Tester la base")

    def set_source_status(self, text: str, color: Optional[str] = None) -> None:
        self.source_dot.itemconfig(self._source_dot_id, fill=color or branding.STATUS_GREY)
        self.source_status_lbl.configure(text=text)

    def set_last_reading(self, text: str) -> None:
        self.last_reading_lbl.configure(text=text or "—")

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

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
