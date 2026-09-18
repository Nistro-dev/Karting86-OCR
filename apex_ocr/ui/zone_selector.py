"""Sélection à la souris de la zone du timer sur un screenshot de la fenêtre."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk


class ZoneSelector(ctk.CTkToplevel):
    def __init__(self, parent, screenshot: Image.Image, current_zone: Optional[list[int]] = None):
        super().__init__(parent)
        self.title("Sélectionner la zone du timer")
        self.resizable(False, False)
        self.result: Optional[list[int]] = None

        max_w, max_h = 1000, 750
        img_w, img_h = screenshot.size
        self.scale = min(max_w / img_w, max_h / img_h, 1.0)
        disp_w, disp_h = int(img_w * self.scale), int(img_h * self.scale)

        ctk.CTkLabel(
            self, text="Dessinez un rectangle autour du timer puis cliquez Valider", font=("Segoe UI", 12)
        ).pack(pady=8)

        self._display_img = screenshot.resize((disp_w, disp_h), Image.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(self._display_img)

        self.canvas = tk.Canvas(self, width=disp_w, height=disp_h, cursor="crosshair", highlightthickness=0)
        self.canvas.pack(padx=10)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)

        if current_zone:
            x, y, w, h = current_zone
            sx, sy, sw, sh = int(x * self.scale), int(y * self.scale), int(w * self.scale), int(h * self.scale)
            self.canvas.create_rectangle(sx, sy, sx + sw, sy + sh, outline="lime", width=2, dash=(5, 3))

        self._rect_id = None
        self._start_x = self._start_y = 0

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="Valider", command=self._validate, width=110).pack(side=tk.LEFT, padx=6)
        ctk.CTkButton(btn_row, text="Annuler", command=self._cancel, width=110, fg_color="transparent").pack(
            side=tk.LEFT, padx=6
        )

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - self.winfo_width()) // 2}+{(sh - self.winfo_height()) // 2}")

    def _on_press(self, event):
        self._start_x, self._start_y = event.x, event.y
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event):
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            self._start_x, self._start_y, event.x, event.y, outline="red", width=2
        )

    def _on_release(self, event):
        x1, y1 = min(self._start_x, event.x), min(self._start_y, event.y)
        x2, y2 = max(self._start_x, event.x), max(self._start_y, event.y)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        self.result = [
            int(x1 / self.scale),
            int(y1 / self.scale),
            int((x2 - x1) / self.scale),
            int((y2 - y1) / self.scale),
        ]

    def _validate(self):
        if self.result:
            self.destroy()
        else:
            messagebox.showwarning("Zone", "Dessinez d'abord un rectangle.", parent=self)

    def _cancel(self):
        self.result = None
        self.destroy()
