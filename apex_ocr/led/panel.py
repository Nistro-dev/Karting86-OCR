"""Pilotage BLE du panneau LED (iPixel Color, voir newkart-led-panel).

Une boucle asyncio dédiée tourne dans son propre thread : les écritures
Bluetooth (lentes, variables — souvent ~1s pour une image) ne bloquent donc
jamais ni l'UI Tk ni la boucle OCR.

Une seule coroutine (``_run``) gère connexion, reconnexion et envoi, ce qui
évite toute course entre plusieurs tâches. Le Tk thread ne fait que déposer
le contenu *voulu* ; la coroutine envoie toujours la valeur la plus récente
et saute les intermédiaires : si le Bluetooth prend du retard, le panneau
passe directement à la bonne valeur au lieu d'accumuler un décalage.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from enum import Enum, auto
from typing import Optional

from bleak import BleakClient, BleakScanner

from apex_ocr.led.content import PanelContent
from apex_ocr.led.protocol import (
    DEVICE_NAME_PREFIX,
    UUID_WRITE,
    brightness_command,
    build_png_packet,
    power_command,
)
from apex_ocr.led.rendering import TimerRenderer, blank_png

CONNECT_TIMEOUT_S = 15.0
RETRY_MIN_S = 3.0
RETRY_MAX_S = 30.0
SHUTDOWN_TIMEOUT_S = 3.0
BRIGHTNESS = 100  # toujours au maximum (piste en extérieur)

_UNSENT = object()  # rien d'envoyé depuis la connexion (≠ None = écran vide envoyé)


class LedStatus(Enum):
    DISABLED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RETRYING = auto()


class LedPanel:
    def __init__(self, width: int, height: int, rgb: tuple, alert_rgb: tuple, logger: logging.Logger):
        self._width = width
        self._height = height
        self._rgb = rgb
        self._alert_rgb = alert_rgb
        self._renderer = TimerRenderer(width, height, rgb)
        self._logger = logger

        # Lus depuis le thread Tk (affectations simples, atomiques en CPython).
        self.status = LedStatus.DISABLED
        self.status_detail = ""

        # État partagé : écrit uniquement dans le thread asyncio.
        self._address: Optional[str] = None
        self._desired: Optional[PanelContent] = None
        self._sent: object = _UNSENT
        self._client: Optional[BleakClient] = None

        # Côté Tk : évite de réveiller la boucle 5x/s pour la même valeur.
        self._last_requested: object = _UNSENT

        self._loop = asyncio.new_event_loop()
        self._wake = asyncio.Event()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="led-panel")
        self._thread.start()
        self._main = asyncio.run_coroutine_threadsafe(self._run(), self._loop)

    # ---- API (thread-safe, appelée depuis Tk) -----------------------------

    def connect(self, address: str) -> None:
        self._call(self._set_address, address.strip() or None)

    def disconnect(self) -> None:
        self._call(self._set_address, None)

    def show(self, content: Optional[PanelContent]) -> None:
        """Contenu voulu sur le panneau (``None`` = écran vide)."""
        if content == self._last_requested:
            return
        self._last_requested = content
        self._call(self._set_desired, content)

    def set_color(self, rgb: tuple) -> None:
        self._call(self._set_color, tuple(rgb))

    def set_alert_color(self, rgb: tuple) -> None:
        self._call(self._set_alert_color, tuple(rgb))

    def scan(self, timeout: float = 6.0) -> Future:
        """Future -> liste de (nom, adresse) des panneaux ``LED_BLE_*`` à proximité."""
        return asyncio.run_coroutine_threadsafe(self._scan(timeout), self._loop)

    def shutdown(self) -> None:
        """Vide l'écran et coupe la connexion (à la fermeture de l'appli),
        sans jamais bloquer la sortie plus de quelques secondes."""
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(SHUTDOWN_TIMEOUT_S)
        except Exception:
            pass

    # ---- côté boucle asyncio ------------------------------------------------

    def _call(self, fn, *args) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    def _set_address(self, address: Optional[str]) -> None:
        self._address = address
        self._wake.set()

    def _set_desired(self, content: Optional[PanelContent]) -> None:
        self._desired = content
        self._wake.set()

    def _set_color(self, rgb: tuple) -> None:
        self._rgb = rgb
        self._renderer.rgb = rgb
        self._sent = _UNSENT
        self._wake.set()

    def _set_alert_color(self, rgb: tuple) -> None:
        self._alert_rgb = rgb
        self._sent = _UNSENT
        self._wake.set()

    def _on_ble_disconnect(self, _client: BleakClient) -> None:
        self._loop.call_soon_threadsafe(self._wake.set)

    def _set_status(self, status: LedStatus, detail: str = "") -> None:
        if status != self.status:
            self._logger.info("Panneau LED : %s%s", status.name, f" ({detail})" if detail else "")
        self.status = status
        self.status_detail = detail

    async def _wait_wake(self, timeout: Optional[float] = None) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    def _is_connected(self) -> bool:
        return (
            self._client is not None
            and self._client.is_connected
            and self._address is not None
            and self._client.address.upper() == self._address.upper()
        )

    async def _run(self) -> None:
        backoff = RETRY_MIN_S
        while True:
            try:
                if self._address is None:
                    await self._blank_and_close()
                    self._set_status(LedStatus.DISABLED)
                    await self._wait_wake()
                    continue

                if not self._is_connected():
                    await self._blank_and_close()
                    self._set_status(LedStatus.CONNECTING if backoff == RETRY_MIN_S else LedStatus.RETRYING,
                                     self.status_detail)
                    try:
                        await self._open(self._address)
                    except Exception as exc:
                        await self._close_client()
                        self._set_status(LedStatus.RETRYING, str(exc) or type(exc).__name__)
                        await self._wait_wake(backoff)
                        backoff = min(backoff * 2, RETRY_MAX_S)
                        continue
                    backoff = RETRY_MIN_S
                    self._set_status(LedStatus.CONNECTED)

                target = self._desired
                if target != self._sent:
                    await self._send_content(target)
                    self._sent = target
                else:
                    await self._wait_wake()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Écriture échouée en cours de route (connexion tombée) : on
                # repart dans la boucle, qui reconnecte puis renvoie la valeur
                # la plus récente.
                self._logger.warning("Panneau LED : envoi échoué (%s)", exc)
                self._set_status(LedStatus.RETRYING, str(exc) or type(exc).__name__)
                await self._close_client()

    async def _open(self, address: str) -> None:
        client = BleakClient(address, disconnected_callback=self._on_ble_disconnect, timeout=CONNECT_TIMEOUT_S)
        self._client = client
        await client.connect()
        # La luminosité doit être appliquée AVANT toute image, sinon le panneau
        # revient à son affichage par défaut (constaté sur newkart-led-panel).
        await self._write(brightness_command(BRIGHTNESS), response=False)
        await self._write(power_command(True), response=False)
        await self._write(build_png_packet(blank_png(self._width, self._height)))
        self._sent = None

    async def _send_content(self, content: Optional[PanelContent]) -> None:
        if content is None:
            png = blank_png(self._width, self._height)
        else:
            rgb = self._alert_rgb if content.alert else self._rgb
            self._renderer.rgb = rgb
            png = self._renderer.render(content.time_text, content.laps_text)
        await self._write(build_png_packet(png))

    async def _write(self, data: bytes, response: bool = True) -> None:
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("non connecté")
        await self._client.write_gatt_char(UUID_WRITE, data, response=response)

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        self._sent = _UNSENT
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _scan(self, timeout: float) -> list[tuple[str, str]]:
        devices = await BleakScanner.discover(timeout=timeout)
        return [(d.name or "?", d.address) for d in devices if (d.name or "").startswith(DEVICE_NAME_PREFIX)]

    async def _blank_and_close(self) -> None:
        """Vide l'écran si on est encore connecté (déconnexion volontaire,
        changement de panneau), puis ferme la connexion."""
        if self._client is not None and self._client.is_connected:
            try:
                await self._write(build_png_packet(blank_png(self._width, self._height)))
            except Exception:
                pass
        await self._close_client()

    async def _shutdown(self) -> None:
        self._main.cancel()
        await self._blank_and_close()
