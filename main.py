"""Point d'entrée de l'application New Kart - Panneau led."""
import sys

if sys.platform == "win32":
    import ctypes

    # Per-monitor v2 : rendu net des fenêtres sur un 2e écran à une autre échelle.
    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    try:
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            raise OSError("SetProcessDpiAwarenessContext refusé")
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _selftest() -> None:
    try:
        import apex_ocr.app  # noqa: F401
    except ImportError as exc:
        print(f"DEPS_ERR: {exc}")
        sys.exit(1)
    print("OK")


def _show_missing_deps_error(exc: Exception) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Erreur", f"Dépendance manquante :\n{exc}\n\nLancez install.bat")


def main() -> None:
    if "--selftest" in sys.argv:
        _selftest()
        return

    try:
        from apex_ocr.app import App
    except ImportError as exc:
        _show_missing_deps_error(exc)
        sys.exit(1)

    App().run()


if __name__ == "__main__":
    main()
