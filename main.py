"""
Vstupní bod aplikace pro přejmenování výkresů.
První spuštění: automaticky nainstaluje chybějící závislosti (pip) a připraví prostředí.
Při každém startu ověří Python verzi a dostupnost knihoven; při selhání zobrazí srozumitelný dialog.
"""
import sys
import os
import subprocess
import threading
import queue

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(APP_DIR, "requirements.txt")
VERSION_PATH = os.path.join(APP_DIR, "VERSION")
MIN_PYTHON = (3, 10)

# Early HF_HOME — why: musí být před import transformers/huggingface_hub, jinak přednastavené HF_HOME přepsáno (config.py:272)
if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = os.path.abspath(os.path.join(APP_DIR, "models"))

# Early OMP — why: OMP_* musí být před import torch, jinak placebo (config.py:191 nastavuje až po importu)
_cpu_early = os.cpu_count() or 4
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_k, str(_cpu_early))
os.environ.setdefault("KMP_BLOCKTIME", "0")
os.environ.setdefault("MKL_DYNAMIC", "FALSE")
os.environ.setdefault("OMP_DYNAMIC", "FALSE")
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
os.environ.setdefault("KMP_AFFINITY", "granularity=fine,compact,1,0")

# Mapování import_name -> (pip_name, display_name)
REQUIRED_MAP = {
    "torch": ("torch", "PyTorch (torch)"),
    "torchvision": ("torchvision", "TorchVision (torchvision)"),
    "transformers": ("transformers", "Transformers (transformers)"),
    "PIL": ("Pillow", "Pillow (Pillow)"),
    "numpy": ("numpy", "NumPy (numpy)"),
    "openpyxl": ("openpyxl", "OpenPyXL (openpyxl)"),
    "rapidocr_onnxruntime": ("rapidocr_onnxruntime", "RapidOCR (rapidocr_onnxruntime)"),
    "huggingface_hub": ("huggingface_hub", "HuggingFace Hub (huggingface_hub)"),
    "cv2": ("opencv-python", "OpenCV (opencv-python)"),
    "einops": ("einops", "EinOps (einops)"),
    "accelerate": ("accelerate", "Accelerate (accelerate)"),
}

# easyocr je volitelný fallback – neblokuje start, pokud chybí a rapidocr je dostupný
OPTIONAL_MAP = {
    "easyocr": ("easyocr", "EasyOCR (easyocr)"),
}

# File-lock pro paralelní run.bat 2× — why: 2× pip install rozbije site-packages
_BOOTSTRAP_LOCK = os.path.join(APP_DIR, ".bootstrap.lock")


def _acquire_bootstrap_lock() -> bool:
    """Zkusí získat lock pro pip install. Vrátí True pokud získán, False pokud již běží jiná instalace."""
    try:
        # O_EXCL zajistí atomický vznik — pokud existuje, selže
        fd = os.open(_BOOTSTRAP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True  # při chybě raději pokračovat bez locku


def _release_bootstrap_lock() -> None:
    try:
        if os.path.exists(_BOOTSTRAP_LOCK):
            os.remove(_BOOTSTRAP_LOCK)
    except Exception:
        pass


def _get_version() -> str:
    try:
        if os.path.isfile(VERSION_PATH):
            with open(VERSION_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return "unknown"


def _check_python_version():
    if sys.version_info < MIN_PYTHON:
        msg = (
            f"Aplikace vyžaduje Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} nebo novější.\n"
            f"Aktuální verze: {sys.version.split()[0]}\n\n"
            f"Nainstalujte aktuální Python z https://www.python.org/downloads/\n"
            f"a při instalaci zaškrtněte 'Add Python to PATH'."
        )
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Nekompatibilní verze Pythonu", msg)
            r.destroy()
        except Exception:
            print(f"CHYBA: {msg}", file=sys.stderr)
        sys.exit(1)


def _find_missing() -> list[tuple[str, str, str]]:
    """Vrátí seznam (import_name, pip_name, display) pro chybějící povinné závislosti."""
    # why: původně __import__ načítal torch (15s cold-start) i když nic nechybí — find_spec je lehký
    import importlib.util
    missing = []
    for import_name, (pip_name, display) in REQUIRED_MAP.items():
        if importlib.util.find_spec(import_name) is None:
            missing.append((import_name, pip_name, display))
    return missing


def _run_pip_install(requirements_path: str, log_queue: queue.Queue, proc_ref: dict | None = None) -> int:
    """Spustí pip install a streamuje výstup do queue. Vrací exit code."""
    cmd = [sys.executable, "-m", "pip", "install", "-r", requirements_path, "--disable-pip-version-check"]
    log_queue.put(("info", f"Spouštím: {' '.join(cmd)}\n"))
    try:
        # why: bufsize=1 + text=True pro průběžný streaming výstupu do GUI
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        if proc_ref is not None:
            proc_ref["proc"] = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            log_queue.put(("log", line))
        proc.wait()
        if proc_ref is not None:
            proc_ref["proc"] = None
        return proc.returncode
    except FileNotFoundError as e:
        log_queue.put(("error", f"pip nenalezen: {e}\n"))
        return 127
    except Exception as e:
        log_queue.put(("error", f"Chyba při instalaci: {e}\n"))
        return 1


def _show_bootstrap_window(missing: list[tuple[str, str, str]]) -> bool:
    """Zobrazí okno s průběhem automatické instalace. Vrací True pokud úspěch."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    result: dict = {"success": False, "exit_code": 1}

    root = tk.Tk()
    root.title(f"První spuštění – instalace závislostí (v{_get_version()})")
    root.geometry("680x480")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    header = tk.Frame(root, bg="#1976D2", padx=16, pady=12)
    header.pack(fill="x")
    tk.Label(header, text="📦 První spuštění – připravuji prostředí", font=("Segoe UI", 12, "bold"), bg="#1976D2", fg="white").pack(anchor="w")
    tk.Label(header, text="Aplikace sama nainstaluje potřebné knihovny. Prosím nevypínejte počítač.", font=("Segoe UI", 9), bg="#1976D2", fg="white").pack(anchor="w", pady=(4, 0))

    info_frame = tk.Frame(root, padx=16, pady=10)
    info_frame.pack(fill="x")
    missing_text = "\n".join(f"  • {d}" for _, _, d in missing)
    tk.Label(info_frame, text=f"Chybí {len(missing)} knihoven:", font=("Segoe UI", 9, "bold"), fg="#37474F").pack(anchor="w")
    tk.Label(info_frame, text=missing_text, font=("Segoe UI", 9), fg="#C62828", justify="left").pack(anchor="w", pady=(2, 0))
    # Upozornění na velikost (why: torch CUDA + deps reálně ~3 GB + model ~7 GB, ne 200 MB)
    tk.Label(info_frame, text="Instalace může trvat 5–15 minut podle rychlosti internetu (závislosti ~3 GB, model ~7 GB, celkem ~10 GB).", font=("Segoe UI", 8, "italic"), fg="#555").pack(anchor="w", pady=(6, 0))

    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.pack(fill="x", padx=16, pady=(4, 8))
    progress.start(12)

    lbl_status = tk.Label(root, text="Připravuji instalaci…", font=("Segoe UI", 9), fg="#1565C0", anchor="w")
    lbl_status.pack(fill="x", padx=16)

    txt_frame = tk.Frame(root, padx=10, pady=6)
    txt_frame.pack(fill="both", expand=True, padx=10, pady=4)
    txt = tk.Text(txt_frame, font=("Consolas", 8), bg="#263238", fg="#ECEFF1", wrap="word", height=14)
    txt.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(txt_frame, orient="vertical", command=txt.yview)
    scrollbar.pack(side="right", fill="y")
    txt.configure(yscrollcommand=scrollbar.set)
    txt.insert("end", f"Python: {sys.version.split()[0]}  |  {sys.executable}\n")
    txt.insert("end", f"Požadavky: {REQUIREMENTS_PATH}\n\n")

    q: queue.Queue = queue.Queue()

    def append_log(text: str, tag: str = "log"):
        try:
            txt.insert("end", text)
            txt.see("end")
            if "Instaluji" in text or "Collecting" in text:
                lbl_status.config(text=text.strip()[:90])
        except Exception:
            pass

    def poll_queue():
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    append_log(payload)
                elif kind == "info":
                    append_log(payload, "info")
                    lbl_status.config(text=payload.strip()[:90])
                elif kind == "error":
                    append_log(payload, "error")
                elif kind == "done":
                    code = payload
                    progress.stop()
                    if code == 0:
                        lbl_status.config(text="✅ Instalace dokončena – ověřuji…", fg="#2E7D32")
                        append_log("\n✅ Instalace úspěšně dokončena.\n", "info")
                        # Ověření že importy už fungují
                        still_missing = _find_missing()
                        if not still_missing:
                            result["success"] = True
                            result["exit_code"] = 0
                            root.after(1200, root.destroy)
                        else:
                            still = ", ".join(d for _, _, d in still_missing)
                            append_log(f"\n⚠️ Stále chybí: {still}\nZkuste spustit ručně: pip install -r requirements.txt\n", "error")
                            lbl_status.config(text="⚠️ Některé knihovny se nenainstalovaly", fg="#C62828")
                            progress.config(mode="determinate", value=100)
                    else:
                        lbl_status.config(text=f"❌ Instalace selhala (kód {code})", fg="#C62828")
                        append_log(f"\n❌ Instalace selhala s kódem {code}.\nZkontrolujte připojení k internetu a zkuste znovu.\nNebo spusťte ručně:\n  pip install -r requirements.txt\n", "error")
                        progress.config(mode="determinate", value=100)
                        # Ponechat okno otevřené, ať uživatel vidí log
                    return
        except queue.Empty:
            pass
        root.after(80, poll_queue)

    pip_proc_ref: dict = {"proc": None}

    def worker():
        if not os.path.isfile(REQUIREMENTS_PATH):
            q.put(("error", f"Soubor nenalezen: {REQUIREMENTS_PATH}\n"))
            q.put(("done", 1))
            return
        code = _run_pip_install(REQUIREMENTS_PATH, q, pip_proc_ref)
        q.put(("done", code))

    def _on_close():
        # why: daemon pip thread bez handleru zanechá poloviční wheel — ukončit proc
        try:
            proc = pip_proc_ref.get("proc")
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        _release_bootstrap_lock()
        try:
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    root.protocol("WM_DELETE_WINDOW", _on_close)

    threading.Thread(target=worker, daemon=True).start()
    root.after(80, poll_queue)

    # Blokující wait – dokud se okno nezavře
    root.mainloop()

    if not result["success"]:
        # Selhání – zobrazit dialog s možností opakování / kontakt správce
        try:
            r2 = tk.Tk()
            r2.withdraw()
            messagebox.showerror(
                "Instalace se nezdařila",
                "Automatická instalace závislostí se nezdařila.\n\n"
                "Zkontrolujte připojení k internetu a zkuste aplikaci spustit znovu.\n\n"
                "Ruční instalace:\n"
                f"  pip install -r \"{REQUIREMENTS_PATH}\"\n\n"
                f"Log: {os.path.join(APP_DIR, 'rename_drawings.log')}\n"
                "V případě potíží kontaktujte správce.",
            )
            r2.destroy()
        except Exception:
            pass
        return False
    return True


def _check_dependencies_bootstrap():
    """Ověří závislosti; pokud chybí, automaticky je nainstaluje (first-run)."""
    # why: env proměnná umožní vypnout auto-install (offline prostředí)
    if os.environ.get("FINAAL_NO_AUTO_INSTALL") == "1":
        missing = _find_missing()
        if missing:
            msg = (
                "Aplikace nemůže být spuštěna, protože chybí následující knihovny:\n\n"
                + "\n".join(f"  ✗  {d}" for _, _, d in missing)
                + f"\n\nAutomatická instalace je vypnuta (FINAAL_NO_AUTO_INSTALL=1).\n"
                + f"Nainstalujte ručně:\n  pip install -r \"{REQUIREMENTS_PATH}\"\n"
            )
            try:
                import tkinter as tk
                from tkinter import messagebox
                r = tk.Tk(); r.withdraw()
                messagebox.showerror("Chybějící knihovny", msg)
                r.destroy()
            except Exception:
                print(f"CHYBA: {msg}", file=sys.stderr)
            sys.exit(1)
        return

    missing = _find_missing()
    if not missing:
        return

    # File-lock pro paralelní run.bat 2× — why: 2× pip install rozbije site-packages
    if not _acquire_bootstrap_lock():
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showwarning(
                "Instalace již běží",
                "Jiná instance aplikace právě instaluje závislosti.\nVyčkejte dokončení a spusťte znovu.",
            )
            r.destroy()
        except Exception:
            print("Instalace již běží v jiné instanci", file=sys.stderr)
        sys.exit(1)
    try:
        ok = _show_bootstrap_window(missing)
    finally:
        _release_bootstrap_lock()
    if not ok:
        sys.exit(1)

    # Po úspěšné instalaci znovu ověřit
    still = _find_missing()
    if still:
        msg = "Po instalaci stále chybí: " + ", ".join(d for _, _, d in still)
        print(f"CHYBA: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _check_python_version()
    _check_dependencies_bootstrap()

    from config import setup_logging
    setup_logging()

    import tkinter as tk
    from gui import RenameApp

    root = tk.Tk()
    app = RenameApp(root)
    root.mainloop()
