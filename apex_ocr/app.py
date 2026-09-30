"""Orchestrateur applicatif : relie config, source Apex Timing, session, santé, panneau LED et UI.

Toute mutation d'état (session, santé, widgets) passe par le thread principal Tk ;
la source Apex Timing (``ApexLiveSource``) tourne dans son thread et ne fait que lire
la base, le panneau LED dans le sien.

Deux fenêtres : ``window`` (minimaliste, toujours visible/réduite dans la zone de
notification) et ``dev_window`` (réglages Apex Timing / panneau LED / journal,
masquée par défaut, ouverte via Ctrl+Maj+D).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from tkinter import TclError, filedialog
from typing import Optional

from apex_ocr.config import AppConfig
from apex_ocr.health import HealthMonitor, HealthStatus
from apex_ocr.led import wifi
from apex_ocr.led.content import panel_content
from apex_ocr.led.panel import LedPanel, LedStatus
from apex_ocr.led.protocol import DEFAULT_HOST, WIFI_SSID_PREFIX
from apex_ocr.led.rendering import COLOR_NAMES, color_index
from apex_ocr.logging_setup import set_log_level, setup_logging
from apex_ocr.paths import CONFIG_PATH, LOG_DIR, OUTPUT_PATH
from apex_ocr.power import PowerMonitor
from apex_ocr.readings import LenientReading
from apex_ocr.session import DisplayValue, SessionEvent, SessionState, SessionTracker, StopReason, current_display
from apex_ocr.source.apex_live import ApexLiveSource, LiveReading, LiveStatus, probe_database
from apex_ocr.ui import branding
from apex_ocr.ui.dev_window import DevWindow, DevWindowCallbacks
from apex_ocr.ui.main_window import MainWindow, MainWindowCallbacks
from apex_ocr.ui.tray import TrayIcon

UI_REFRESH_MS = 200
LED_WIFI_RETRY_S = 12   # panneau injoignable : nouvel essai Wi-Fi + panneau à cette cadence
ERROR_LOG_REPEAT_S = 60.0         # une même erreur récurrente n'est journalisée qu'une fois par minute

_REASON_LABELS = {
    StopReason.TIME_ZERO: "temps écoulé",
    StopReason.OCR_LOST: "base Apex Timing muette",
    StopReason.CANCELLED: "course annulée",
    StopReason.SOURCE_ENDED: "fin signalée par Apex Timing",
}


class App:
    def __init__(self) -> None:
        self.config = AppConfig.load()
        self.logger = setup_logging(self.config.log_retention_days, self.config.log_level)
        if self.config.loaded_from_legacy:
            self.config.save()
            self.logger.info("Réglages repris de l'ancienne version (Apex Timing OCR).")

        self.tracker = SessionTracker(ocr_lost_timeout_seconds=self.config.apex_stale_seconds, logger=self.logger)
        self.tracker.round_up = True   # afficher comme GoKarts (arrondi au supérieur)
        self.health = HealthMonitor()
        self._last_health_status: Optional[HealthStatus] = None
        self._last_output_text = ""
        self._error_count = 0
        self._last_error_wall: Optional[float] = None
        self._logged_errors: dict[str, float] = {}
        self._output_error_logged = False
        self._health_detail = ""

        self.running = False
        self.source: Optional[ApexLiveSource] = None
        self._source_fresh = False           # la base a répondu depuis moins de apex_stale_seconds
        self._last_source_status_text = ""
        self._last_reading_text = ""
        self._probing = False

        self.led = LedPanel(
            self.config.led_width,
            self.config.led_height,
            tuple(self.config.led_color),
            tuple(self.config.led_alert_color),
            self.logger,
            password=self.config.led_password,
            brightness=self.config.led_brightness,
            show_laps=self.config.led_show_laps,
            resync_minutes=self.config.led_resync_minutes,
            rotate_180=self.config.led_rotate_180,
            warn_rgb=tuple(self.config.led_warn_color),
        )
        self._last_led_status: Optional[tuple[LedStatus, str]] = None
        self._led_wanted = self.config.led_enabled   # « Déconnecter » ne vaut que pour la session
        self._wifi_joining = False
        self._wifi_last_attempt = 0.0

        self.window = MainWindow(
            self.config,
            MainWindowCallbacks(on_toggle_dev=self._toggle_dev_window, on_close=self._on_close),
        )
        # Une exception dans un callback Tk (bouton, after...) ne doit ni planter
        # l'appli ni disparaître : journalisée, l'appli continue.
        self.window.report_callback_exception = self._tk_exception

        dev_callbacks = DevWindowCallbacks(
            on_browse_data_dir=self._browse_data_dir,
            on_start=self.start,
            on_stop=self.stop,
            on_probe=self._probe_database,
            on_config_changed=self._persist_config_from_ui,
            on_clear_errors=self._clear_errors,
            on_open_logs=self._open_logs_folder,
            on_open_config=self._open_config_file,
            on_led_scan=self._led_scan,
            on_led_toggle=self._led_toggle,
            on_led_color=self._led_set_color,
            on_led_brightness=self._led_set_brightness,
            on_led_warn_color=self._led_set_warn_color,
            on_led_warn_seconds=self._led_set_warn_seconds,
            on_led_warn_laps=self._led_set_warn_laps,
            on_led_alert_color=self._led_set_alert_color,
            on_led_alert_seconds=self._led_set_alert_seconds,
            on_led_alert_laps=self._led_set_alert_laps,
            on_led_laps_only=self._led_set_laps_only,
            on_led_show_laps=self._led_set_show_laps,
            on_led_idle_clock=self._led_set_idle_clock,
            on_led_rotate_180=self._led_set_rotate_180,
            on_led_wifi_autoconnect=self._led_set_wifi_autoconnect,
            on_led_chunk_minutes=self._led_set_chunk_minutes,
            on_led_password=self._led_set_password,
            on_log_level=self._set_log_level,
        )
        self.dev_window = DevWindow(self.window, self.config, dev_callbacks)
        self.dev_window.set_led_control(self._led_wanted, self.led.status)

        self.tray = TrayIcon(
            on_show=lambda: self.window.after(0, self._show_window),
            on_quit=lambda: self.window.after(0, self._really_quit),
        )
        self.tray.start()

        # Mise en veille : fermer proprement la connexion au panneau AVANT (sinon la
        # carte garde une connexion « zombie » ~3 min au réveil) ; reprise : reconnexion.
        self.power = PowerMonitor(
            post=lambda fn: self.window.after(0, fn),
            on_suspend=self._on_suspend,
            on_resume=self._on_resume,
            on_endsession=self._on_endsession,   # arrêt du PC : écran noir envoyé avant d'être tué
        )
        self.power.start()

        self.dev_window.log("Application prête.")
        self.window.after(UI_REFRESH_MS, self._refresh_tick)

        # Prod : l'appli se réduit direct dans la zone de notification au lancement et lit
        # la base tout de suite ; rien à calibrer.
        self.window.withdraw()
        self.start()

        # Indépendant de la source : le panneau se (re)connecte tout seul au lancement
        # (Wi-Fi compris), puis retente en arrière-plan s'il est éteint/hors de portée.
        if self._led_wanted:
            self.logger.info("Connexion automatique au panneau LED %s...", self.config.led_host)
            self._led_connect(self.config.led_host)

    # ---- fenêtre dev -----------------------------------------------------

    def _toggle_dev_window(self) -> None:
        self.dev_window.toggle()

    def _open_logs_folder(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

    def _open_config_file(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            self.config.save()
        os.startfile(CONFIG_PATH)

    def _browse_data_dir(self) -> Optional[str]:
        path = filedialog.askdirectory(title="Dossier des bases Apex Timing (DAYAAAAMMJJ.GO)",
                                       initialdir=self.config.apex_data_dir or None)
        return path or None

    def _persist_config_from_ui(self) -> None:
        changed = False
        for key, value in self.dev_window.current_config_values(self.config).items():
            if getattr(self.config, key) != value:
                setattr(self.config, key, value)
                changed = True
        self.config.save()
        self.tracker.ocr_lost_timeout_seconds = self.config.apex_stale_seconds
        if changed and self.running:
            self.dev_window.log("Réglages Apex Timing modifiés : lecture relancée.")
            self.stop()
            self.start()

    # ---- source Apex Timing ---------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        self._persist_config_from_ui()   # valeurs des champs (sans effet de bord : pas encore en marche)
        self.running = True
        self.tracker.reset()
        self._source_fresh = False
        self.source = ApexLiveSource(
            self.logger, self.config.apex_data_dir, host=self.config.apex_db_host,
            user=self.config.apex_db_user, password=self.config.apex_db_password,
            fbclient_path=self.config.apex_fbclient_path, poll_s=self.config.apex_poll_ms / 1000,
        )
        self.source.start()
        self.dev_window.set_running(True)
        self.dev_window.log("Lecture de la base Apex Timing démarrée.")

    def stop(self) -> None:
        self.running = False
        src, self.source = self.source, None
        if src is not None:
            src.stop()
        self.tracker.reset()
        self._source_fresh = False
        self.dev_window.set_running(False)
        self._set_source_status("Lecture arrêtée", branding.STATUS_GREY)
        self.dev_window.log("Lecture de la base Apex Timing arrêtée.")

    def _poll_source(self, now: float) -> None:
        """Appelé à chaque rafraîchissement UI : lit la dernière lecture de la base et nourrit
        le suivi de session (départ confirmé sur 2 lectures décroissantes, puis horloge recalée
        exactement à chaque lecture, pause gelée, fin immédiate)."""
        src = self.source
        if src is None:
            return
        reading, last_ok = src.latest()
        fresh = last_ok > 0 and now - last_ok <= self.config.apex_stale_seconds
        if fresh != self._source_fresh:
            self._source_fresh = fresh
            if fresh:
                self.logger.info("Base Apex Timing lue : suivi des sessions actif.")
            else:
                self.logger.warning("Base Apex Timing muette depuis %.0f s (%s).",
                                    self.config.apex_stale_seconds, src.status_detail or src.status.name)
                self.tracker.set_paused(False, now)
        self._refresh_source_status(src, reading, fresh)
        if not fresh:
            self.health.record_capture_failure()
            if self.tracker.state == SessionState.RUNNING:
                # Plus de nouvelles : l'horloge interne continue quelques secondes, puis la
                # session est abandonnée (« base muette ») comme un signal perdu.
                self._handle_events(self.tracker.on_lenient_reading(LenientReading(None, None, None), now))
            return
        self.health.record_capture_success()
        if reading is None:
            if self.tracker.state == SessionState.RUNNING:
                self._handle_events(self.tracker.force_stop(now))
            elif self.tracker.state == SessionState.ARMED:
                self.tracker.reset()
            return
        if self.tracker.state == SessionState.RUNNING:
            self.tracker.set_paused(reading.paused, now)
            events = self.tracker.on_lenient_reading(reading.lenient(), now)
        else:
            events = self.tracker.on_strict_reading(reading.strict(), now)
        self._handle_events(events)
        if not reading.paused:
            self.tracker.sync_exact(reading.remaining_s, now)   # sans effet hors RUNNING

    def _set_source_status(self, text: str, color: Optional[str] = None) -> None:
        if text != self._last_source_status_text:
            self._last_source_status_text = text
            self.dev_window.set_source_status(text, color)

    def _refresh_source_status(self, src: ApexLiveSource, reading: Optional[LiveReading], fresh: bool) -> None:
        if src.status == LiveStatus.CONNECTED and fresh:
            if reading is None:
                self._set_source_status(f"Connectée ({os.path.basename(src.db_path)}), aucune session en cours",
                                        branding.STATUS_GREEN)
                text = "—"
            else:
                self._set_source_status(f"Connectée ({os.path.basename(src.db_path)}), session {reading.session_idx}"
                                        + (" en pause" if reading.paused else " en cours"), branding.STATUS_GREEN)
                laps = f"  {reading.laps_done}/{reading.laps_total}" if reading.laps_total is not None else ""
                text = f"{reading.time_text}{laps}"
        elif src.status in (LiveStatus.CONNECTING, LiveStatus.CONNECTED):
            self._set_source_status("Connexion...", branding.STATUS_AMBER)
            text = "—"
        else:
            detail = f" — {src.status_detail}" if src.status_detail else ""
            self._set_source_status(f"Indisponible{detail}", branding.PRIMARY_RED)
            text = "—"
        if text != self._last_reading_text:
            self._last_reading_text = text
            self.dev_window.set_last_reading(text)

    def _probe_database(self) -> None:
        """« Tester la base » : ouverture ponctuelle en lecture seule, en tâche de fond."""
        if self._probing:
            return
        self._persist_config_from_ui()
        self._probing = True
        self.dev_window.set_probing(True)
        self.dev_window.log("Test de la base Apex Timing...")
        cfg = self.config

        def work():
            report = probe_database(cfg.apex_data_dir, cfg.apex_db_host, cfg.apex_db_user, cfg.apex_db_password,
                                    cfg.apex_fbclient_path)
            try:
                self.window.after(0, self._on_probe_done, report)
            except (RuntimeError, TclError):
                pass
        threading.Thread(target=work, daemon=True, name="apex-probe").start()

    def _on_probe_done(self, report: str) -> None:
        self._probing = False
        self.dev_window.set_probing(False)
        self.dev_window.log(f"Test de la base : {report}")

    # ---- garde-fous : une exception ne tue pas la boucle Tk ------------------

    def _guarded(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:
            self._log_error_once(fn.__name__, exc)

    def _log_error_once(self, key: str, exc: Exception) -> None:
        """Journalise une erreur récurrente (même origine, même type) au plus une fois
        par ERROR_LOG_REPEAT_S, avec la trace : 5 lignes par seconde ne serviraient à rien."""
        signature = f"{key}:{type(exc).__name__}"
        now = time.monotonic()
        if now - self._logged_errors.get(signature, -ERROR_LOG_REPEAT_S) >= ERROR_LOG_REPEAT_S:
            self._logged_errors[signature] = now
            self.logger.exception("Erreur dans %s (l'appli continue) : %s", key, exc)

    def _tk_exception(self, exc_type, exc_value, exc_tb) -> None:
        self._log_error_once("tk_callback", exc_value if isinstance(exc_value, Exception) else Exception(str(exc_value)))

    def _handle_events(self, events: list[SessionEvent]) -> None:
        for event in events:
            if event == SessionEvent.ARMED:
                self.dev_window.log("Session vue dans la base — en attente que le chrono descende.")
            elif event == SessionEvent.STARTED:
                self.dev_window.log("Départ détecté — décompte démarré.")
            elif event == SessionEvent.RESYNCED:
                self.dev_window.log("Resynchronisation sur la base (écart détecté).")
            elif event == SessionEvent.STOPPED:
                result = self.tracker.last_completed
                label = _REASON_LABELS[result.reason]
                self.dev_window.log(f"Session terminée ({label}) : {result.time_text}")
                self.logger.info("Session terminée (%s) : %s", result.reason.name, result.time_text)

    # ---- rafraîchissement UI --------------------------------------------

    def _refresh_tick(self) -> None:
        # Quoi qu'il arrive dans le rafraîchissement, le tick suivant est planifié :
        # sinon une seule exception fige timer, panneau et santé pour de bon.
        try:
            self._refresh_once()
        except Exception as exc:
            self._log_error_once("refresh_tick", exc)
        finally:
            try:
                self.window.after(UI_REFRESH_MS, self._refresh_tick)
            except TclError:  # fenêtre détruite : l'appli se ferme
                pass

    def _refresh_once(self) -> None:
        now = time.monotonic()
        self._poll_source(now)
        if self.tracker.state == SessionState.RUNNING:
            self._handle_events(self.tracker.tick(now))

        display = current_display(self.tracker, now)
        self.window.set_display(display)
        self._sync_output(display)
        self.led.show(panel_content(
            self.tracker.state, display,
            laps_only=self.config.led_laps_only,
            warn_seconds=self.config.led_warn_seconds,
            alert_seconds=self.config.led_alert_seconds,
            warn_laps=self.config.led_warn_laps,
            alert_laps=self.config.led_alert_laps,
            idle_clock=self.config.led_idle_clock,
        ))
        self._refresh_led_status()
        self._led_watchdog()

        status = self.health.status_for(self.tracker.state)
        self._apply_health_status(status)

    def _sync_output(self, display: DisplayValue) -> None:
        if display.time_text == self._last_output_text:
            return
        self._last_output_text = display.time_text
        # Écriture atomique : le lecteur externe ne voit jamais un fichier vide/tronqué,
        # et s'il verrouille le fichier, l'erreur est journalisée une fois, pas à chaque tick.
        tmp = OUTPUT_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(display.time_text)
            os.replace(tmp, OUTPUT_PATH)
            self._output_error_logged = False
        except OSError as exc:
            if not self._output_error_logged:
                self._output_error_logged = True
                self.logger.warning("Écriture de %s impossible : %s", OUTPUT_PATH, exc)
        if display.is_live:
            laps = f" ({display.laps_done}/{display.laps_total})" if display.laps_total is not None else ""
            self.logger.info("Timer %s%s", display.time_text, laps)

    # ---- panneau LED ----------------------------------------------------

    def _refresh_led_status(self) -> None:
        current = (self.led.status, self.led.status_detail)
        if current != self._last_led_status:
            self._last_led_status = current
            self.dev_window.set_led_status(*current)
            self.window.set_led_status(*current)
            self.dev_window.set_led_control(self._led_wanted, self.led.status)

    def _led_host_from_ui(self) -> str:
        """IP saisie dans la fenêtre dev ; champ vide -> hôte par défaut (remis dans le champ)."""
        host = self.dev_window.led_host_input()
        if not host:
            host = DEFAULT_HOST
            self.dev_window.set_led_host(host)
        return host

    def _led_scan(self) -> None:
        """« Tester » : le panneau répond-il sur le réseau ? (sonde TCP, sans changer l'état de connexion)."""
        host = self._led_host_from_ui()
        if host != self.config.led_host:
            self.config.led_host = host
            self.config.save()
            if self._led_wanted:
                self.led.connect(host)  # nouvelle cible : le pilote se reconnecte dessus
        self.dev_window.set_led_scanning(True)
        self.dev_window.log("Test de connexion au panneau LED...")
        self.led.scan().add_done_callback(lambda fut: self.window.after(0, self._on_led_scan_done, fut))

    def _on_led_scan_done(self, fut) -> None:
        self.dev_window.set_led_scanning(False)
        try:
            devices = fut.result()
        except Exception as exc:
            self.dev_window.log(f"Test du panneau LED impossible : {exc}")
            return
        if devices:
            self.dev_window.log(f"Panneau LED joignable ({devices[0][1]}).")
            return
        # scan() sonde l'hôte passé à connect(), ou l'hôte par défaut tant que
        # le panneau n'est pas activé (statut DISABLED).
        probed = self.config.led_host if self.led.status != LedStatus.DISABLED else DEFAULT_HOST
        hint = f" L'IP saisie ({self.config.led_host}) sera utilisée à la connexion." if probed != self.config.led_host else ""
        self.dev_window.log(
            f"Panneau LED injoignable sur {probed} — vérifier le Wi-Fi {WIFI_SSID_PREFIX}… "
            f"(le PC doit être sur le réseau du panneau).{hint}"
        )

    def _led_toggle(self) -> None:
        """« Déconnecter » / « Connecter » : pour la session en cours seulement, le panneau
        est de nouveau rejoint automatiquement au prochain lancement."""
        if self._led_wanted:
            self._led_wanted = False
            self.led.disconnect()
            self.dev_window.set_led_control(False, self.led.status)
            self.dev_window.log("Panneau LED déconnecté (jusqu'au prochain lancement).")
            return
        host = self._led_host_from_ui()
        self.config.led_host = host
        self.config.save()
        self._led_wanted = True
        self.dev_window.set_led_control(True, self.led.status)
        self.dev_window.log(f"Connexion au panneau LED {host}...")
        self._led_connect(host)

    def _led_connect(self, host: str) -> None:
        """Demande la connexion au panneau ; avec ``led_wifi_autoconnect``, rejoint
        d'abord le Wi-Fi « RHX8-… » (netsh : plusieurs secondes -> thread)."""
        if not self.config.led_wifi_autoconnect:
            self.led.connect(host)
            return
        self.dev_window.log(f"Recherche du Wi-Fi {WIFI_SSID_PREFIX}… avant la connexion au panneau.")
        self._start_wifi_join(quiet=False)

    def _led_watchdog(self) -> None:
        """Tant que le panneau reste injoignable, retente le Wi-Fi « RHX8-… » (puis le
        panneau) toutes les LED_WIFI_RETRY_S : panneau allumé après l'appli, Wi-Fi coupé..."""
        if (not self._led_wanted or not self.config.led_wifi_autoconnect or self._wifi_joining
                or self.led.status != LedStatus.RETRYING
                or time.monotonic() - self._wifi_last_attempt < LED_WIFI_RETRY_S):
            return
        self._start_wifi_join(quiet=True)

    def _start_wifi_join(self, quiet: bool) -> None:
        self._wifi_joining = True
        self._wifi_last_attempt = time.monotonic()
        threading.Thread(target=self._join_wifi_then_connect, args=(quiet,), daemon=True, name="led-wifi").start()

    def _join_wifi_then_connect(self, quiet: bool) -> None:
        before = wifi.current_ssid()
        if before is not None and before.startswith(WIFI_SSID_PREFIX):
            # Déjà sur le bon réseau : rien à faire côté Wi-Fi ; c'est au pilote de
            # retenter le TCP (la carte peut garder brièvement son ancienne connexion).
            joined, message = False, None
        elif wifi.connect_to_prefix(WIFI_SSID_PREFIX):
            joined, message = True, f"Wi-Fi : réseau {wifi.current_ssid() or WIFI_SSID_PREFIX + '…'} rejoint."
        else:
            joined = False
            message = (
                f"Wi-Fi : aucun réseau {WIFI_SSID_PREFIX}… à portée (panneau éteint ?), réseau actuel : "
                f"{before or 'aucun'}. Nouvel essai dans {LED_WIFI_RETRY_S} s."
            )
        try:
            self.window.after(0, self._on_wifi_join_done, message, joined, quiet)
        except (RuntimeError, TclError):  # appli fermée entre-temps
            pass

    def _on_wifi_join_done(self, message: Optional[str], joined: bool, quiet: bool) -> None:
        self._wifi_joining = False
        if message and (joined or not quiet):   # les échecs répétés du chien de garde ne remplissent pas le journal
            self.dev_window.log(message)
            self.logger.info(message)
        elif message:
            self.logger.debug(message)
        # On (re)lance le TCP au démarrage/clic (not quiet) ou après un vrai rejoint Wi-Fi ;
        # sinon (chien de garde, déjà sur le réseau) le pilote retente tout seul.
        if self._led_wanted and (joined or not quiet):
            self.led.connect(self.config.led_host)

    def _led_set_color(self, rgb: tuple) -> None:
        self.config.led_color = list(rgb)
        self.config.save()
        self.led.set_color(rgb)
        self.dev_window.log(
            "Couleur du panneau LED : #%02x%02x%02x -> %s (8 couleurs disponibles)."
            % (*tuple(rgb), COLOR_NAMES[color_index(rgb)])
        )

    def _led_set_brightness(self, level: int) -> None:
        level = max(1, min(16, int(level)))
        if level == self.config.led_brightness:
            return
        self.config.led_brightness = level
        self.config.save()
        self.led.set_brightness(level)
        self.dev_window.log(f"Luminosité du panneau LED : {level}/16.")

    def _led_set_laps_only(self, enabled: bool) -> None:
        self.config.led_laps_only = enabled
        self.config.save()
        self.dev_window.log("Panneau LED : " + ("tours seuls" if enabled else "chrono + tours"))

    def _led_set_warn_color(self, rgb: tuple) -> None:
        self.config.led_warn_color = list(rgb)
        self.config.save()
        self.led.set_warn_color(rgb)
        self.dev_window.log("Couleur d'avertissement LED : #%02x%02x%02x" % tuple(rgb))

    def _led_set_warn_seconds(self, seconds: int) -> None:
        self.config.led_warn_seconds = seconds
        self.config.save()
        self.dev_window.log(f"Avertissement LED : {seconds} dernières secondes.")

    def _led_set_warn_laps(self, laps: int) -> None:
        self.config.led_warn_laps = laps
        self.config.save()
        self.dev_window.log(f"Avertissement LED : {laps} derniers tours.")

    def _led_set_alert_color(self, rgb: tuple) -> None:
        self.config.led_alert_color = list(rgb)
        self.config.save()
        self.led.set_alert_color(rgb)
        self.dev_window.log("Couleur d'alerte LED : #%02x%02x%02x" % tuple(rgb))

    def _led_set_alert_seconds(self, seconds: int) -> None:
        self.config.led_alert_seconds = seconds
        self.config.save()
        self.dev_window.log(f"Alerte LED : {seconds} dernières secondes.")

    def _led_set_alert_laps(self, laps: int) -> None:
        self.config.led_alert_laps = laps
        self.config.save()
        self.dev_window.log(f"Alerte LED : {laps} derniers tours.")

    def _led_set_show_laps(self, enabled: bool) -> None:
        self.config.led_show_laps = enabled
        self.config.save()
        self.led.set_show_laps(enabled)
        self.dev_window.log("Panneau LED : " + ("tours à côté du temps" if enabled else "temps seul"))

    def _led_set_idle_clock(self, enabled: bool) -> None:
        self.config.led_idle_clock = enabled
        self.config.save()
        self.dev_window.log("Panneau LED hors course : " + ("heure affichée" if enabled else "écran noir"))

    def _led_set_rotate_180(self, enabled: bool) -> None:
        self.config.led_rotate_180 = enabled
        self.config.save()
        self.led.set_rotate_180(enabled)
        self.dev_window.log("Panneau LED : " + ("image tournée de 180° (panneau à l'envers)" if enabled
                                                else "image à l'endroit"))

    def _led_set_wifi_autoconnect(self, enabled: bool) -> None:
        self.config.led_wifi_autoconnect = enabled
        self.config.save()
        self.dev_window.log("Wi-Fi RHX8 : " + ("rejoint automatiquement" if enabled else "laissé tel quel (manuel)"))

    def _led_set_chunk_minutes(self, minutes: int) -> None:
        self.config.led_resync_minutes = minutes
        self.config.save()
        self.led.set_chunk_minutes(minutes)
        self.dev_window.log(f"Panneau LED : tranches de {minutes} min (à partir de la prochaine tranche).")

    def _led_set_password(self, password: str) -> None:
        self.config.led_password = password
        self.config.save()
        self.led.set_password(password)
        self.dev_window.log("Mot de passe du panneau LED modifié (reconnexion).")

    # ---- journal ---------------------------------------------------------

    def _set_log_level(self, level: str) -> None:
        self.config.log_level = level
        self.config.save()
        set_log_level(level)
        self.dev_window.log(f"Niveau de journal : {level}.")

    # ---- santé -----------------------------------------------------------

    def _health_detail_text(self, status: HealthStatus) -> str:
        """Ce qui ne va pas, en clair (fenêtre principale, fenêtre dev, infobulle systray)."""
        if status != HealthStatus.ERROR:
            return ""
        if not self.running:
            return "Lecture de la base arrêtée (fenêtre dev → Démarrer)."
        src = self.source
        detail = (src.status_detail if src is not None else "") or "sans réponse"
        return f"Base Apex Timing injoignable : {detail}"

    def _apply_health_status(self, status: HealthStatus) -> None:
        # Pas de notification Windows ici (trop intrusif) -> l'icône colorée dans la
        # zone de notification suffit, l'historique reste dans le log.
        detail = self._health_detail_text(status)
        if status != self._last_health_status or detail != self._health_detail:
            self._health_detail = detail
            self.window.set_health(status, detail)
            self.dev_window.set_health(status, detail)
            self.tray.set_status(status, detail)
        if status != self._last_health_status:
            if status == HealthStatus.ERROR:
                self._error_count += 1
                self._last_error_wall = time.monotonic()
                self.logger.warning("Passage en état ERROR")
            elif self._last_health_status == HealthStatus.ERROR:
                self.logger.info("Sortie de l'état ERROR")
        self._last_health_status = status
        self.dev_window.set_diagnostics(self._error_count, self._format_since_last_error())

    def _clear_errors(self) -> None:
        self._error_count = 0
        self._last_error_wall = None
        self.dev_window.set_diagnostics(0, self._format_since_last_error())
        self.dev_window.log("Compteur d'erreurs réinitialisé.")

    def _format_since_last_error(self) -> str:
        if self._last_error_wall is None:
            return "aucune erreur"
        elapsed = int(time.monotonic() - self._last_error_wall)
        suffix = " (en cours)" if self._last_health_status == HealthStatus.ERROR else ""
        if elapsed < 60:
            return f"{elapsed}s{suffix}"
        if elapsed < 3600:
            return f"{elapsed // 60}min {elapsed % 60}s{suffix}"
        return f"{elapsed // 3600}h {(elapsed % 3600) // 60}min{suffix}"

    # ---- cycle de vie ----------------------------------------------------

    def _show_window(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _on_close(self) -> None:
        self._persist_config_from_ui()
        self.window.withdraw()
        self.dev_window.withdraw()
        self.dev_window.log("Réduit dans la zone de notification.")

    # ---- veille / reprise ----------------------------------------------

    def _on_suspend(self) -> None:
        self.logger.info("Mise en veille : fermeture propre de la connexion au panneau LED.")
        self.led.disconnect()

    def _on_resume(self) -> None:
        self.logger.info("Reprise après veille.")
        if self._led_wanted:
            self._led_connect(self.config.led_host)

    def _on_endsession(self) -> None:
        """Arrêt / redémarrage / fermeture de session Windows : appelé en synchrone dans
        le thread du moniteur ; Windows attend notre retour (quelques secondes) puis tue
        le processus. On éteint le panneau et on ferme proprement la connexion (sinon il
        resterait sur l'heure ou le dernier décompte, et garderait une connexion zombie)."""
        self.logger.info("Fin de session Windows : extinction du panneau LED.")
        self.led.shutdown()

    def _really_quit(self) -> None:
        self.running = False
        src, self.source = self.source, None
        if src is not None:
            src.stop()
        self._persist_config_from_ui()
        self.power.stop()
        self.led.shutdown()
        self.tray.stop()
        self.dev_window.destroy()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()
