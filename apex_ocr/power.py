"""Événements d'alimentation et de session Windows : mise en veille / reprise,
verrouillage / déverrouillage.

Une fenêtre cachée (thread dédié avec sa boucle de messages) reçoit
``WM_POWERBROADCAST`` et ``WM_WTSSESSION_CHANGE`` ; les callbacks sont livrés
au thread Tk via ``post`` (typiquement ``window.after(0, ...)``). Rien ici ne
bloque ni ne lève : hors Windows ou en cas d'échec, le moniteur est simplement
inactif.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable, Optional

WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WM_CLOSE = 0x0010

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
WTS_SESSION_LOCK = 0x0007
WTS_SESSION_UNLOCK = 0x0008
NOTIFY_FOR_THIS_SESSION = 0

_log = logging.getLogger("apex_ocr")


class PowerMonitor:
    """``on_suspend`` juste avant la veille, ``on_resume`` au réveil (une seule fois,
    même si Windows envoie deux messages de reprise), ``on_lock``/``on_unlock`` au
    (dé)verrouillage de la session."""

    def __init__(self, post: Callable[[Callable[[], None]], None],
                 on_suspend: Optional[Callable[[], None]] = None,
                 on_resume: Optional[Callable[[], None]] = None,
                 on_lock: Optional[Callable[[], None]] = None,
                 on_unlock: Optional[Callable[[], None]] = None):
        self._post = post
        self._callbacks = {"suspend": on_suspend, "resume": on_resume, "lock": on_lock, "unlock": on_unlock}
        self._suspended = False
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None

    # ---- logique pure (testable) ------------------------------------------

    def dispatch(self, msg: int, wparam: int) -> Optional[str]:
        """Traduit un message Windows en événement et l'envoie au thread Tk.
        Renvoie le nom de l'événement émis (ou None)."""
        event = None
        if msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND and not self._suspended:
                self._suspended, event = True, "suspend"
            elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND) and self._suspended:
                self._suspended, event = False, "resume"
        elif msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                event = "lock"
            elif wparam == WTS_SESSION_UNLOCK:
                event = "unlock"
        if event is None:
            return None
        callback = self._callbacks.get(event)
        if callback is not None:
            try:
                self._post(callback)
            except Exception:  # appli en cours de fermeture
                pass
        return event

    # ---- fenêtre cachée Windows ----------------------------------------------

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="power-monitor")
        self._thread.start()

    def stop(self) -> None:
        hwnd, self._hwnd = self._hwnd, None
        if hwnd:
            try:
                import win32gui
                win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            import ctypes
            import win32con
            import win32gui

            def wndproc(hwnd, msg, wparam, lparam):
                if msg in (WM_POWERBROADCAST, WM_WTSSESSION_CHANGE):
                    self.dispatch(msg, wparam)
                    return 1 if msg == WM_POWERBROADCAST else 0
                if msg == WM_CLOSE:
                    win32gui.DestroyWindow(hwnd)
                    return 0
                if msg == win32con.WM_DESTROY:
                    win32gui.PostQuitMessage(0)
                    return 0
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

            wc = win32gui.WNDCLASS()
            wc.lpszClassName = "ApexOcrPowerMonitor"
            wc.lpfnWndProc = wndproc
            atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(atom, "ApexOcrPowerMonitor", 0, 0, 0, 0, 0, 0, 0, 0, None)
            try:
                ctypes.windll.wtsapi32.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION)
            except Exception:
                pass  # pas de (dé)verrouillage : la veille reste gérée
            win32gui.PumpMessages()
        except Exception as exc:
            _log.debug("Moniteur veille/session indisponible : %s", exc)
        finally:
            self._hwnd = None
