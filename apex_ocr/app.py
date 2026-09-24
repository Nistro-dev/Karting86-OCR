"""Orchestrateur applicatif : relie config, capture, OCR, session, santé et UI.

Toute mutation d'état (session, santé, widgets) passe par le thread principal
Tk via ``window.after(0, ...)`` — la boucle OCR tourne dans un thread séparé
et ne fait que lire des images / appeler Tesseract.

Deux fenêtres : ``window`` (minimaliste, toujours visible/réduite dans la
zone de notification) et ``dev_window`` (configuration/calibration/journal/
test OCR/affichage externe, masquée par défaut, ouverte via Ctrl+Maj+D).
"""
from __future__ import annotations

import sys
import threading
import time
from tkinter import filedialog, messagebox
from typing import Optional

from PIL import Image

from apex_ocr import capture
from apex_ocr.config import AppConfig
from apex_ocr.health import HealthMonitor, HealthStatus
from apex_ocr.led.content import panel_content
from apex_ocr.led.panel import LedPanel, LedStatus
from apex_ocr.logging_setup import setup_logging
from apex_ocr.ocr import engine
from apex_ocr.ocr.calibration import calibrate_threshold
from apex_ocr.ocr.parsing import parse_lenient, parse_strict
from apex_ocr.ocr.preprocess import preprocess
from apex_ocr.paths import OUTPUT_PATH
from apex_ocr.session import DisplayValue, SessionEvent, SessionState, SessionTracker, StopReason, current_display
from apex_ocr.ui.dev_window import DevWindow, DevWindowCallbacks
from apex_ocr.ui.external_display import ExternalDisplay
from apex_ocr.ui.main_window import MainWindow, MainWindowCallbacks
from apex_ocr.ui.screen_picker import MonitorInfo, ScreenPicker, list_monitors
from apex_ocr.ui.tray import TrayIcon
from apex_ocr.ui.zone_selector import ZoneSelector

UI_REFRESH_MS = 200
CALIBRATION_SAMPLES = 5
CALIBRATION_SAMPLE_INTERVAL_S = 0.25
AUTO_EXTERNAL_RETRY_INTERVAL_MS = 2000
AUTO_EXTERNAL_MAX_ATTEMPTS = 150  # ~5min au total avant d'abandonner

_REASON_LABELS = {
    StopReason.TIME_ZERO: "temps écoulé",
    StopReason.OCR_LOST: "signal perdu",
    StopReason.CANCELLED: "course annulée",
}


class App:
    def __init__(self) -> None:
        self.config = AppConfig.load()
        self.logger = setup_logging(self.config.log_retention_days)
        engine.set_tesseract_path(self.config.tesseract_path)

        self.tracker = SessionTracker(
            resync_tolerance_seconds=self.config.resync_tolerance_seconds,
            ocr_lost_timeout_seconds=self.config.ocr_lost_timeout_seconds,
        )
        self.health = HealthMonitor()
        self._last_health_status: Optional[HealthStatus] = None
        self._last_output_text = ""
        self._error_count = 0
        self._last_error_wall: Optional[float] = None

        self.running = False
        self.external_display: Optional[ExternalDisplay] = None

        self.led = LedPanel(
            self.config.led_width,
            self.config.led_height,
            tuple(self.config.led_color),
            self.logger,
        )
        self._last_led_status: Optional[tuple[LedStatus, str]] = None

        self.window = MainWindow(
            self.config,
            MainWindowCallbacks(on_toggle_dev=self._toggle_dev_window, on_close=self._on_close),
        )

        dev_callbacks = DevWindowCallbacks(
            on_refresh_windows=capture.list_window_titles,
            on_browse_tesseract=self._browse_tesseract,
            on_select_zone=self._select_zone,
            on_test_ocr=self._test_ocr,
            on_start=self.start,
            on_stop=self.stop,
            on_open_external=self._open_external,
            on_external_enabled=self._set_external_enabled,
            on_config_changed=self._persist_config_from_ui,
            on_auto_calibrate=self._auto_calibrate_threshold,
            on_clear_errors=self._clear_errors,
            on_led_scan=self._led_scan,
            on_led_toggle=self._led_toggle,
            on_led_color=self._led_set_color,
            on_led_laps_only=self._led_set_laps_only,
        )
        self.dev_window = DevWindow(self.window, self.config, dev_callbacks)
        self.dev_window.set_zone(self.config.zone)
        self.dev_window.set_led_enabled(self.config.led_enabled)

        self.tray = TrayIcon(
            on_show=lambda: self.window.after(0, self._show_window),
            on_quit=lambda: self.window.after(0, self._really_quit),
        )
        self.tray.start()

        self.dev_window.log("Application prête.")
        self.window.after(UI_REFRESH_MS, self._refresh_tick)

        # Prod : une fois configurée, l'appli se réduit direct dans la zone
        # de notification au lancement, sans action manuelle. Tant qu'elle
        # n'est pas configurée, la fenêtre reste visible pour la calibration.
        if "--minimized" in sys.argv or self.config.is_ready:
            self.window.withdraw()

        if self.config.is_ready:
            self.start()
            self._auto_open_external()

        # Indépendant de la config OCR : le panneau se (re)connecte tout seul
        # au lancement, puis retente en arrière-plan s'il est éteint/hors de portée.
        if self.config.led_enabled and self.config.led_address:
            self.logger.info("Connexion automatique au panneau LED %s...", self.config.led_address)
            self.led.connect(self.config.led_address)

    # ---- fenêtre dev -----------------------------------------------------

    def _toggle_dev_window(self) -> None:
        self.dev_window.toggle()

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
            self.dev_window.set_zone(self.config.zone)
            self.config.save()
            self.dev_window.log(f"Zone définie : {self.dev_window.format_zone(self.config.zone)}")

    def _test_ocr(self) -> None:
        img = self._capture_zone()
        if img is None:
            self.dev_window.log("Capture impossible. Vérifiez fenêtre et zone.")
            return
        text = self._read_raw_text(img)
        self.dev_window.set_preview_image(img)
        reading = parse_strict(text)
        if reading is None:
            self.dev_window.log(
                f"Test OCR : « {text} » (format non reconnu)" if text else "Test OCR : aucun texte lu."
            )
            return
        laps = f" ({reading.laps_done}/{reading.laps_total})" if reading.has_laps else ""
        self.dev_window.log(f"Test OCR : « {text} » -> {reading.time_text}{laps} ✓")

    def _auto_calibrate_threshold(self) -> None:
        if not self.config.window_title or not self.config.zone:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre et définissez la zone d'abord.")
            return
        self.dev_window.log(f"Calibration automatique du seuil en cours ({CALIBRATION_SAMPLES} échantillons)...")
        threading.Thread(target=self._run_calibration, daemon=True).start()

    def _run_calibration(self) -> None:
        samples: list[Image.Image] = []
        for _ in range(CALIBRATION_SAMPLES):
            img = self._capture_zone()
            if img is not None:
                samples.append(img)
            time.sleep(CALIBRATION_SAMPLE_INTERVAL_S)
        best = calibrate_threshold(samples)
        self.window.after(0, self._on_calibration_done, best)

    def _on_calibration_done(self, best: Optional[int]) -> None:
        if best is None:
            self.dev_window.log("Calibration échouée : aucun seuil ne donne une lecture valide. Vérifiez la zone.")
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
        self.running = True
        self.tracker.reset()
        self.dev_window.set_running(True)
        self.dev_window.log("OCR démarré.")
        threading.Thread(target=self._ocr_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        self.dev_window.set_running(False)
        self.dev_window.log("OCR arrêté.")

    # ---- boucle OCR (thread d'arrière-plan) ---------------------------

    def _capture_zone(self) -> Optional[Image.Image]:
        if not self.config.window_title or not self.config.zone:
            return None
        return capture.capture_zone(self.config.window_title, tuple(self.config.zone))

    def _read_raw_text(self, img: Image.Image) -> str:
        processed = preprocess(img, self.config.threshold)
        return engine.extract_text(processed)

    def _ocr_loop(self) -> None:
        while self.running:
            try:
                img = self._capture_zone()
                if img is None:
                    self.window.after(0, self._on_capture_failure)
                else:
                    text = self._read_raw_text(img)
                    self.window.after(0, self._on_capture_success, img, text)
            except Exception as exc:
                self.window.after(0, self._on_capture_error, exc)
            time.sleep(max(0.05, self.config.ocr_interval_ms / 1000))

    def _on_capture_failure(self) -> None:
        self.health.record_capture_failure()

    def _on_capture_error(self, exc: Exception) -> None:
        self.health.record_capture_failure()
        self.logger.warning("Erreur OCR : %s", exc)

    def _on_capture_success(self, img: Image.Image, text: str) -> None:
        self.health.record_capture_success()
        self.dev_window.set_preview_image(img)
        now = time.monotonic()

        if self.tracker.state == SessionState.RUNNING:
            reading = parse_lenient(text)
            events = self.tracker.on_lenient_reading(reading, now)
        else:
            events = self.tracker.on_strict_reading(parse_strict(text), now)

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
        now = time.monotonic()
        if self.tracker.state == SessionState.RUNNING:
            self._handle_events(self.tracker.tick(now))

        display = current_display(self.tracker, now)
        self.window.set_display(display)
        self._sync_output(display)
        self.led.show(panel_content(self.tracker.state, display, laps_only=self.config.led_laps_only))
        self._refresh_led_status()

        status = self.health.status_for(self.tracker.state)
        self._apply_health_status(status)

        if self.external_display is not None:
            if self.external_display.winfo_exists():
                self.external_display.set_display(display)
                self.external_display.set_health(status)
            else:
                self.external_display = None
                self.dev_window.set_external_open(False)

        self.window.after(UI_REFRESH_MS, self._refresh_tick)

    def _sync_output(self, display: DisplayValue) -> None:
        if display.time_text == self._last_output_text:
            return
        self._last_output_text = display.time_text
        try:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(display.time_text)
        except IOError:
            pass
        if display.is_live:
            laps = f" ({display.laps_done}/{display.laps_total})" if display.laps_total is not None else ""
            self.logger.info("Timer %s%s", display.time_text, laps)

    # ---- panneau LED ----------------------------------------------------

    def _refresh_led_status(self) -> None:
        current = (self.led.status, self.led.status_detail)
        if current != self._last_led_status:
            self._last_led_status = current
            self.dev_window.set_led_status(*current)

    def _led_scan(self) -> None:
        self.dev_window.set_led_scanning(True)
        self.dev_window.log("Scan des panneaux LED à proximité...")
        self.led.scan().add_done_callback(lambda fut: self.window.after(0, self._on_led_scan_done, fut))

    def _on_led_scan_done(self, fut) -> None:
        self.dev_window.set_led_scanning(False)
        try:
            devices = fut.result()
        except Exception as exc:
            self.dev_window.log(f"Scan LED impossible : {exc}")
            return
        self.config.led_known_devices = [list(d) for d in devices]
        self.config.save()
        self.dev_window.set_led_devices(devices, select_first=True)
        self.dev_window.log(f"{len(devices)} panneau(x) LED trouvé(s).")

    def _led_toggle(self) -> None:
        if self.config.led_enabled:
            self.config.led_enabled = False
            self.config.save()
            self.led.disconnect()
            self.dev_window.set_led_enabled(False)
            self.dev_window.log("Panneau LED déconnecté.")
            return
        address = self.dev_window.led_address_input()
        if not address:
            messagebox.showwarning("Attention", "Scannez ou saisissez l'adresse du panneau LED.")
            return
        self.config.led_address = address
        self.config.led_enabled = True
        self.config.save()
        self.led.connect(address)
        self.dev_window.set_led_enabled(True)
        self.dev_window.log(f"Connexion au panneau LED {address}...")

    def _led_set_color(self, rgb: tuple) -> None:
        self.config.led_color = list(rgb)
        self.config.save()
        self.led.set_color(rgb)
        self.dev_window.log("Couleur du panneau LED : #%02x%02x%02x" % tuple(rgb))

    def _led_set_laps_only(self, enabled: bool) -> None:
        self.config.led_laps_only = enabled
        self.config.save()
        self.dev_window.log("Panneau LED : " + ("tours seuls" if enabled else "chrono + tours"))

    def _apply_health_status(self, status: HealthStatus) -> None:
        # Pas de notification Windows ici (trop intrusif : se déclenchait à
        # chaque changement de fenêtre) -> l'icône colorée dans la zone de
        # notification suffit, l'historique reste dans le log.
        self.window.set_health(status)
        self.dev_window.set_health(status)
        self.tray.set_status(status)
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

    # ---- affichage externe ---------------------------------------------

    def _open_external(self) -> None:
        # Repli fiable pour fermer l'affichage externe : la fenêtre dev
        # a toujours le focus normalement, contrairement à l'écran plein écran.
        if self.external_display is not None and self.external_display.winfo_exists():
            self.external_display.destroy()
            self.external_display = None
            self.dev_window.set_external_open(False)
            self.dev_window.log("Affichage externe fermé.")
            return
        ScreenPicker(self.dev_window, on_selected=self._open_external_on)

    def _set_external_enabled(self, enabled: bool) -> None:
        self.config.external_enabled = enabled
        self.config.save()
        self.dev_window.set_external_enabled(enabled)
        if enabled:
            self.dev_window.log("Affichage externe activé.")
            self._auto_open_external()
            return
        if self.external_display is not None and self.external_display.winfo_exists():
            self.external_display.destroy()
        self.external_display = None
        self.dev_window.set_external_open(False)
        self.dev_window.log("Affichage externe désactivé (ne s'ouvrira plus au démarrage).")

    def _open_external_on(self, monitor: MonitorInfo) -> None:
        if self.external_display is not None and self.external_display.winfo_exists():
            self.external_display.destroy()
        self.external_display = ExternalDisplay(self.window, monitor)
        self.dev_window.set_external_open(True)
        self.dev_window.log(f"Affichage externe ouvert sur {monitor.label}.")
        self.config.external_monitor_index = monitor.index
        self.config.save()

    def _auto_open_external(self) -> None:
        """Rouvre l'affichage externe sur l'écran mémorisé au démarrage,
        sans action manuelle (config déjà prête = usage prod).

        Réessaie plusieurs fois : au boot, un écran externe (souvent un
        contrôleur/convertisseur piste) peut mettre plusieurs secondes à
        être détecté par Windows, donc absent de ``list_monitors()`` au
        tout premier essai ne veut pas dire indisponible."""
        if not self.config.external_enabled:
            self.logger.info("Affichage externe désactivé : pas d'ouverture automatique.")
            return
        if self.config.external_monitor_index is None:
            return
        self.logger.info(
            "Recherche de l'écran externe #%d au démarrage...", self.config.external_monitor_index
        )
        self._try_auto_open_external(attempt=1)

    def _try_auto_open_external(self, attempt: int) -> None:
        # désactivé entre-temps (ou déjà ouvert à la main) : on arrête les essais
        if not self.config.external_enabled or self.external_display is not None:
            return
        match = next(
            (m for m in list_monitors() if m.index == self.config.external_monitor_index), None
        )
        if match is not None:
            self._open_external_on(match)
            self.logger.info(
                "Affichage externe ouvert automatiquement sur %s (tentative %d/%d).",
                match.label, attempt, AUTO_EXTERNAL_MAX_ATTEMPTS,
            )
            return

        if attempt >= AUTO_EXTERNAL_MAX_ATTEMPTS:
            self.logger.warning(
                "Écran externe #%d introuvable après %d tentatives (~%.0fs). "
                "Ouverture manuelle nécessaire (Ctrl+Maj+D -> Affichage externe).",
                self.config.external_monitor_index,
                attempt,
                attempt * AUTO_EXTERNAL_RETRY_INTERVAL_MS / 1000,
            )
            return

        self.logger.info(
            "Écran externe #%d pas encore détecté (tentative %d/%d), nouvel essai dans %.0fs.",
            self.config.external_monitor_index,
            attempt,
            AUTO_EXTERNAL_MAX_ATTEMPTS,
            AUTO_EXTERNAL_RETRY_INTERVAL_MS / 1000,
        )
        self.window.after(AUTO_EXTERNAL_RETRY_INTERVAL_MS, self._try_auto_open_external, attempt + 1)

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

    def _really_quit(self) -> None:
        self.running = False
        self._persist_config_from_ui()
        self.led.shutdown()
        self.tray.stop()
        self.dev_window.destroy()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()
