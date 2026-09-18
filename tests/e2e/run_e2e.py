"""Harnais de tests de bout en bout : pilote un vrai navigateur sur
test_timer_mini.html, lance une vraie instance de l'appli dessus (capture
d'écran + OCR réels), et vérifie le comportement via son journal.

Chaque scénario tourne dans un profil navigateur et un dossier de données
(%LOCALAPPDATA%) isolés et jetables : ne touche jamais à la config réelle
de l'utilisateur, et peut tourner en parallèle d'une session manuelle.

Usage : py tests/e2e/run_e2e.py
Nécessite : Tesseract installé, Edge ou Chrome installé, un écran réel.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import win32gui  # noqa: E402

from apex_ocr import capture  # noqa: E402
from apex_ocr.config import find_tesseract  # noqa: E402
from apex_ocr.ocr import engine  # noqa: E402
from apex_ocr.ocr.calibration import calibrate_threshold  # noqa: E402

engine.set_tesseract_path(find_tesseract())

PAGE_TITLE = "Mini Timer Test - Apex Timing OCR"
PAGE_PATH = REPO_ROOT / "test_timer_mini.html"
WINDOW_W, WINDOW_H = 700, 500
BOX_X, BOX_Y, BOX_W, BOX_H = 20, 20, 420, 130

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str:
    for path in BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("Aucun navigateur (Edge/Chrome) trouvé aux emplacements habituels.")


@dataclass
class Scenario:
    name: str
    query: str
    wait_seconds: float
    expect_contains: list[str] = field(default_factory=list)
    expect_not_contains: list[str] = field(default_factory=list)
    max_occurrences: dict[str, int] = field(default_factory=dict)
    extra_check: "callable | None" = None


SCENARIOS = [
    Scenario(
        name="mm:ss - course normale jusqu'au bout (pas de faux 'signal perdu')",
        query="fmt=mmss&duration=00:00:15&autostart=300",
        wait_seconds=19,
        expect_contains=["Départ détecté", "Session terminée (temps écoulé)"],
        expect_not_contains=["signal perdu", "course annulée"],
    ),
    Scenario(
        name="hh:mm:ss - le format heures est bien suivi (pas 'XX:XX' -> nombre à 3 chiffres)",
        query="fmt=hhmmss&duration=00:00:08&autostart=300",
        wait_seconds=12,
        expect_contains=["Départ détecté", "Session terminée (temps écoulé)"],
        expect_not_contains=["signal perdu", "course annulée"],
        extra_check=lambda log: bool(re.search(r"Timer \d{2}:\d{2}:\d{2}", log)),
    ),
    Scenario(
        name="tours - la session s'arrête sur les tours avant la fin du temps",
        query="fmt=laps_mmss&duration=00:01:00&lapsTotal=3&autostart=300&autolap=1200",
        wait_seconds=8,
        expect_contains=["Départ détecté", "Session terminée (tours terminés)"],
        expect_not_contains=["signal perdu", "course annulée", "temps écoulé"],
    ),
    Scenario(
        name="annulation - bouton Stop -> 'course annulée', pas de boucle de redémarrage",
        query="fmt=mmss&duration=00:00:30&autostart=300&autostop=3000",
        wait_seconds=8,
        expect_contains=["Départ détecté", "Session terminée (course annulée)"],
        expect_not_contains=["signal perdu"],
        max_occurrences={"Départ détecté": 1},
    ),
]


def launch_browser(browser_path: str, url: str, profile_dir: str) -> subprocess.Popen:
    args = [
        browser_path,
        f"--app={url}",
        f"--window-position=40,40",
        f"--window-size={WINDOW_W},{WINDOW_H}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    return subprocess.Popen(args)


def find_hwnd_near(title: str, near: tuple[int, int], timeout: float = 10.0) -> int:
    """Attend puis retrouve le handle de la fenêtre par titre, en préférant
    celle positionnée là où on l'a lancée (--window-position) : évite de
    confondre avec une autre fenêtre qui porterait le même titre (ex: la
    page ouverte manuellement par ailleurs pendant les tests)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = []

        def _enum(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
                matches.append((hwnd, win32gui.GetWindowRect(hwnd)))

        win32gui.EnumWindows(_enum, None)
        if matches:
            close = [hwnd for hwnd, (l, t, _r, _b) in matches if abs(l - near[0]) < 80 and abs(t - near[1]) < 80]
            if close:
                return close[0]
            if len(matches) == 1:
                return matches[0][0]
        time.sleep(0.2)
    raise TimeoutError(f"Fenêtre « {title} » introuvable après {timeout}s.")


def compute_zone(hwnd: int) -> tuple[int, int, int, int]:
    left, top, _right, _bottom = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (left, top))
    return (x + BOX_X, y + BOX_Y, BOX_W, BOX_H)


def write_app_config(data_dir: Path, window_title: str, zone: tuple[int, int, int, int], threshold: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "window_title": window_title,
        "zone": list(zone),
        "ocr_interval_ms": 150,
        "threshold": threshold,
        "resync_tolerance_seconds": 3,
        "ocr_lost_timeout_seconds": 10.0,
        "log_retention_days": 3,
    }
    with open(data_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def run_scenario(scenario: Scenario, browser_path: str) -> tuple[bool, str]:
    profile_dir = tempfile.mkdtemp(prefix="apex_ocr_e2e_profile_")
    app_local_appdata = tempfile.mkdtemp(prefix="apex_ocr_e2e_data_")
    browser_proc = app_proc = None
    run_id = uuid.uuid4().hex[:8]
    window_title = f"{PAGE_TITLE} #{run_id}"
    try:
        url = f"file:///{PAGE_PATH.as_posix()}?{scenario.query}&runid={run_id}"
        browser_proc = launch_browser(browser_path, url, profile_dir)
        hwnd = find_hwnd_near(window_title, near=(40, 40))
        zone = compute_zone(hwnd)

        img = capture.capture_zone(window_title, zone)
        if img is None:
            return False, "Capture de la zone de test impossible (fenêtre non trouvée/capturable)."
        threshold = calibrate_threshold(img)
        if threshold is None:
            return False, "Calibration auto du seuil échouée sur la page de test (rien de lisible)."

        data_dir = Path(app_local_appdata) / "ApexTimingOCR"
        write_app_config(data_dir, window_title, zone, threshold)

        env = os.environ.copy()
        env["LOCALAPPDATA"] = app_local_appdata
        app_proc = subprocess.Popen(
            [sys.executable, "main.py", "--minimized"], cwd=str(REPO_ROOT), env=env
        )

        time.sleep(scenario.wait_seconds)

        log_path = data_dir / "logs" / "apex_ocr.log"
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

        failures = []
        for needle in scenario.expect_contains:
            if needle not in log_text:
                failures.append(f"attendu absent : « {needle} »")
        for needle in scenario.expect_not_contains:
            if needle in log_text:
                failures.append(f"présent alors qu'interdit : « {needle} »")
        for needle, max_count in scenario.max_occurrences.items():
            count = log_text.count(needle)
            if count > max_count:
                failures.append(f"« {needle} » apparaît {count}x (max attendu {max_count})")
        if scenario.extra_check is not None and not scenario.extra_check(log_text):
            failures.append("vérification supplémentaire échouée")

        if failures:
            detail = "\n    - " + "\n    - ".join(failures) + f"\n    (log : {log_path})"
            return False, detail
        return True, "OK"
    finally:
        for proc in (app_proc, browser_proc):
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
        time.sleep(0.5)
        shutil.rmtree(profile_dir, ignore_errors=True)
        shutil.rmtree(app_local_appdata, ignore_errors=True)


def main() -> int:
    browser_path = find_browser()
    print(f"Navigateur : {browser_path}")
    print(f"Page de test : {PAGE_PATH}\n")

    results = []
    for scenario in SCENARIOS:
        print(f"-> {scenario.name} ...", flush=True)
        ok, detail = run_scenario(scenario, browser_path)
        results.append((scenario.name, ok, detail))
        print(f"   {'PASS' if ok else 'FAIL'}{'' if ok else detail}")

    print("\n=== Résumé ===")
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, _ in results:
        print(f"  [{'OK' if ok else 'X '}] {name}")
    print(f"\n{passed}/{len(results)} scénarios réussis.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
