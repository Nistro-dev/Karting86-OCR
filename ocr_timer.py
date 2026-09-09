import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import sys
import time
import threading
import re
from datetime import datetime

if sys.platform == 'win32':
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

DEPS_OK = True
DEPS_ERR = ""
try:
    import pytesseract
    import cv2
    import numpy as np
    from PIL import Image, ImageTk
    import mss
except ImportError as e:
    DEPS_OK = False
    DEPS_ERR = str(e)

gw = None
try:
    import pygetwindow as gw
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "timer.txt")
LOG_PATH = os.path.join(BASE_DIR, "timer_log.txt")

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]


def find_tesseract():
    for p in TESSERACT_PATHS:
        if os.path.exists(p):
            return p
    return ""


def load_config():
    defaults = {
        "window_title": "",
        "zone": None,
        "tesseract_path": find_tesseract(),
        "interval": 500,
        "threshold": 127,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                defaults.update(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return defaults


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class ZoneSelector(tk.Toplevel):
    def __init__(self, parent, screenshot, current_zone=None):
        super().__init__(parent)
        self.title("Sélectionner la zone du timer")
        self.resizable(False, False)
        self.result = None

        max_w, max_h = 1000, 750
        img_w, img_h = screenshot.size
        self.scale = min(max_w / img_w, max_h / img_h, 1.0)
        disp_w = int(img_w * self.scale)
        disp_h = int(img_h * self.scale)

        tk.Label(
            self,
            text="Dessinez un rectangle autour du timer puis cliquez Valider",
            font=("Segoe UI", 11),
        ).pack(pady=6)

        self.display_img = screenshot.resize((disp_w, disp_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(self.display_img)

        self.canvas = tk.Canvas(self, width=disp_w, height=disp_h, cursor="crosshair")
        self.canvas.pack(padx=10)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)

        if current_zone:
            x, y, w, h = current_zone
            sx, sy = int(x * self.scale), int(y * self.scale)
            sw, sh = int(w * self.scale), int(h * self.scale)
            self.canvas.create_rectangle(
                sx, sy, sx + sw, sy + sh, outline="lime", width=2, dash=(5, 3)
            )

        self.rect_id = None
        self.start_x = self.start_y = 0

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        btn = ttk.Frame(self)
        btn.pack(pady=8)
        ttk.Button(btn, text="Valider", command=self.validate, width=12).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn, text="Annuler", command=self.cancel, width=12).pack(
            side=tk.LEFT, padx=5
        )

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(
            f"+{(sw - self.winfo_width()) // 2}+{(sh - self.winfo_height()) // 2}"
        )

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

    def on_drag(self, event):
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y, outline="red", width=2
        )

    def on_release(self, event):
        x1, y1 = min(self.start_x, event.x), min(self.start_y, event.y)
        x2, y2 = max(self.start_x, event.x), max(self.start_y, event.y)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        self.result = [
            int(x1 / self.scale),
            int(y1 / self.scale),
            int((x2 - x1) / self.scale),
            int((y2 - y1) / self.scale),
        ]

    def validate(self):
        if self.result:
            self.destroy()
        else:
            messagebox.showwarning(
                "Zone", "Dessinez d'abord un rectangle.", parent=self
            )

    def cancel(self):
        self.result = None
        self.destroy()


class ExternalDisplay(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Timer")
        self.configure(bg="black")
        self.geometry("800x300")

        self.time_var = tk.StringVar(value="--:--")
        self.label = tk.Label(
            self,
            textvariable=self.time_var,
            font=("Consolas", 140, "bold"),
            fg="#00FF00",
            bg="black",
        )
        self.label.pack(expand=True)

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<F11>", self.toggle_fs)
        self.bind("<Double-Button-1>", self.toggle_fs)
        self._fs = False

    def toggle_fs(self, event=None):
        self._fs = not self._fs
        self.attributes("-fullscreen", self._fs)

    def set_time(self, text):
        self.time_var.set(text if text else "--:--")


class App:
    def __init__(self):
        if not DEPS_OK:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Erreur",
                f"Dépendance manquante :\n{DEPS_ERR}\n\nLancez install.bat",
            )
            sys.exit(1)

        self.cfg = load_config()
        self.running = False
        self.last_time = ""
        self.thread = None
        self.ext_display = None

        self.root = tk.Tk()
        self.root.title("Apex Timing OCR")
        self.root.geometry("680x600")
        self.root.minsize(550, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if self.cfg["tesseract_path"] and os.path.exists(self.cfg["tesseract_path"]):
            pytesseract.pytesseract.tesseract_cmd = self.cfg["tesseract_path"]

        self.build_ui()

    def build_ui(self):
        m = ttk.Frame(self.root, padding=10)
        m.pack(fill=tk.BOTH, expand=True)

        cfg_f = ttk.LabelFrame(m, text="Configuration", padding=8)
        cfg_f.pack(fill=tk.X, pady=(0, 8))

        r = ttk.Frame(cfg_f)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Tesseract :", width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.tess_var = tk.StringVar(value=self.cfg["tesseract_path"])
        ttk.Entry(r, textvariable=self.tess_var, width=48).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(r, text="...", command=self.browse_tess, width=3).pack(side=tk.LEFT)

        r = ttk.Frame(cfg_f)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Fenêtre :", width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.win_var = tk.StringVar(value=self.cfg["window_title"])
        self.win_combo = ttk.Combobox(r, textvariable=self.win_var, width=45)
        self.win_combo.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(r, text="↻", command=self.refresh_windows, width=3).pack(
            side=tk.LEFT
        )

        r = ttk.Frame(cfg_f)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Zone :", width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.zone_lbl = ttk.Label(r, text=self._fmt_zone())
        self.zone_lbl.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(r, text="Définir la zone", command=self.select_zone).pack(
            side=tk.LEFT
        )

        r = ttk.Frame(cfg_f)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Seuil :", width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.thresh_var = tk.IntVar(value=self.cfg["threshold"])
        ttk.Scale(
            r, from_=0, to=255, variable=self.thresh_var, orient=tk.HORIZONTAL, length=220
        ).pack(side=tk.LEFT)
        self.thresh_lbl = ttk.Label(r, text=str(self.thresh_var.get()), width=4)
        self.thresh_lbl.pack(side=tk.LEFT, padx=5)
        self.thresh_var.trace_add(
            "write", lambda *_: self.thresh_lbl.config(text=str(self.thresh_var.get()))
        )

        r = ttk.Frame(cfg_f)
        r.pack(fill=tk.X, pady=2)
        ttk.Label(r, text="Intervalle :", width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.interval_var = tk.IntVar(value=self.cfg["interval"])
        ttk.Spinbox(
            r, from_=100, to=5000, increment=100, textvariable=self.interval_var, width=7
        ).pack(side=tk.LEFT)
        ttk.Label(r, text="ms").pack(side=tk.LEFT, padx=3)

        prev_f = ttk.LabelFrame(m, text="Aperçu zone capturée", padding=4)
        prev_f.pack(fill=tk.X, pady=(0, 8))
        self.preview_canvas = tk.Canvas(prev_f, height=60, bg="#1e1e1e")
        self.preview_canvas.pack(fill=tk.X)
        self._preview_img = None

        timer_f = ttk.LabelFrame(m, text="Timer détecté", padding=4)
        timer_f.pack(fill=tk.X, pady=(0, 8))
        timer_bg = tk.Frame(timer_f, bg="black")
        timer_bg.pack(fill=tk.X, ipady=8)
        self.time_lbl = tk.Label(
            timer_bg,
            text="--:--",
            font=("Consolas", 52, "bold"),
            fg="#00FF00",
            bg="black",
        )
        self.time_lbl.pack()

        btn_f = ttk.Frame(m)
        btn_f.pack(fill=tk.X, pady=(0, 8))
        self.start_btn = ttk.Button(
            btn_f, text="▶  Démarrer", command=self.start_ocr
        )
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(
            btn_f, text="■  Arrêter", command=self.stop_ocr, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="Affichage externe", command=self.open_ext).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_f, text="Test OCR", command=self.test_ocr).pack(
            side=tk.RIGHT, padx=4
        )

        log_f = ttk.LabelFrame(m, text="Journal", padding=4)
        log_f.pack(fill=tk.BOTH, expand=True)
        self.log_txt = tk.Text(log_f, height=6, font=("Consolas", 9), state=tk.DISABLED)
        sb = ttk.Scrollbar(log_f, orient=tk.VERTICAL, command=self.log_txt.yview)
        self.log_txt.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_txt.pack(fill=tk.BOTH, expand=True)

        self.refresh_windows()
        self.log("Application prête. Sélectionnez une fenêtre et définissez la zone.")

    def _fmt_zone(self):
        z = self.cfg.get("zone")
        if z:
            return f"x={z[0]}  y={z[1]}  {z[2]}×{z[3]} px"
        return "Non définie"

    def log(self, msg):
        self.log_txt.config(state=tk.NORMAL)
        self.log_txt.insert(tk.END, msg + "\n")
        self.log_txt.see(tk.END)
        self.log_txt.config(state=tk.DISABLED)

    def browse_tess(self):
        p = filedialog.askopenfilename(
            title="Sélectionner tesseract.exe",
            filetypes=[("Executable", "*.exe"), ("Tous", "*.*")],
        )
        if p:
            self.tess_var.set(p)
            self.cfg["tesseract_path"] = p
            pytesseract.pytesseract.tesseract_cmd = p
            save_config(self.cfg)

    def refresh_windows(self):
        if gw is None:
            return
        try:
            titles = sorted(set(t for t in gw.getAllTitles() if t.strip()))
            self.win_combo["values"] = titles
        except Exception as e:
            self.log(f"Erreur liste fenêtres : {e}")

    def _capture_window_screenshot(self):
        title = self.win_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Sélectionnez d'abord une fenêtre.")
            return None
        if gw is None:
            messagebox.showwarning("Attention", "pygetwindow non disponible (Windows).")
            return None
        try:
            wins = gw.getWindowsWithTitle(title)
            if not wins:
                messagebox.showwarning("Attention", f"Fenêtre « {title} » introuvable.")
                return None
            w = wins[0]
            if w.isMinimized:
                w.restore()
                time.sleep(0.3)
            with mss.mss() as sct:
                mon = {
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height,
                }
                shot = sct.grab(mon)
                return Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
        except Exception as e:
            messagebox.showerror("Erreur", f"Capture impossible :\n{e}")
            return None

    def select_zone(self):
        img = self._capture_window_screenshot()
        if not img:
            return
        self.cfg["window_title"] = self.win_var.get().strip()
        sel = ZoneSelector(self.root, img, self.cfg.get("zone"))
        self.root.wait_window(sel)
        if sel.result:
            self.cfg["zone"] = sel.result
            self.zone_lbl.config(text=self._fmt_zone())
            save_config(self.cfg)
            self.log(f"Zone définie : {self._fmt_zone()}")

    def _get_abs_region(self):
        title = self.win_var.get().strip()
        zone = self.cfg.get("zone")
        if not title or not zone or gw is None:
            return None
        try:
            wins = gw.getWindowsWithTitle(title)
            if not wins:
                return None
            w = wins[0]
            zx, zy, zw, zh = zone
            return {"left": w.left + zx, "top": w.top + zy, "width": zw, "height": zh}
        except Exception:
            return None

    def _capture_zone(self):
        region = self._get_abs_region()
        if not region:
            return None
        try:
            with mss.mss() as sct:
                shot = sct.grab(region)
                return Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
        except Exception:
            return None

    def _preprocess(self, pil_img):
        arr = np.array(pil_img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        thresh = self.thresh_var.get()
        _, bw = cv2.threshold(gray, thresh, 255, cv2.THRESH_BINARY)
        h, w = bw.shape
        if h < 60:
            s = max(2, 60 // h)
            bw = cv2.resize(bw, (w * s, h * s), interpolation=cv2.INTER_CUBIC)
        return bw

    def _clean_text(self, raw):
        text = re.sub(r"[^0-9:]", "", raw)
        if ":" not in text and len(text) >= 3:
            if len(text) == 3:
                text = text[0] + ":" + text[1:]
            elif len(text) == 4:
                text = text[:2] + ":" + text[2:]
            elif len(text) == 5:
                text = text[0] + ":" + text[1:3] + ":" + text[3:]
            elif len(text) == 6:
                text = text[:2] + ":" + text[2:4] + ":" + text[4:]
        return text

    def _extract(self, processed):
        config = "--psm 7 -c tessedit_char_whitelist=0123456789:"
        raw = pytesseract.image_to_string(processed, config=config)
        return self._clean_text(raw.strip())

    def _is_valid(self, text):
        return bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", text))

    def _update_preview(self, pil_img):
        cw = self.preview_canvas.winfo_width()
        if cw < 10:
            cw = 640
        iw, ih = pil_img.size
        s = min(cw / iw, 60 / ih, 4.0)
        dw, dh = max(1, int(iw * s)), max(1, int(ih * s))
        disp = pil_img.resize((dw, dh), Image.LANCZOS)
        self._preview_img = ImageTk.PhotoImage(disp)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            cw // 2, 30, anchor=tk.CENTER, image=self._preview_img
        )

    def test_ocr(self):
        img = self._capture_zone()
        if not img:
            self.log("Capture impossible. Vérifiez fenêtre et zone.")
            return
        processed = self._preprocess(img)
        text = self._extract(processed)
        self._update_preview(img)
        if text:
            valid = self._is_valid(text)
            self.log(f"Test OCR : « {text} »" + (" ✓" if valid else " (format invalide)"))
            self.time_lbl.config(text=text)
        else:
            self.log("Test OCR : aucun texte. Ajustez le seuil ou la zone.")

    def start_ocr(self):
        title = self.win_var.get().strip()
        zone = self.cfg.get("zone")
        if not title:
            messagebox.showwarning("Attention", "Sélectionnez une fenêtre.")
            return
        if not zone:
            messagebox.showwarning("Attention", "Définissez la zone de capture.")
            return
        tpath = self.tess_var.get().strip()
        if tpath and not os.path.exists(tpath):
            messagebox.showwarning("Attention", "Chemin Tesseract invalide.")
            return

        self.cfg["window_title"] = title
        self.cfg["tesseract_path"] = tpath
        self.cfg["threshold"] = self.thresh_var.get()
        self.cfg["interval"] = self.interval_var.get()
        save_config(self.cfg)

        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.log("OCR démarré")
        self.thread = threading.Thread(target=self._ocr_loop, daemon=True)
        self.thread.start()

    def stop_ocr(self):
        self.running = False
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.log("OCR arrêté")

    def _ocr_loop(self):
        while self.running:
            try:
                img = self._capture_zone()
                if img:
                    processed = self._preprocess(img)
                    text = self._extract(processed)
                    self.root.after(0, self._update_preview, img)
                    if text and text != self.last_time:
                        self.last_time = text
                        self.root.after(0, self._on_new_time, text)
            except Exception as e:
                self.root.after(0, self.log, f"Erreur OCR : {e}")
            time.sleep(self.interval_var.get() / 1000)

    def _on_new_time(self, text):
        self.time_lbl.config(text=text)
        if self.ext_display and self.ext_display.winfo_exists():
            self.ext_display.set_time(text)
        ts = datetime.now().strftime("%H:%M:%S")
        self.log(f"{ts}  →  {text}")
        try:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(text)
        except IOError:
            pass
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {text}\n")
        except IOError:
            pass

    def open_ext(self):
        if self.ext_display and self.ext_display.winfo_exists():
            self.ext_display.lift()
            return
        self.ext_display = ExternalDisplay(self.root)
        if self.last_time:
            self.ext_display.set_time(self.last_time)
        self.log("Affichage externe ouvert (F11 = plein écran, Echap = fermer)")

    def on_close(self):
        self.running = False
        self.cfg["window_title"] = self.win_var.get().strip()
        self.cfg["tesseract_path"] = self.tess_var.get().strip()
        self.cfg["threshold"] = self.thresh_var.get()
        self.cfg["interval"] = self.interval_var.get()
        save_config(self.cfg)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
