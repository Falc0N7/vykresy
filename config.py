"""
Konfigurační modul pro aplikaci přejmenování výkresů.
Dynamicky zjišťuje parametry reálného hardware (CPU jádra, RAM, GPU VRAM/MPS)
a přizpůsobuje výpočetní parametry pro libovolný počítač.
"""
from __future__ import annotations

import os
import sys
import json
import logging
import ctypes
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")


def _load_dotenv() -> None:
    """Load .env file (key=value) into os.environ if present. No external deps."""
    env_path = os.path.join(APP_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, sep, value = line.partition("=")
                if key and sep:
                    os.environ.setdefault(key.strip(), value.strip())
    except OSError as e:
        logger.debug("Cannot read .env: %s", e)


_load_dotenv()


def get_hardware_specs() -> dict[str, Any]:
    """Zjistí reálné parametry aktuálního hardware (CPU jádra, RAM, GPU/MPS VRAM)."""
    import torch
    cpu_count = os.cpu_count() or 4
    
    # Detekce RAM paměti — why: původně 16.0 fallback + pouze Windows, Linux/macOS vždy 16 GB
    total_ram_gb = 8.0  # realistický default pro kancelářské PC (ne 16)
    if sys.platform == "win32":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total_ram_gb = stat.ullTotalPhys / (1024 ** 3)
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        total_ram_gb = int(parts[1]) / (1024 * 1024)
                        break
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            total_ram_gb = int(out) / (1024 ** 3)
        except Exception:
            pass

    # Detekce GPU/MPS akcelerátoru
    has_gpu = False
    has_mps = False
    gpu_vram_gb = 0.0
    gpu_name = "Není k dispozici"
    try:
        if torch.cuda.is_available():
            has_gpu = True
            try:
                gpu_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "NVIDIA CUDA"
                gpu_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            except Exception:
                gpu_vram_gb = 4.0
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            has_gpu = True
            gpu_name = "Intel XPU"
            gpu_vram_gb = 8.0  # XPU nemá get_device_properties, odhad
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            has_mps = True
            gpu_name = "Apple Silicon (MPS)"
            gpu_vram_gb = total_ram_gb  # MPS shares unified memory with CPU
    except Exception:
        pass

    return {
        "cpu_count": cpu_count,
        "ram_gb": total_ram_gb,
        "has_gpu": has_gpu,
        "has_mps": has_mps,
        "gpu_name": gpu_name,
        "gpu_vram_gb": gpu_vram_gb,
    }


def get_dynamic_hardware_profiles(model_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Dynamicky sestaví profily přesně podle aktuálního hardware a zvoleného VLM modelu."""
    specs = get_hardware_specs()
    cpu_count = specs["cpu_count"]
    ram_gb = specs["ram_gb"]
    has_gpu = specs["has_gpu"]
    gpu_vram = specs["gpu_vram_gb"]

    # Detekce modelu pro optimální rozlišení (why: VisionPsy má nativní 512 + tiling až 2048, jiný tradeoff než SmolVLM 512/2048)
    if model_id is None:
        try:
            _cfg = load_config()
            model_id = _cfg.get("default_model", "")
        except Exception:
            model_id = ""
    is_visionpsy = "visionpsy" in (model_id or "").lower()

    # Turbo parametry — why: původně cpu_count oversubscribe na 32j, io_workers=8 thrashing na HDD/SMB
    # cap na 16 vláken, na 2-4j nechat 1 jádro volné pro OS/myš
    turbo_threads_raw = max(1, min(cpu_count, 16))
    if cpu_count <= 4:
        turbo_threads = max(1, cpu_count - 1)
    else:
        turbo_threads = turbo_threads_raw
    turbo_io = min(4, max(2, cpu_count // 4))  # max 4 místo 8, méně thrashing na HDD/SMB
    if ram_gb < 8.0:
        turbo_io = 2

    # Eco parametry — why: na 2j původně turbo 2 vs eco 1 žádný rozdíl, eco vždy 1 na malých strojích
    eco_threads = 1 if cpu_count <= 4 else max(1, min(2, cpu_count // 4))

    # Rozlišení podle VRAM / RAM + modelu (why: VisionPsy float32 OOM na 4GB VRAM, původní větve dávaly stejné 1024/1280 pro 4GB i 24GB)
    if is_visionpsy:
        # VisionPsy: 512 native, float32 → OOM na <6GB
        if has_gpu and gpu_vram >= 6.0:
            turbo_dim = 1024  # 2x2 tiles, optimální pro 6GB+
        elif has_gpu:
            turbo_dim = 768  # <6GB VRAM → 768 aby nepadlo OOM (float32)
        else:
            turbo_dim = 768 if ram_gb < 12.0 else 1024
    else:
        if has_gpu and gpu_vram >= 6.0:
            turbo_dim = 1280
        elif has_gpu:
            turbo_dim = 1024  # <6GB VRAM → 1024 místo 1280 aby nepadlo OOM
        else:
            turbo_dim = 1280 if ram_gb >= 12.0 else 1024

    # Priorita — why: HIGH (0x80) na 2j vyhladoví myš, na malých strojích použít ABOVE_NORMAL
    turbo_priority = 0x00008000 if cpu_count <= 4 else 0x00000080  # ABOVE_NORMAL vs HIGH
    eco_priority = 0x00004000  # BELOW_NORMAL

    return {
        "turbo": {
            "name": "🚀 Výkonný",
            "short_name": "Výkonný",
            "description": "Rychlejší zpracování, vyšší zatížení PC.",
            "cpu_threads": turbo_threads,
            "win_priority": turbo_priority,
            "max_image_dim": turbo_dim,
            "inter_file_pause_s": 0.0,
            "io_workers": turbo_io,
        },
        "eco": {
            "name": "🌱 Úsporný",
            "short_name": "Úsporný",
            "description": "Pomalejší zpracování, PC zůstává plynulý.",
            "cpu_threads": eco_threads,
            "win_priority": eco_priority,
            "max_image_dim": (768 if is_visionpsy else 1024),
            "inter_file_pause_s": 0.05,
            "io_workers": 1,
        },
    }


# Výchozí hodnoty
DEFAULTS = {
    "hf_home": "./models",
    "default_model": "HuggingFaceTB/SmolVLM-500M-Instruct",
    "paper_format": "A4",
    "hardware_profile": "turbo",
    "device": "auto",
}


def get_detected_devices() -> list[tuple[str, str, bool]]:
    """
    Detekuje dostupná výpočetní zařízení.
    Vrátí seznam trojic: (device_key, display_label, is_available)
    """
    import torch
    devices = []
    has_cuda = torch.cuda.is_available()
    if has_cuda:
        gpu_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "NVIDIA CUDA"
        devices.append(("cuda", f"⚡ Grafická karta (GPU: {gpu_name})", True))
    elif hasattr(torch, "xpu") and torch.xpu.is_available():
        devices.append(("xpu", "⚡ Grafická karta (Intel XPU)", True))
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append(("mps", "🍎 Apple Silicon (MPS)", True))
    else:
        devices.append(("cuda", "⚡ Grafická karta (GPU: Není detekována)", False))

    devices.append(("cpu", "💻 Procesor (CPU)", True))
    return devices


def load_config() -> dict[str, Any]:
    """Načte konfiguraci z config.json. Pokud neexistuje, vrátí výchozí hodnoty."""
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update(saved)
            logger.info("Konfigurace načtena z %s", CONFIG_FILE)
        except Exception as e:
            logger.warning("Nelze načíst konfiguraci z %s: %s", CONFIG_FILE, e)
    return config


def save_config(config: dict) -> None:
    """Uloží konfiguraci do config.json pro příští spuštění — why: atomicky (tmp+fsync+replace) proti corrupt při výpadku."""
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, CONFIG_FILE)
        logger.info("Konfigurace uložena do %s", CONFIG_FILE)
    except Exception as e:
        logger.warning("Nelze uložit konfiguraci: %s", e)


def apply_hardware_profile(profile_key: str = "turbo") -> dict[str, Any]:
    """
    Aplikuje nastavení vybraného hardwarového profilu:
    - Nastaví proměnné prostředí pro vlákna (OpenMP, MKL, PyTorch).
    - Nastaví prioritu procesu ve Windows.
    Vrátí slovník parametrů profilu.
    """
    profiles = get_dynamic_hardware_profiles()
    if profile_key not in profiles:
        profile_key = "turbo"
    
    profile = profiles[profile_key]
    threads = profile["cpu_threads"]
    
    # Nastavení systémových proměnných pro C/C++ backendy
    thread_str = str(threads)
    os.environ["OMP_NUM_THREADS"] = thread_str
    os.environ["MKL_NUM_THREADS"] = thread_str
    os.environ["OPENBLAS_NUM_THREADS"] = thread_str
    os.environ["NUMEXPR_NUM_THREADS"] = thread_str
    os.environ["VECLIB_MAXIMUM_THREADS"] = thread_str
    os.environ["KMP_BLOCKTIME"] = "0"
    os.environ["MKL_DYNAMIC"] = "FALSE"
    os.environ["OMP_DYNAMIC"] = "FALSE"
    # CPU optimalizace: vlákna nečekají busy-loop (šetří CPU cykly pro inference)
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
    # Lepší cache locality – váže vlákna na fyzická jádra
    os.environ["KMP_AFFINITY"] = "granularity=fine,compact,1,0"

    # Nastavení priority procesu na Windows
    if sys.platform == "win32":
        try:
            priority_val = profile["win_priority"]
            current_proc = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(current_proc, priority_val)
            logger.info("Nastavena priorita procesu Windows: 0x%X (Profil: %s)", priority_val, profile_key)
        except Exception as e:
            logger.warning("Nelze nastavit prioritu procesu Windows: %s", e)

    logger.info("Aplikován hardwarový profil '%s' (CPU vláken: %d)", profile_key, threads)
    return profile


def setup_logging() -> None:
    """Inicializuje logování do souboru i konzole (odolné vůči zámkům souborů ve Windows)."""
    log_file = os.path.join(APP_DIR, "rename_drawings.log")
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    if not root_logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        
        from logging.handlers import RotatingFileHandler
        
        class SafeRotatingFileHandler(RotatingFileHandler):
            def doRollover(self):
                try:
                    if self.stream:
                        self.stream.close()
                        self.stream = None
                    super().doRollover()
                except (PermissionError, OSError):
                    # Ve Windows při zamčení souboru jiným vláknem bezpečně pokračovat
                    pass

        try:
            fh = SafeRotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=2, encoding="utf-8", delay=True)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            root_logger.addHandler(fh)
        except Exception as e:
            # why: tiché selhání by skrylo chybějící logování — alespoň varování na stderr
            print(f"Varování: Nelze vytvořit log soubor {log_file}: {e}", file=sys.stderr)
        
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root_logger.addHandler(ch)


def init_config() -> None:
    """Initialize HF_HOME from config/env. Called at import time; safe to re-call."""
    if "HF_HOME" not in os.environ:
        _config = load_config()
        _hf_home = _config.get("hf_home", DEFAULTS["hf_home"])
        if not os.path.isabs(_hf_home):
            _hf_home = os.path.join(APP_DIR, _hf_home)
        os.environ["HF_HOME"] = os.path.abspath(_hf_home)


# why: HF_HOME musí být nastavena před importem transformers/huggingface_hub
init_config()
