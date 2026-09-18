"""Fenêtre plein écran affichant temps + tours sur l'écran choisi (piste)."""
from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

from apex_ocr.health import HealthStatus
from apex_ocr.session import DisplayValue
from apex_ocr.ui import branding
from apex_ocr.ui.screen_picker import MonitorInfo

_STATE_COLORS = {
    HealthStatus.IDLE: "#4a4a4a",
    HealthStatus.ACTIVE: "#00c94a",
    HealthStatus.ERROR: branding.PRIMARY_RED,
}


class ExternalDisplay(tk.Toplevel):
    def __init__(self, parent, monitor: MonitorInfo):
        super().__init__(parent)
        self.title("Timer")
        self.configure(bg="black")
        # overrideredirect + géométrie exacte : positionnement fiable sur
        # l'écran choisi. L'attribut "-fullscreen" de Tk recentre parfois la
        # fenêtre sur l'écran principal côté Windows, on l'évite donc ici.
        self.overrideredirect(True)
        self.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
        self.attributes("-topmost", True)

        dot = tk.Canvas(self, width=28, height=28, bg="black", highlightthickness=0)
        dot.place(x=28, y=28)
        self._dot = dot
        self._dot_id = dot.create_oval(4, 4, 24, 24, fill=_STATE_COLORS[HealthStatus.IDLE], outline="")

        center = tk.Frame(self, bg="black")
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._time_var = tk.StringVar(value="--:--")
        time_lbl = tk.Label(
            center, textvariable=self._time_var, font=("", 220, "bold"), fg="#FFFFFF", bg="black"
        )
        time_lbl.pack()

        self._laps_var = tk.StringVar(value="")
        laps_lbl = tk.Label(
            center, textvariable=self._laps_var, font=("", 90, "bold"), fg=branding.PRIMARY_RED, bg="black"
        )
        laps_lbl.pack(pady=(10, 0))

        self._logo_photo = None
        logo = branding.load_logo()
        if logo is not None:
            display_w = 180
            display_h = int(logo.height * (display_w / logo.width))
            self._logo_photo = ImageTk.PhotoImage(logo.resize((display_w, display_h)))
            logo_lbl = tk.Label(self, image=self._logo_photo, bg="black")
            logo_lbl.place(relx=1.0, rely=1.0, x=-20, y=-16, anchor="se")

        # Bouton fermeture discret (mêmes couleurs que le fond, pas de texte) :
        # un clic dessus marche toujours, contrairement au raccourci clavier
        # qui dépend du focus (peu fiable si l'appli n'a pas la main sur Windows).
        close_btn = tk.Label(self, text="✕", font=("Segoe UI", 16), fg="#333", bg="black", cursor="hand2")
        close_btn.place(relx=1.0, x=-10, y=8, anchor="ne")
        close_btn.bind("<Button-1>", lambda e: self.destroy())

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Alt-F4>", lambda e: self.destroy())
        for widget in (self, center, dot, time_lbl, laps_lbl):
            widget.bind("<Double-Button-1>", lambda e: self.destroy())

        self.focus_force()
        self.after(150, self.focus_force)

    def set_display(self, value: DisplayValue) -> None:
        self._time_var.set(value.time_text)
        if value.laps_total is not None:
            self._laps_var.set(f"{value.laps_done} / {value.laps_total}")
        else:
            self._laps_var.set("")

    def set_health(self, status: HealthStatus) -> None:
        self._dot.itemconfig(self._dot_id, fill=_STATE_COLORS[status])
