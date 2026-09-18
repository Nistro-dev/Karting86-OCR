"""Orchestrateur applicatif : relie config, capture, OCR, session, santé et UI.

Toute mutation d'état (session, santé, widgets) passe par le thread principal
Tk via ``window.after(0, ...)`` — la boucle OCR tourne dans un thread séparé
et ne fait que lire des images / appeler Tesseract.
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
from apex_ocr.logging_setup import setup_logging
from apex_ocr.ocr import engine
from apex_ocr.ocr.calibration import calibrate_threshold
from apex_ocr.ocr.parsing import parse_lenient, parse_strict
from apex_ocr.ocr.preprocess import preprocess
from apex_ocr.paths import OUTPUT_PATH
from apex_ocr.session import DisplayValue, SessionEvent, SessionState, SessionTracker, StopReason, current_display
from apex_ocr.ui.external_display import ExternalDisplay
from apex_ocr.ui.main_window import MainWindow, MainWindowCallbacks
from apex_ocr.ui.screen_picker import MonitorInfo, ScreenPicker
from apex_ocr.ui.tray import TrayIcon
from apex_ocr.ui.zone_selector import ZoneSelector

UI_REFRESH_MS = 200
CALIBRATION_SAMPLES = 5
CALIBRATION_SAMPLE_INTERVAL_S = 0.25

_REASON_LABELS = {
    StopReason.TIME_ZERO: "temps écoulé",
    StopReason.LAPS_COMPLETE: "tours terminés",
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

        self.running = False
        self.external_display: Optional[ExternalDisplay] = None

        callbacks = MainWindowCallbacks(
            on_refresh_windows=capture.list_window_titles,
            on_browse_tesseract=self._browse_tesseract,
            on_select_zone=self._select_zone,
            on_test_ocr=self._test_ocr,
            on_start=self.start,
            on_stop=self.stop,
            on_open_external=self._open_external,
            on_config_changed=self._persist_config_from_ui,
            on_auto_calibrate=self._auto_calibrate_threshold,
            on_close=self._on_close,
        )
        self.window = MainWindow(self.config, callbacks)
        self.window.set_zone(self.config.zone)

        self.tray = TrayIcon(
            on_show=lambda: self.window.after(0, self._show_window),
            on_quit=lambda: self.window.after(0, self._really_quit),
        )
        self.tray.start()

        self.window.log("Application prête.")
        self.window.after(UI_REFRESH_MS, self._refresh_tick)

        if "--minimized" in sys.argv:
            self.window.withdraw()

        if self.config.is_ready:
            self.start()

    # ---- actions déclenchées par l'UI --------------------------------

    def _browse_tesseract(self) -> Optional[str]:
        path = filedialog.askopenfilename(
            title="Sélectionner tesseract.exe", filetypes=[("Executable", "*.exe"), ("Tous", "*.*")]
        )
        return path or None

    def _persist_config_from_ui(self) -> None:
        for key, value in self.window.current_config_values(self.config).items():
            setattr(self.config, key, value)
        engine.set_tesseract_path(self.config.tesseract_path)
        self.tracker.resync_tolerance_seconds = self.config.resync_tolerance_seconds
        self.tracker.ocr_lost_timeout_seconds = self.config.ocr_lost_timeout_seconds
        self.config.save()

    def _select_zone(self) -> None:
        title = self.window.window_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une fenêtre.")
            return
        img = capture.capture_window(title)
        if img is None:
            messagebox.showerror("Erreur", f"Capture impossible pour « {title} ».")
            return
        self.config.window_title = title
        selector = ZoneSelector(self.window, img, self.config.zone)
        self.window.wait_window(selector)
        if selector.result:
            self.config.zone = selector.result
            self.window.set_zone(self.config.zone)
            self.config.save()
            self.window.log(f"Zone définie : {self.window.format_zone(self.config.zone)}")

    def _test_ocr(self) -> None:
        img = self._capture_zone()
        if img is None:
            self.window.log("Capture impossible. Vérifiez fenêtre et zone.")
            return
        text = self._read_raw_text(img)
        self.window.set_preview_image(img)
        reading = parse_strict(text)
        if reading is None:
            self.window.log(f"Test OCR : « {text} » (format non reconnu)" if text else "Test OCR : aucun texte lu.")
            return
        laps = f" ({reading.laps_done}/{reading.laps_total})" if reading.has_laps else ""
        self.window.log(f"Test OCR : « {text} » -> {reading.time_text}{laps} ✓")

    def _auto_calibrate_threshold(self) -> None:
        if not self.config.window_title or not self.config.zone:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre et définissez la zone d'abord.")
            return
        self.window.log(f"Calibration automatique du seuil en cours ({CALIBRATION_SAMPLES} échantillons)...")
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
            self.window.log("Calibration échouée : aucun seuil ne donne une lecture valide. Vérifiez la zone.")
            return
        self.config.threshold = best
        self.window.set_threshold(best)
        self.config.save()
        self.window.log(f"Seuil calibré automatiquement : {best}")

    def start(self) -> None:
        if self.running:
            return
        if not self.config.window_title or not self.config.zone:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre et définissez la zone.")
            return
        self._persist_config_from_ui()
        self.running = True
        self.tracker.reset()
        self.window.set_running(True)
        self.window.log("OCR démarré.")
        threading.Thread(target=self._ocr_loop, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        self.window.set_running(False)
        self.window.log("OCR arrêté.")

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
        self.window.set_preview_image(img)
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
                self.window.log("Chiffre détecté — en attente de confirmation (doit diminuer).")
            elif event == SessionEvent.STARTED:
                self.window.log("Départ détecté — minuterie démarrée.")
            elif event == SessionEvent.RESYNCED:
                self.window.log("Resynchronisation sur lecture OCR (écart détecté).")
            elif event == SessionEvent.STOPPED:
                result = self.tracker.last_completed
                label = _REASON_LABELS[result.reason]
                self.window.log(f"Session terminée ({label}) : {result.time_text}")
                self.logger.info("Session terminée (%s) : %s", result.reason.name, result.time_text)

    # ---- rafraîchissement UI (indépendant de la boucle OCR) ------------

    def _refresh_tick(self) -> None:
        now = time.monotonic()
        if self.tracker.state == SessionState.RUNNING:
            self._handle_events(self.tracker.tick(now))

        display = current_display(self.tracker, now)
        self.window.set_display(display)
        self._sync_output(display)

        status = self.health.status_for(self.tracker.state)
        self._apply_health_status(status)

        if self.external_display is not None:
            if self.external_display.winfo_exists():
                self.external_display.set_display(display)
                self.external_display.set_health(status)
            else:
                self.external_display = None
                self.window.set_external_open(False)

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

    def _apply_health_status(self, status: HealthStatus) -> None:
        # Pas de notification Windows ici (trop intrusif : se déclenchait à
        # chaque changement de fenêtre) -> l'icône colorée dans la zone de
        # notification suffit, l'historique reste dans le log.
        self.window.set_health(status)
        self.tray.set_status(status)
        if status != self._last_health_status:
            if status == HealthStatus.ERROR:
                self.logger.warning("Passage en état ERROR")
            elif self._last_health_status == HealthStatus.ERROR:
                self.logger.info("Sortie de l'état ERROR")
        self._last_health_status = status

    # ---- affichage externe ---------------------------------------------

    def _open_external(self) -> None:
        # Repli fiable pour fermer l'affichage externe : la fenêtre principale
        # a toujours le focus normalement, contrairement à l'écran plein écran.
        if self.external_display is not None and self.external_display.winfo_exists():
            self.external_display.destroy()
            self.external_display = None
            self.window.set_external_open(False)
            self.window.log("Affichage externe fermé.")
            return
        ScreenPicker(self.window, on_selected=self._open_external_on)

    def _open_external_on(self, monitor: MonitorInfo) -> None:
        if self.external_display is not None and self.external_display.winfo_exists():
            self.external_display.destroy()
        self.external_display = ExternalDisplay(self.window, monitor)
        self.window.set_external_open(True)
        self.window.log(f"Affichage externe ouvert sur {monitor.label}.")

    # ---- cycle de vie ----------------------------------------------------

    def _show_window(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _on_close(self) -> None:
        self._persist_config_from_ui()
        self.window.withdraw()
        self.window.log("Réduit dans la zone de notification.")

    def _really_quit(self) -> None:
        self.running = False
        self._persist_config_from_ui()
        self.tray.stop()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()
