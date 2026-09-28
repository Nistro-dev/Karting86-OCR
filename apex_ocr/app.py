"""Orchestrateur applicatif : relie config, capture, OCR, session, santé et UI.

Toute mutation d'état (session, santé, widgets) passe par le thread principal
Tk via ``window.after(0, ...)`` — la boucle OCR tourne dans un thread séparé
et ne fait que lire des images / appeler Tesseract.

Deux fenêtres : ``window`` (minimaliste, toujours visible/réduite dans la
zone de notification) et ``dev_window`` (configuration/calibration/journal/
test OCR/panneau LED, masquée par défaut, ouverte via Ctrl+Maj+D).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import TclError, filedialog, messagebox
from typing import Optional

from PIL import Image

from apex_ocr import capture
from apex_ocr.config import AppConfig
from apex_ocr.health import HealthMonitor, HealthStatus
from apex_ocr.led import wifi
from apex_ocr.led.content import panel_content
from apex_ocr.led.panel import LedPanel, LedStatus
from apex_ocr.led.protocol import DEFAULT_HOST, WIFI_SSID_PREFIX
from apex_ocr.led.rendering import COLOR_NAMES, color_index
from apex_ocr.logging_setup import set_log_level, setup_logging
from apex_ocr.ocr import engine
from apex_ocr.ocr.calibration import calibrate_threshold
from apex_ocr.ocr.parsing import parse_lenient, parse_strict
from apex_ocr.ocr.preprocess import preprocess
from apex_ocr.paths import CONFIG_PATH, LOG_DIR, OUTPUT_PATH, test_page_path
from apex_ocr.power import PowerMonitor
from apex_ocr.session import DisplayValue, SessionEvent, SessionState, SessionTracker, StopReason, current_display
from apex_ocr.ui import branding
from apex_ocr.ui.dev_window import DevWindow, DevWindowCallbacks
from apex_ocr.ui.main_window import MainWindow, MainWindowCallbacks
from apex_ocr.ui.tray import TrayIcon
from apex_ocr.ui.zone_selector import ZoneSelector

UI_REFRESH_MS = 200
LED_WIFI_RETRY_S = 12   # panneau injoignable : nouvel essai Wi-Fi + panneau à cette cadence
CALIBRATION_SAMPLES = 5
CALIBRATION_SAMPLE_INTERVAL_S = 0.25
PREVIEW_MIN_INTERVAL_S = 0.5      # aperçu de la zone dans la fenêtre dev : 2x/s max, et seulement si visible
ERROR_LOG_REPEAT_S = 60.0         # une même erreur récurrente n'est journalisée qu'une fois par minute

_REASON_LABELS = {
    StopReason.TIME_ZERO: "temps écoulé",
    StopReason.OCR_LOST: "signal perdu",
    StopReason.CANCELLED: "course annulée",
}

TESSERACT_MISSING_MSG = ("Tesseract OCR introuvable — relancer l'installateur, ou l'installer depuis "
                         "le site UB-Mannheim (dossier par défaut C:\\Program Files\\Tesseract-OCR).")


class App:
    def __init__(self) -> None:
        self.config = AppConfig.load()
        self.logger = setup_logging(self.config.log_retention_days, self.config.log_level)
        engine.set_tesseract_path(self.config.tesseract_path)

        self.tracker = SessionTracker(
            resync_tolerance_seconds=self.config.resync_tolerance_seconds,
            ocr_lost_timeout_seconds=self.config.ocr_lost_timeout_seconds,
            logger=self.logger,
        )
        self.health = HealthMonitor()
        self._last_health_status: Optional[HealthStatus] = None
        self._last_output_text = ""
        self._error_count = 0
        self._last_error_wall: Optional[float] = None

        self.running = False
        self._ocr_thread: Optional[threading.Thread] = None
        self._last_preview_wall = 0.0
        self._last_ocr_raw: Optional[str] = None
        self._last_capture_reason = ""      # dernière raison d'échec de capture (capture.REASON_*), "" si OK
        self._logged_errors: dict[str, float] = {}
        self._output_error_logged = False
        self._calibration_cancel = threading.Event()
        self._calibrating = False
        self._testing_ocr = False
        self._last_ocr_error = ""          # dernière erreur Tesseract/OCR (texte), "" si tout va bien
        self._health_detail = ""

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
            on_refresh_windows=self._refresh_window_titles,
            on_browse_tesseract=self._browse_tesseract,
            on_select_zone=self._select_zone,
            on_test_ocr=self._test_ocr,
            on_start=self.start,
            on_stop=self.stop,
            on_open_test_page=self._open_test_page,
            on_config_changed=self._persist_config_from_ui,
            on_auto_calibrate=self._auto_calibrate_threshold,
            on_cancel_calibrate=self.cancel_calibration,
            on_clear_errors=self._clear_errors,
            on_open_logs=self._open_logs_folder,
            on_open_config=self._open_config_file,
            on_led_scan=self._led_scan,
            on_led_toggle=self._led_toggle,
            on_led_color=self._led_set_color,
            on_led_brightness=self._led_set_brightness,
            on_led_alert_color=self._led_set_alert_color,
            on_led_alert_seconds=self._led_set_alert_seconds,
            on_led_alert_laps=self._led_set_alert_laps,
            on_led_laps_only=self._led_set_laps_only,
            on_led_show_laps=self._led_set_show_laps,
            on_led_idle_clock=self._led_set_idle_clock,
            on_led_wifi_autoconnect=self._led_set_wifi_autoconnect,
            on_led_chunk_minutes=self._led_set_chunk_minutes,
            on_led_password=self._led_set_password,
            on_log_level=self._set_log_level,
        )
        self.dev_window = DevWindow(self.window, self.config, dev_callbacks)
        self.dev_window.set_zone(self.config.zone)
        self.dev_window.set_led_control(self._led_wanted, self.led.status)
        self._check_tesseract()

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
        )
        self.power.start()

        self.dev_window.log("Application prête.")
        self.window.after(UI_REFRESH_MS, self._refresh_tick)

        # Prod : une fois configurée, l'appli se réduit direct dans la zone
        # de notification au lancement, sans action manuelle. Tant qu'elle
        # n'est pas configurée, la fenêtre reste visible pour la calibration.
        if "--minimized" in sys.argv or self.config.is_ready:
            self.window.withdraw()

        if self.config.is_ready:
            self.start()

        # Indépendant de la config OCR : le panneau se (re)connecte tout seul
        # au lancement (Wi-Fi compris), puis retente en arrière-plan s'il est
        # éteint/hors de portée (voir _led_watchdog).
        if self._led_wanted:
            self.logger.info("Connexion automatique au panneau LED %s...", self.config.led_host)
            self._led_connect(self.config.led_host)

    # ---- fenêtre dev -----------------------------------------------------

    def _toggle_dev_window(self) -> None:
        self.dev_window.toggle()

    def _refresh_window_titles(self) -> None:
        """Liste des fenêtres ouvertes : l'énumération prend jusqu'à quelques centaines
        de ms -> en tâche de fond, résultat déposé dans la fenêtre dev."""
        def work():
            titles = capture.list_window_titles()
            try:
                self.window.after(0, self._guarded, self.dev_window.set_window_titles, titles)
            except (RuntimeError, TclError):
                pass
        threading.Thread(target=work, daemon=True, name="window-titles").start()

    def _open_logs_folder(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        os.startfile(LOG_DIR)

    def _open_config_file(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            self.config.save()
        os.startfile(CONFIG_PATH)

    # ---- Tesseract ------------------------------------------------------

    def _tesseract_ok(self) -> bool:
        path = self.config.tesseract_path
        return bool(path) and os.path.exists(path)

    def _check_tesseract(self) -> None:
        """Sans tesseract.exe l'appli ne lira jamais rien : bandeau explicite dans la
        fenêtre principale (avec le lien de téléchargement) plutôt qu'une erreur muette."""
        if self._tesseract_ok():
            self.window.hide_banner()
            return
        self.window.show_banner(TESSERACT_MISSING_MSG, branding.TESSERACT_DOWNLOAD_URL)
        self.logger.warning("tesseract.exe introuvable (%r) : l'OCR ne peut pas fonctionner.",
                            self.config.tesseract_path)
        self.dev_window.log(TESSERACT_MISSING_MSG)

    # ---- actions déclenchées par l'UI --------------------------------

    def _browse_tesseract(self) -> Optional[str]:
        path = filedialog.askopenfilename(
            title="Sélectionner tesseract.exe", filetypes=[("Executable", "*.exe"), ("Tous", "*.*")]
        )
        return path or None

    def _persist_config_from_ui(self) -> None:
        for key, value in self.dev_window.current_config_values(self.config).items():
            setattr(self.config, key, value)
        engine.set_tesseract_path(self.config.tesseract_path)
        self.tracker.resync_tolerance_seconds = self.config.resync_tolerance_seconds
        self.tracker.ocr_lost_timeout_seconds = self.config.ocr_lost_timeout_seconds
        self.config.save()
        self._check_tesseract()

    def _select_zone(self) -> None:
        title = self.dev_window.window_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une fenêtre.")
            return
        img = capture.capture_window(title)
        if img is None:
            messagebox.showerror("Erreur", f"Capture impossible pour « {title} ».")
            return
        self.config.window_title = title
        selector = ZoneSelector(self.dev_window, img, self.config.zone)
        self.dev_window.wait_window(selector)
        if selector.result:
            self.config.zone = selector.result
            self.config.zone_ref_size = list(img.size)  # pour remettre la zone à l'échelle si la fenêtre change de taille/DPI
            self.dev_window.set_zone(self.config.zone)
            self.config.save()
            self.dev_window.log(f"Zone définie : {self.dev_window.format_zone(self.config.zone)}")

    def _test_ocr(self) -> None:
        """Capture + Tesseract (150-400 ms) en tâche de fond : la fenêtre ne gèle pas."""
        if self._testing_ocr:
            return
        self._persist_config_from_ui()
        self._testing_ocr = True
        self.dev_window.set_testing_ocr(True)

        def work():
            img, reason = self._capture_zone_ex()
            text, processed, error = "", None, ""
            if img is not None:
                try:
                    processed = preprocess(img, self.config.threshold)
                    text = engine.extract_text(processed)
                except Exception as exc:
                    error = str(exc) or type(exc).__name__
            try:
                self.window.after(0, self._guarded, self._on_test_ocr_done, img, processed, text, reason, error)
            except (RuntimeError, TclError):
                pass
        threading.Thread(target=work, daemon=True, name="test-ocr").start()

    def _on_test_ocr_done(self, img, processed, text: str, reason: str, error: str) -> None:
        self._testing_ocr = False
        self.dev_window.set_testing_ocr(False)
        if img is None:
            self.dev_window.log(f"Test OCR : capture impossible — {capture.CAPTURE_REASON_LABELS.get(reason, reason)}.")
            return
        self.dev_window.set_preview_image(img, processed)
        if error:
            self.dev_window.log(f"Test OCR : erreur Tesseract — {error}")
            return
        self.dev_window.set_last_ocr_text(text.strip())
        reading = parse_strict(text)
        if reading is None:
            self.dev_window.log(
                f"Test OCR : « {text.strip()} » (format non reconnu)" if text.strip() else "Test OCR : aucun texte lu."
            )
            return
        laps = f" ({reading.laps_done}/{reading.laps_total})" if reading.has_laps else ""
        self.dev_window.log(f"Test OCR : « {text.strip()} » -> {reading.time_text}{laps} ✓")

    def _auto_calibrate_threshold(self) -> None:
        if not self.config.window_title or not self.config.zone:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre et définissez la zone d'abord.")
            return
        if self._calibrating:
            self.dev_window.log("Calibration déjà en cours.")
            return
        self._calibrating = True
        self._calibration_cancel.clear()
        self.dev_window.set_calibrating(True)
        self.dev_window.log(f"Calibration automatique du seuil en cours ({CALIBRATION_SAMPLES} échantillons)...")
        threading.Thread(target=self._run_calibration, daemon=True).start()

    def cancel_calibration(self) -> None:
        """Interrompt la calibration en cours (sans effet s'il n'y en a pas)."""
        self._calibration_cancel.set()

    def _run_calibration(self) -> None:
        samples: list[Image.Image] = []
        for _ in range(CALIBRATION_SAMPLES):
            img = self._capture_zone()
            if img is not None:
                samples.append(img)
            time.sleep(CALIBRATION_SAMPLE_INTERVAL_S)
        last_pct = [0]

        def on_progress(done: int, total: int) -> None:
            pct = done * 100 // total
            if pct // 20 > last_pct[0] // 20:   # un message tous les 20 %
                last_pct[0] = pct
                self.window.after(0, self.dev_window.log, f"Calibration : {pct} %")

        try:
            best = calibrate_threshold(samples, on_progress=on_progress, cancel=self._calibration_cancel)
        except Exception as exc:
            self.logger.exception("Calibration : erreur")
            best = None
            self.window.after(0, self.dev_window.log, f"Calibration : erreur ({exc}).")
        self.window.after(0, self._on_calibration_done, best)

    def _on_calibration_done(self, best: Optional[int]) -> None:
        self._calibrating = False
        self.dev_window.set_calibrating(False)
        if self._calibration_cancel.is_set():
            self.dev_window.log("Calibration annulée.")
            return
        if best is None:
            self.dev_window.log("Calibration échouée : aucun seuil ne donne une lecture valide et stable. Vérifiez la zone.")
            return
        self.config.threshold = best
        self.dev_window.set_threshold(best)
        self.config.save()
        self.dev_window.log(f"Seuil calibré automatiquement : {best}")

    def start(self) -> None:
        if self.running:
            return
        if not self.config.window_title or not self.config.zone:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre et définissez la zone.")
            return
        self._persist_config_from_ui()
        # Un précédent thread OCR peut encore finir son sleep après un stop() : on
        # l'attend plutôt que de faire tourner deux boucles en parallèle.
        if self._ocr_thread is not None and self._ocr_thread.is_alive():
            self._ocr_thread.join(timeout=max(0.05, self.config.ocr_interval_ms / 1000) + 1.0)
        self.running = True
        self.tracker.reset()
        self.dev_window.set_running(True)
        self.dev_window.log("OCR démarré.")
        self._ocr_thread = threading.Thread(target=self._ocr_loop, daemon=True, name="ocr")
        self._ocr_thread.start()

    def stop(self) -> None:
        self.running = False
        self.dev_window.set_running(False)
        self.dev_window.log("OCR arrêté.")

    # ---- boucle OCR (thread d'arrière-plan) ---------------------------

    def _capture_zone(self) -> Optional[Image.Image]:
        return self._capture_zone_ex()[0]

    def _capture_zone_ex(self) -> tuple[Optional[Image.Image], str]:
        """(image de la zone, raison d'échec capture.REASON_* ou "")."""
        if not self.config.window_title or not self.config.zone:
            return None, capture.REASON_WINDOW_NOT_FOUND
        return capture.capture_zone_ex(self.config.window_title, tuple(self.config.zone), self.config.zone_ref_size)

    def _read_raw_text(self, img: Image.Image) -> str:
        processed = preprocess(img, self.config.threshold)
        return engine.extract_text(processed)

    def _ocr_loop(self) -> None:
        while self.running:
            try:
                img, reason = self._capture_zone_ex()
                if img is None:
                    self.window.after(0, self._guarded, self._on_capture_failure, reason)
                else:
                    text = self._read_raw_text(img)
                    self.window.after(0, self._guarded, self._on_capture_success, img, text)
            except Exception as exc:
                try:
                    self.window.after(0, self._guarded, self._on_capture_error, exc)
                except (RuntimeError, TclError):  # appli en cours de fermeture
                    break
            time.sleep(max(0.05, self.config.ocr_interval_ms / 1000))

    # ---- garde-fous : une exception ne tue ni la boucle Tk ni la boucle OCR ----

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

    def _on_capture_failure(self, reason: str = "") -> None:
        self.health.record_capture_failure()
        self._set_capture_reason(reason)

    def _on_capture_error(self, exc: Exception) -> None:
        self.health.record_capture_failure()
        self._last_ocr_error = str(exc).strip().splitlines()[0][:120] if str(exc).strip() else type(exc).__name__
        self._log_error_once("ocr", exc)

    def _set_capture_reason(self, reason: str) -> None:
        """Raison d'échec de la capture (exposée à l'UI via _last_capture_reason) ;
        journalisée à chaque changement, pas à chaque frame."""
        if reason == self._last_capture_reason:
            return
        self._last_capture_reason = reason
        if reason:
            self.logger.warning("Capture impossible : %s", capture.CAPTURE_REASON_LABELS.get(reason, reason))
        else:
            self.logger.info("Capture rétablie.")

    def _on_capture_success(self, img: Image.Image, text: str) -> None:
        self.health.record_capture_success()
        self._set_capture_reason("")
        self._last_ocr_error = ""
        now = time.monotonic()
        raw = text.strip()
        changed = raw != self._last_ocr_raw   # le texte brut n'est journalisé qu'à son changement
        self._last_ocr_raw = raw
        # L'aperçu (redimensionnement + PhotoImage) ne vaut que fenêtre dev visible, 2x/s max ;
        # l'image prétraitée (celle vue par Tesseract) n'est recalculée que pour lui.
        if self.dev_window.winfo_viewable():
            if now - self._last_preview_wall >= PREVIEW_MIN_INTERVAL_S:
                self._last_preview_wall = now
                self.dev_window.set_preview_image(img, preprocess(img, self.config.threshold))
            if changed:
                self.dev_window.set_last_ocr_text(raw)
        if self.tracker.state == SessionState.RUNNING:
            reading = parse_lenient(text)
            if changed:
                self.logger.debug("OCR brut=%r → temps=%s tours=%s/%s",
                                  raw, reading.time_text, reading.laps_done, reading.laps_total)
            events = self.tracker.on_lenient_reading(reading, now)
        else:
            strict = parse_strict(text)
            if strict is not None and changed:
                self.logger.debug("OCR brut=%r → strict temps=%s tours=%s/%s",
                                  raw, strict.time_text, strict.laps_done, strict.laps_total)
            events = self.tracker.on_strict_reading(strict, now)

        self._handle_events(events)

    def _handle_events(self, events: list[SessionEvent]) -> None:
        for event in events:
            if event == SessionEvent.ARMED:
                self.dev_window.log("Chiffre détecté — en attente de confirmation (doit diminuer).")
            elif event == SessionEvent.STARTED:
                self.dev_window.log("Départ détecté — minuterie démarrée.")
            elif event == SessionEvent.RESYNCED:
                self.dev_window.log("Resynchronisation sur lecture OCR (écart détecté).")
            elif event == SessionEvent.STOPPED:
                result = self.tracker.last_completed
                label = _REASON_LABELS[result.reason]
                self.dev_window.log(f"Session terminée ({label}) : {result.time_text}")
                self.logger.info("Session terminée (%s) : %s", result.reason.name, result.time_text)

    # ---- rafraîchissement UI (indépendant de la boucle OCR) ------------

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
        if self.tracker.state == SessionState.RUNNING:
            self._handle_events(self.tracker.tick(now))

        display = current_display(self.tracker, now)
        self.window.set_display(display)
        self._sync_output(display)
        self.led.show(panel_content(
            self.tracker.state, display,
            laps_only=self.config.led_laps_only,
            alert_seconds=self.config.led_alert_seconds,
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
        self.dev_window.log("Mot de passe du panneau LED enregistré (reconnexion si nécessaire).")

    def _set_log_level(self, level: str) -> None:
        self.config.log_level = level
        self.config.save()
        set_log_level(level)
        self.dev_window.log(f"Niveau de log : {level}")

    def _health_detail_text(self, status: HealthStatus) -> str:
        """Ce qui ne va pas, en clair (fenêtre principale, fenêtre dev, infobulle systray)."""
        if not self._tesseract_ok():
            return "tesseract.exe introuvable : l'OCR ne peut pas fonctionner."
        if status != HealthStatus.ERROR:
            return ""
        if self._last_capture_reason == capture.REASON_WINDOW_NOT_FOUND:
            title = self.config.window_title or "(aucune)"
            return f"Fenêtre « {title} » introuvable : Apex Timing fermé ou titre différent ?"
        if self._last_capture_reason:
            label = capture.CAPTURE_REASON_LABELS.get(self._last_capture_reason, self._last_capture_reason)
            return label[0].upper() + label[1:] + "."
        if self._last_ocr_error:
            return f"Tesseract : {self._last_ocr_error}"
        return "Capture ou lecture en échec depuis trop longtemps (voir le journal)."

    def _apply_health_status(self, status: HealthStatus) -> None:
        # Pas de notification Windows ici (trop intrusif : se déclenchait à
        # chaque changement de fenêtre) -> l'icône colorée dans la zone de
        # notification suffit, l'historique reste dans le log.
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

    # ---- page de test ----------------------------------------------------

    def _open_test_page(self) -> None:
        """Ouvre test_timer.html (livrée avec l'appli) dans le navigateur par défaut."""
        path = test_page_path()
        if not path or not os.path.exists(path):
            self.dev_window.log("Page de test introuvable (test_timer.html).")
            return
        webbrowser.open(Path(path).as_uri())
        self.dev_window.log(f"Page de test ouverte dans le navigateur : {path}")

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

    def _really_quit(self) -> None:
        self.running = False
        self._persist_config_from_ui()
        self.power.stop()
        self.led.shutdown()
        self.tray.stop()
        self.dev_window.destroy()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()
