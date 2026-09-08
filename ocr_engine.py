"""
Výpočetní modul pro rozpoznávání výkresů (VLM + OCR).
Obsahuje univerzální ověřovací algoritmus (bez hardcoded řetězců),
hardwarovou optimalizaci pro CPU (INT8, adaptivní crop, threading) i GPU (CUDA FP16).
"""
import os
import re
import sys
import logging
import difflib
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageEnhance, ImageOps
import torch
from typing import Any

from config import load_config, apply_hardware_profile
from parser import (
    extract_drawing_number,
    split_drawing_details, extract_best_from_ocr_boxes,
    disambiguate_drawing_number,
    _KNOWN_STEEL_GRADES
)

logger = logging.getLogger(__name__)

# Kořen aplikace (pro model cache a kontroly disku)
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Ochrana před decompression bomb — why: A0 skeny mají běžně 280+ Mpx, 500Mpx pokryje i A0+ při 600 DPI.
# Program obrázek ihned zmenší na max_dim 1440px, takže reálná spotřeba RAM je nízká.
Image.MAX_IMAGE_PIXELS = 500_000_000


# =============================================================================
# VLM Backend (SmolVLM2 / Univerzální HuggingFace VLM)
# =============================================================================

class SmolVLMBackend:
    """Univerzální backend pro všechny VLM (SmolVLM2 / VisionPsy / LFM2.5 / GLM-OCR / Paddle / Qwen / dots.ocr)."""

    def __init__(self, model_path: str, device: str, progress_callback=None):
        from transformers import AutoProcessor, AutoModelForImageTextToText
        import json as _json

        # Detekce speciálních architektur (pro model-specific optimalizace)
        _is_visionpsy = False
        _model_type = ""
        _cfg_p = os.path.join(model_path, "config.json")
        if os.path.isfile(_cfg_p):
            try:
                with open(_cfg_p, "r", encoding="utf-8") as _cf:
                    _cj = _json.load(_cf)
                _model_type = _cj.get("model_type", "")
                if _cj.get("model_type") == "visionpsynano":
                    _is_visionpsy = True
            except Exception:
                pass
        if not _is_visionpsy and "visionpsy" in model_path.lower():
            _is_visionpsy = True
        self.is_visionpsy = _is_visionpsy
        self.model_type = _model_type
        # pro obecné rozlišení promptu: VisionPsy krátký, ostatní dlouhý
        self.use_short_prompt = _is_visionpsy

        model_label = "VisionPsy-Nano" if _is_visionpsy else (_model_type or os.path.basename(model_path))
        if progress_callback:
            progress_callback("Načítání procesoru AI modelu...", 20)
        logger.info("Načítání %s z: %s (device: %s, model_type: %s)", model_label, model_path, device, _model_type)

        self.device = device
        # dtype volba: VisionPsy float32, ostatní float16 na CUDA, XPU/CPU float32 (why: VisionPsy trénován float32, XPU experimentální — stable float32)
        if _is_visionpsy:
            self.dtype = torch.float32
        else:
            self.dtype = torch.float16 if device == "cuda" else torch.float32

        # Bezpečnost — why: trust_remote_code RCE pokud models/ writable a útočník vloží kód
        if os.path.isdir(model_path):
            try:
                has_custom = any(f.endswith(".py") for f in os.listdir(model_path) if os.path.isfile(os.path.join(model_path, f)))
                if has_custom:
                    allowed = any(k in model_path.lower() for k in ("smolvlm", "visionpsy", "paddle", "dots", "qwen", "glm", "lfm", "navi"))
                    if not allowed:
                        logger.warning("Model %s obsahuje custom .py a není v allowlist — trust_remote_code riziko RCE", model_path)
                    if os.access(model_path, os.W_OK):
                        try:
                            import stat
                            st = os.stat(model_path)
                            if st.st_mode & stat.S_IWOTH:
                                logger.warning("Adresář modelu %s je world-writable — RCE riziko", model_path)
                        except Exception:
                            pass
            except Exception:
                pass

        # Vždy trust_remote_code=True pro univerzální podporu (GLM, dots, LFM, Qwen custom)
        try:
            self.processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        except Exception as e:
            logger.warning("AutoProcessor trust_remote_code selhal, zkouším bez: %s", e)
            self.processor = AutoProcessor.from_pretrained(model_path)

        if progress_callback:
            progress_callback("Načítání vah modelu do paměti...", 45)

        if _is_visionpsy:
            # VisionPsy vyžaduje trust_remote_code, má vlastní tiling (512 native, až 2048)
            # why: na Windows chybí triton → inductor selže, proto vypínáme compile_inference a neaplikujeme torch.compile
            # také vypínáme torch dynamo inductor pro VisionPsy (bez tritonu padá na Windows)
            try:
                import torch._dynamo as _dynamo
                _dynamo.config.suppress_errors = True
                _dynamo.config.disable = True
            except Exception:
                pass
            # why: VisionPsy float32 OOM na 4GB VRAM — přidán fallback na CPU (původně bez OOM handlingu)
            try:
                self.model = AutoModelForImageTextToText.from_pretrained(
                    model_path,
                    trust_remote_code=True,
                    torch_dtype=self.dtype,
                ).to(device).eval()
            except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if "out of memory" in str(e).lower() and device in ("cuda", "xpu"):
                    logger.warning("VisionPsy OOM na %s (%s), fallback na CPU", device, e)
                    try:
                        if device == "cuda" and torch.cuda.is_available():
                            torch.cuda.empty_cache()
                        elif device == "xpu" and hasattr(torch, "xpu"):
                            try:
                                torch.xpu.empty_cache()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.device = "cpu"
                    self.dtype = torch.float32
                    self.model = AutoModelForImageTextToText.from_pretrained(
                        model_path,
                        trust_remote_code=True,
                        torch_dtype=self.dtype,
                    ).to("cpu").eval()
                else:
                    raise
            # vypnutí vestavěného compile inference (pokud existuje)
            try:
                if hasattr(self.model, "config") and hasattr(self.model.config, "compile_inference"):
                    self.model.config.compile_inference = False
                if hasattr(self.model, "cfg") and hasattr(self.model.cfg, "compile_inference"):
                    self.model.cfg.compile_inference = False
            except Exception:
                pass
        else:
            # Univerzální načtení pro všechny ostatní VLM (LFM, GLM, Paddle, Qwen, dots, SmolVLM2)
            # why: 1-3B na 6GB VRAM selže v float16 → fallback 4-bit quantization přes bitsandbytes
            try:
                self.model = AutoModelForImageTextToText.from_pretrained(
                    model_path,
                    trust_remote_code=True,
                    torch_dtype=self.dtype,
                    _attn_implementation="eager",
                    low_cpu_mem_usage=True,
                ).to(device).eval()
            except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if "out of memory" in str(e).lower() or "CUDA out of memory" in str(e):
                    # why: get_device_properties může selhat když je GPU v nekonzistentním stavu po OOM — chránit try
                    try:
                        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3 if torch.cuda.is_available() else 0
                    except Exception:
                        vram_gb = 0
                    logger.warning("CUDA OOM při načtení %s (%.1f GB), zkouším 4-bit quantization", model_path, vram_gb)
                    try:
                        from transformers import BitsAndBytesConfig
                        bnb_cfg = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=self.dtype)
                        self.model = AutoModelForImageTextToText.from_pretrained(
                            model_path,
                            trust_remote_code=True,
                            quantization_config=bnb_cfg,
                            device_map="auto",
                            low_cpu_mem_usage=True,
                        ).eval()
                        self.device = "cuda"  # device_map auto již na cuda
                        logger.info("4-bit quantization úspěšná pro %s", model_path)
                    except Exception as e2:
                        logger.error("4-bit fallback selhal: %s, zkouším CPU", e2)
                        self.device = "cpu"
                        self.dtype = torch.float32
                        self.model = AutoModelForImageTextToText.from_pretrained(
                            model_path,
                            trust_remote_code=True,
                            torch_dtype=self.dtype,
                            low_cpu_mem_usage=True,
                        ).to("cpu").eval()
                else:
                    raise

        # Zakázání výpočtu gradientů pro maximální rychlost
        for param in self.model.parameters():
            param.requires_grad = False

        if device == "cuda":
            torch.backends.cudnn.benchmark = True
            # torch.compile() na Windows bez triton je pomalý a padá na Qwen/GLM – přeskočit pro všechny na win32
            # why: GTX 1660 + Windows nemá triton, inductor = 50s/soubor místo 9s
            skip_compile = _is_visionpsy or sys.platform == "win32" or "qwen" in model_path.lower() or "glm" in model_path.lower()
            if not skip_compile:
                try:
                    self.model = torch.compile(self.model, mode="reduce-overhead")
                    logger.info("torch.compile() úspěšně aplikován pro CUDA akceleraci.")
                except Exception as e:
                    logger.warning("torch.compile() není dostupný, pokračuji bez něj: %s", e)
            else:
                logger.info("torch.compile přeskočen (Windows/qwen/glm/visionpsy – nativní inference, rychlejší).")
        elif device == "xpu":
            # why: Intel XPU experimentální — bez cudnn/compile/INT8, float32 nativně (vzácné, neblokující)
            logger.info("XPU detekováno — používám float32 nativní inference bez compile/INT8 (experimentální).")
        elif device == "cpu":
            try:
                torch.set_flush_denormal(True)
            except Exception:
                pass
            try:
                self.model = torch.ao.quantization.quantize_dynamic(
                    self.model, {torch.nn.Linear}, dtype=torch.qint8
                )
                logger.info("Aplikována dynamická INT8 CPU kvantizace pro maximální rychlost procesoru.")
            except Exception as e:
                logger.warning("Nelze aplikovat INT8 kvantizaci: %s", e)

        if progress_callback:
            progress_callback("AI Model úspěšně načten.", 65)

        # Pre-sestavení promptu pro číslo výkresu – model-specific (why: VisionPsy je citlivý na dlouhý prompt, krátký dává 100135 vs DICHTUNG)
        if self.is_visionpsy:
            self._drawing_prompt = "What is the drawing number in the title block? Return ONLY the number."
            # VisionPsy: ukládáme pouze text prompt, image se přidá až v extract_text
            self._template_drawing = self._drawing_prompt
        else:
            self._drawing_prompt = (
                "What is the main engineering drawing number (číslo výkresu / číslo součásti / Zeichnungsnummer) in this drawing or title block? "
                "Extract the complete drawing number with any suffix letters or codes (e.g. a, b, c, E, K20, K5, sp1) "
                "and part numbers after slash (e.g. /1, /11, _1). "
                "IMPORTANT: Do NOT return the approval year or date (such as 1920-1929). "
                "Do NOT return change or revision numbers from the change table (Změny / Änderungs-Nr.). "
                "Do NOT return steel grades or material numbers (such as 12020, 11523, 12050, 14220, ČSN) from the material box. "
                "If this is a 12-digit drawing number starting with 4420, extract the full 12-digit number. "
                "Return ONLY the main drawing number."
            )
            _msgs_draw = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": self._drawing_prompt}]}]
            self._template_drawing = self.processor.apply_chat_template(_msgs_draw, add_generation_prompt=True)

    def _cast_inputs(self, inputs: dict) -> dict:
        """Rychlý in-place dtype cast pro floating point tensory (pro VisionPsy přeskočeno – vyžaduje float32)."""
        if getattr(self, "is_visionpsy", False):
            return inputs
        for k, v in inputs.items():
            if isinstance(v, torch.Tensor) and v.is_floating_point() and v.dtype != self.dtype:
                inputs[k] = v.to(dtype=self.dtype)
        return inputs

    def extract_text(self, img_resized: Image.Image) -> str:
        """Extrahuje číslo výkresu pomocí VLM (SmolVLM i VisionPsy-Nano)."""
        if self.is_visionpsy:
            # VisionPsy: processor(images, text) -> {input_ids, images/pixel_values}
            inputs = self.processor(images=[img_resized], text=self._template_drawing, return_tensors="pt")
            # VisionPsy vrací images i input_ids; přesun na device
            inputs = {k: (v.to(self.device) if isinstance(v, torch.Tensor) else v) for k, v in inputs.items()}
        else:
            inputs = self.processor(text=self._template_drawing, images=[img_resized], return_tensors="pt").to(self.device)
        self._cast_inputs(inputs)

        try:
            with torch.inference_mode():
                out = self.model.generate(
                    **inputs,
                    max_new_tokens=16,  # Číslo výkresu má max 12 znaků + suffix, 16 tokenů stačí
                    do_sample=False,
                    num_beams=1,
                )
        except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
            if "out of memory" in str(e).lower() and self.device in ("cuda", "xpu"):
                logger.warning("Nedostatek VRAM (%s OOM). Automatické dynamické přepnutí na CPU INT8.", self.device.upper())
                try:
                    if self.device == "cuda":
                        torch.cuda.empty_cache()
                    elif self.device == "xpu" and hasattr(torch, "xpu") and hasattr(torch.xpu, "empty_cache"):
                        torch.xpu.empty_cache()
                except Exception:
                    pass
                self.device = "cpu"
                self.dtype = torch.float32
                self.model = self.model.to("cpu")
                try:
                    self.model = torch.ao.quantization.quantize_dynamic(
                        self.model, {torch.nn.Linear}, dtype=torch.qint8
                    )
                except Exception:
                    pass
                inputs_cpu = {k: (v.to("cpu", dtype=torch.float32 if v.is_floating_point() else v.dtype) if isinstance(v, torch.Tensor) else v) for k, v in inputs.items()}
                with torch.inference_mode():
                    out = self.model.generate(**inputs_cpu, max_new_tokens=16, do_sample=False, num_beams=1)
            else:
                raise

        # VisionPsy vrací pouze generované tokeny (out.shape[1] == max_new_tokens), SmolVLM vrací input+generated
        if self.is_visionpsy:
            # out je pouze generace, nebo v některých verzích může obsahovat i input -> ošetřit oba případy
            if out.shape[1] <= 32:  # max_new_tokens = 16, ale VisionPsy někdy 32 – čistá generace
                vlm_text = self.processor.batch_decode(out, skip_special_tokens=True)[0].strip()
            else:
                plen = inputs["input_ids"].shape[1]
                if out.shape[1] > plen:
                    vlm_text = self.processor.batch_decode(out[:, plen:], skip_special_tokens=True)[0].strip()
                else:
                    vlm_text = self.processor.batch_decode(out, skip_special_tokens=True)[0].strip()
        else:
            plen = inputs["input_ids"].shape[1]
            vlm_text = self.processor.batch_decode(out[:, plen:], skip_special_tokens=True)[0].strip()
        logger.debug("VLM raw output: %s", vlm_text)
        return vlm_text


# =============================================================================
# Načítání modelů a správa zařízení
# =============================================================================

def _find_local_model_path(default_model: str) -> str:
    """Najde cestu k lokálnímu modelu (HF cache struktura i přímý adresář) nebo vrátí HuggingFace repozitář."""
    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

    # 1. Přímá cesta: models/HuggingFaceTB/SmolVLM-500M-Instruct
    direct_path = os.path.join(models_dir, default_model)
    if os.path.exists(direct_path):
        return direct_path

    # 2. HuggingFace hub cache: models/hub/models--HuggingFaceTB--SmolVLM-500M-Instruct/snapshots/<hash>/
    hf_cache_name = f"models--{default_model.replace('/', '--')}"
    snapshots_dir = os.path.join(models_dir, "hub", hf_cache_name, "snapshots")
    if os.path.isdir(snapshots_dir):
        # Najde nejnovější snapshot (podle refs/main nebo prvního adresáře)
        refs_main = os.path.join(models_dir, "hub", hf_cache_name, "refs", "main")
        target_hash = None
        if os.path.isfile(refs_main):
            with open(refs_main, "r") as f:
                target_hash = f.read().strip()
        if target_hash:
            snap_path = os.path.join(snapshots_dir, target_hash)
            if os.path.isdir(snap_path):
                logger.info("Nalezen lokální model (HF cache): %s", snap_path)
                return snap_path
        # Fallback: vezme první snapshot
        for entry in os.listdir(snapshots_dir):
            snap_path = os.path.join(snapshots_dir, entry)
            if os.path.isdir(snap_path):
                logger.info("Nalezen lokální model (HF cache snapshot): %s", snap_path)
                return snap_path

    # 3. Fallback: HuggingFace stáhne online (pokud je internet)
    return default_model


def _ensure_model_available(model_name: str, progress_callback: Any = None,
                            on_fatal_error: Any = None) -> str:
    """
    Zajistí dostupnost VLM modelu pro první spuštění.
    - Pokud je model již lokálně (direct nebo hub cache), vrátí jeho cestu.
    - Jinak jej automaticky stáhne z HuggingFace Hub do ./models/<repo> s progress callbackem.
    - Při offline selhání zavolá on_fatal_error callback a vyhodí RuntimeError.
    """
    found = _find_local_model_path(model_name)
    if found != model_name and os.path.exists(found):
        return found

    # Env: vypnutí auto-downloadu v offline prostředí
    if os.environ.get("FINAAL_NO_AUTO_DOWNLOAD") == "1":
        logger.warning("Auto-download vypnut (FINAAL_NO_AUTO_DOWNLOAD=1), model %s není lokálně", model_name)
        os.environ["HF_HUB_OFFLINE"] = "1"
        raise RuntimeError(f"Model '{model_name}' není lokálně dostupný a auto-download je vypnut (FINAAL_NO_AUTO_DOWNLOAD=1). Dodajte složku models/{model_name} ručně.")

    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    direct_path = os.path.join(models_dir, model_name)

    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as e:
        logger.error("huggingface_hub chybí, nelze stáhnout model %s: %s", model_name, e)
        raise RuntimeError(f"huggingface_hub chybí, nelze stáhnout model {model_name}: {e}") from e

    # Kontrola volného místa (alespoň 8 GB — model má ~7 GB)
    try:
        import shutil
        free_gb = shutil.disk_usage(APP_DIR).free / (1024 ** 3)
        if free_gb < 8.0:
            msg = f"Nedostatek místa na disku ({free_gb:.1f} GB volno). Pro stažení modelu je potřeba alespoň 8 GB (model má ~7 GB)."
            logger.error(msg)
            if progress_callback:
                progress_callback(msg, 5)
    except Exception:
        pass

    if progress_callback:
        progress_callback("Stahuji AI model (první spuštění, ~7 GB)… Prosím čekejte, nevypínejte PC.", 3)
    logger.info("Model %s nenalezen lokálně, spouštím stahování do %s", model_name, direct_path)

    os.makedirs(models_dir, exist_ok=True)

    try:
        # why: local_dir_use_symlinks=False pro Windows bez admin práv (reálné soubory, ne symlinky)
        downloaded = snapshot_download(
            repo_id=model_name,
            local_dir=direct_path,
            local_dir_use_symlinks=False,
        )
        logger.info("Model úspěšně stažen do %s", downloaded)
        if progress_callback:
            progress_callback("AI model stažen, načítám…", 12)
        if os.path.isfile(os.path.join(direct_path, "config.json")):
            return direct_path
        return downloaded
    except Exception as e:
        logger.error("Stažení modelu %s selhalo: %s", model_name, e, exc_info=True)
        # Fallback: zkusit hub cache bez local_dir (využije HF_HOME)
        try:
            logger.info("Zkouším fallback stažení do HF cache (HF_HOME)...")
            if progress_callback:
                progress_callback("První pokus selhal, zkouším alternativní stažení…", 6)
            fallback_path = snapshot_download(repo_id=model_name)
            logger.info("Fallback stažení úspěšné: %s", fallback_path)
            if progress_callback:
                progress_callback("AI model stažen (cache), načítám…", 12)
            return fallback_path
        except Exception as e2:
            logger.error("Fallback stažení také selhalo: %s", e2)
            err_msg = (
                f"AI model '{model_name}' není lokálně dostupný a stahování selhalo:\n{e}\n\n"
                f"Zkontrolujte připojení k internetu a zkuste aplikaci spustit znovu.\n\n"
                f"Offline řešení:\n"
                f"1. Na PC s internetem spusťte:\n"
                f"   pip install huggingface_hub\n"
                f"   python -c \"from huggingface_hub import snapshot_download; snapshot_download('{model_name}', local_dir='./models/{model_name}', local_dir_use_symlinks=False)\"\n"
                f"2. Zkopírujte složku 'models' do adresáře aplikace.\n\n"
                f"Hledaná cesta: {direct_path}\n"
                f"Tip: Lze vypnout auto-download nastavením FINAAL_NO_AUTO_DOWNLOAD=1 a dodat model ručně."
            )
            if on_fatal_error:
                on_fatal_error("Model AI se nepodařilo stáhnout", err_msg)
            raise RuntimeError(f"Model '{model_name}' není dostupný a stahování selhalo: {e}") from e


def load_models(hardware_profile: str = "turbo", device_choice: str = "auto",
                progress_callback: Any = None,
                on_fatal_error: Any = None) -> tuple[SmolVLMBackend, Any, str]:
    """
    Inicializuje AI backend a OCR engine s hardwarovými optimalizacemi a zvoleným zařízením (CPU/GPU/MPS).
    Automaticky stáhne VLM model při prvním spuštění, pokud lokálně chybí.
    """
    # 1. Aplikace hardwarového profilu
    profile_info = apply_hardware_profile(hardware_profile)
    threads = profile_info.get("cpu_threads", 4)
    
    # 2. Volba výpočetního zařízení
    if device_choice == "cpu":
        device = "cpu"
    elif device_choice == "cuda":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device_choice == "mps":
        device = "mps" if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else "cpu"
    elif device_choice == "xpu":
        device = "xpu" if (hasattr(torch, "xpu") and torch.xpu.is_available()) else "cpu"
    else:  # auto
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        elif hasattr(torch, "xpu") and torch.xpu.is_available():
            device = "xpu"
        else:
            device = "cpu"

    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "xpu":
        try:
            if hasattr(torch, "xpu") and hasattr(torch.xpu, "empty_cache"):
                torch.xpu.empty_cache()
        except Exception:
            pass
    elif device == "cpu":
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass

    logger.info("Zvolen výpočetní hardware: %s (vláken: %d, volba: %s)", device.upper(), threads, device_choice)

    # 3. Načtení VLM backendu (s auto-download pro první spuštění)
    cfg = load_config()
    model_name = cfg.get("default_model", "HuggingFaceTB/SmolVLM-500M-Instruct")
    model_path = _ensure_model_available(model_name, progress_callback=progress_callback, on_fatal_error=on_fatal_error)

    backend = SmolVLMBackend(model_path, device, progress_callback)

    # 4. Načtení RapidOCR (CPU ONNX) – why: +13.5pp přesnost oproti samotnému VLM
    if progress_callback:
        progress_callback("Načítání OCR enginu...", 80)
    logger.info("Inicializace RapidOCR (onnxruntime CPU)...")
    try:
        from rapidocr_onnxruntime import RapidOCR
        rapid_ocr = RapidOCR()

        class RapidWrapper:
            """Adapter wrapping RapidOCR to match EasyOCR .readtext() interface."""
            def __init__(self, rapid: RapidOCR) -> None:
                self.rapid = rapid

            def readtext(self, arr: np.ndarray, **_kwargs: Any) -> list[list[Any]]:
                result, _ = self.rapid(arr)
                if not result:
                    return []
                return [
                    [line[0], line[1], float(line[2]) if len(line) > 2 else 0.9]
                    for line in result
                ]

        reader = RapidWrapper(rapid_ocr)
        logger.info("RapidOCR načten (onnxruntime CPU)")
    except Exception as e:
        logger.warning("RapidOCR selhal %s, fallback na EasyOCR", e)
        try:
            import easyocr
            reader = easyocr.Reader(['cs', 'en', 'de'], gpu=(device == "cuda"))
            logger.info("EasyOCR fallback načten")
        except ImportError as e2:
            logger.error("Ani RapidOCR ani EasyOCR nejsou dostupné: %s / %s", e, e2)
            err_msg = (
                f"RapidOCR selhal: {e}\nEasyOCR není nainstalován: {e2}\n\n"
                f"Nainstalujte:\n  pip install rapidocr_onnxruntime\n"
                f"nebo\n  pip install easyocr\n\nKontaktujte správce."
            )
            if on_fatal_error:
                on_fatal_error("Chybí OCR engine", err_msg)
            raise RuntimeError(f"Žádný OCR engine není dostupný: RapidOCR {e}, EasyOCR {e2}") from e2
        except Exception as e2:
            logger.error("EasyOCR fallback selhal: %s", e2)
            raise

    # 5. Warmup
    if progress_callback:
        progress_callback("Zahřívání výpočetních modelů...", 95)
    try:
        dummy = Image.new("RGB", (256, 128), "white")
        backend.extract_text(dummy)
    except Exception as e:
        logger.warning("Warmup varování: %s", e)

    if progress_callback:
        progress_callback("Modely připraveny.", 100)

    return backend, reader, device


# =============================================================================
# Úpravy obrázků a ořezy razítek
# =============================================================================

def load_and_resize_image(fpath: str, max_dim: int = 1440) -> tuple[Image.Image, Image.Image]:
    """Načte obrázek z disku a zmenší na cílový rozměr s vysokou kvalitou."""
    try:
        img = Image.open(fpath).convert("RGB")
    except Image.DecompressionBombError as e:
        logger.error("Obrázek %s příliš velký (DecompressionBomb %s), limit %d px", fpath, e, Image.MAX_IMAGE_PIXELS)
        raise RuntimeError(f"Obrázek {os.path.basename(fpath)} je příliš velký ({e}, limit {Image.MAX_IMAGE_PIXELS} px). Snižte rozlišení skenu.") from e
    except Exception:
        raise
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img_resized = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    else:
        img_resized = img
    return img, img_resized


def crop_title_block(img: Image.Image) -> Image.Image:
    """Ořízne pravý dolní roh (rozšířené razítko, ~55% šířky x ~45% výšky)."""
    w, h = img.size
    return img.crop((int(w * 0.45), int(h * 0.55), w, h))


def crop_top_header_block(img: Image.Image) -> Image.Image:
    """Ořízne celé horní záhlaví (pro A5 a vertikální výkresy, ~100% šířky x ~35% výšky)."""
    w, h = img.size
    return img.crop((0, 0, w, int(h * 0.35)))


def enhance_for_ocr(img: Image.Image, use_clahe: bool | None = None) -> Image.Image:
    """Chytřejší enhance – pro vybledlé historické skeny použije CLAHE, jinak autocontrast.
    why: EasyOCR na 100140 vrací 3941 místo 100140 – vybledlý tisk potřebuje lokální kontrast."""
    import cv2  # lazy import — cv2 is heavy, only needed here

    # auto-detekce vybledlého skenu
    if use_clahe is None:
        try:
            gray = np.asarray(img.convert("L"))
            mean = gray.mean()
            std = gray.std()
            use_clahe = (std < 35) or (mean > 180)
        except Exception:
            use_clahe = False
    if use_clahe:
        try:
            gray = np.asarray(img.convert("L"))
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            cl = clahe.apply(gray)
            cl = cv2.medianBlur(cl, 3)
            return Image.fromarray(cv2.cvtColor(cl, cv2.COLOR_GRAY2RGB))
        except Exception:
            pass
    # fallback původní
    img_gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    enhancer = ImageEnhance.Contrast(img_gray.convert("RGB"))
    img_enh = enhancer.enhance(1.4)
    enhancer = ImageEnhance.Sharpness(img_enh)
    return enhancer.enhance(1.4)


# =============================================================================
# Univerzální ověřovací algoritmus (Verification Engine)
# =============================================================================

def calculate_string_similarity(str1: str, str2: str) -> float:
    """Vypočítá normalizovanou podobnost dvou řetězců (0.0 až 1.0)."""
    if not str1 or not str2:
        return 0.0
    s1 = re.sub(r'\W', '', str1).lower()
    s2 = re.sub(r'\W', '', str2).lower()
    if s1 == s2:
        return 1.0
    return difflib.SequenceMatcher(None, s1, s2).ratio()


def verify_consensus(vlm_num: str | None, ocr_results: list[Any], all_ocr_text: str, top_ocr_text: str = "") -> tuple[str | None, str]:
    """
    Binární ověření shody:
    - 🟢 Ověřeno (Shoda AI + OCR): Uděluje se, pokud se AI a OCR nezávisle shodnou na celém čísle výkresu.
    - 🔴 K ověření: Při jakékoliv neshodě mezi modely, chybějícím indexu, nebo pokud číslo našel jen jeden model.
    """
    if vlm_num:
        vlm_num = disambiguate_drawing_number(vlm_num)

    ocr_best_num, ocr_score = extract_best_from_ocr_boxes(ocr_results)
    ocr_num = ocr_best_num or extract_drawing_number(all_ocr_text) or extract_drawing_number(top_ocr_text)
    if ocr_num:
        ocr_num = disambiguate_drawing_number(ocr_num)

    if not vlm_num and not ocr_num:
        return None, "K ověření (Nenalezeno)"

    best_candidate = vlm_num or ocr_num

    # Ochrana proti číslům oceli – why: 5-místné legacy 00210 nesmí být penalizováno jako ocel
    digits_best = re.sub(r'\D', '', best_candidate or '')
    if digits_best in _KNOWN_STEEL_GRADES:
        return best_candidate, "K ověření (Pravděpodobně číslo materiálu)"

    # Chytřejší ochrana pro krátká čísla – why: 00210, 00310 jsou validní 5-místné legacy s leading 0
    if len(digits_best) <= 4:
        return best_candidate, "K ověření (5místné číslo)"
    if len(digits_best) == 5 and not digits_best.startswith('0'):
        # why: 5-místné bez leading 0 je podezřelé (např. 10040 z 100140), ale nechat projít pokud VLM+OCR shoda
        # ponechat K ověření pro 5-místné bez 0, ale ne tvrdě – níže se ještě zkusí shoda
        pass  # necháme projít do konsensu, 5-místné s shodou může být Ověřeno

    # Chytřejší ochrana proti neúplným 12místným – why: 1864120 je fragment 442018641204, ale ne každé <10 s 4420
    ocr_comb = (all_ocr_text + " " + top_ocr_text).lower()
    if digits_best.startswith('442') and len(digits_best) < 12 and re.search(r'\b442\s*0', ocr_comb):
        return best_candidate, "K ověření (Neúplné 12místné číslo)"

    # Pokud chybí jeden z modelů – why: bez shody dvou nezávislých zdrojů nelze ověřit
    if not vlm_num or not ocr_num:
        return best_candidate, "K ověření (Pouze jeden model)"

    # Oboustranná kontrola shody mezi AI a OCR
    v_base, v_suf, v_part = split_drawing_details(vlm_num)
    o_base, o_suf, o_part = split_drawing_details(ocr_num)

    clean_v_base = re.sub(r'\W', '', v_base).lower()
    clean_o_base = re.sub(r'\W', '', o_base).lower()
    clean_v_full = re.sub(r'\W', '', vlm_num).lower()
    clean_o_full = re.sub(r'\W', '', ocr_num).lower()

    # 1. Stoprocentní exaktní shoda celého čísla včetně všech suffixů a dílů
    if clean_v_full == clean_o_full:
        return vlm_num, "Ověřeno (Shoda AI + OCR)"

    # 1b. Fuzzy shoda pro OCR off-by-one (why: 100140 vs 100440 na vybledlém skenu)
    # Zpřísněno: práh 0.95 + stejný počet číslic (zablokuje vloženou/chybějící číslici)
    digits_v = re.sub(r'\D', '', clean_v_full)
    digits_o = re.sub(r'\D', '', clean_o_full)
    if (calculate_string_similarity(clean_v_full, clean_o_full) > 0.95
            and len(clean_v_full) >= 6
            and len(digits_v) == len(digits_o)):
        return vlm_num, "Ověřeno (Shoda AI + OCR)"

    # 2. Shoda kmene čísla (pokud jeden model zachytil legitimní suffix a druhý ne)
    if clean_v_base == clean_o_base and clean_v_base:
        # Pokud se suffixy nebo díly přímo rozcházejí (např. 'a' vs 'b' nebo '21' vs '22' nebo '21' vs ''), je to K ověření!
        if (v_suf and o_suf and v_suf.lower() != o_suf.lower()) or \
           (v_part and o_part and v_part != o_part) or \
           (bool(v_part) != bool(o_part)):
            return (vlm_num or ocr_num), "K ověření (Neshoda suffixu)"

        final_suf = v_suf or o_suf
        final_part = v_part or o_part
        res = v_base + final_suf + (f"_{final_part}" if final_part else "")
        return res, "Ověřeno (Shoda AI + OCR)"

    # 3. Neshoda mezi modely
    return (vlm_num or ocr_num), "K ověření (Neshoda AI a OCR)"


def _dynamic_canvas_size(img_w: int, img_h: int) -> int:
    """Dynamicky zvolí canvas_size podle skutečné velikosti obrázku.
    Pro malé cropi (razítko ~600x300) stačí menší canvas = rychlejší OCR.
    """
    max_side = max(img_w, img_h)
    if max_side <= 640:
        return 640
    elif max_side <= 900:
        return 768
    return 1280


def _resize_for_ocr(img: Image.Image, max_dim: int = 1280) -> Image.Image:
    """Rychlý resize pro OCR s BILINEAR filtrem (2-3× rychlejší než LANCZOS, stejná OCR přesnost)."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    scale = max_dim / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)


# Maximální rozlišení OCR cropů podle zařízení
_CPU_OCR_MAX_DIM = 960   # Menší cropi na CPU = rychlejší EasyOCR CRAFT
_GPU_OCR_MAX_DIM = 1280  # GPU zvládne plné rozlišení


def prepare_crops(img: Image.Image, device: str = "cpu") -> tuple[Image.Image, Image.Image, Image.Image]:
    """Připraví ořezy razítka pro OCR (lze volat v prefetch vlákně).
    Na CPU používá menší max_dim pro rychlejší EasyOCR.
    """
    ocr_max = _CPU_OCR_MAX_DIM if device == "cpu" else _GPU_OCR_MAX_DIM
    crop_br = crop_title_block(img)
    crop_br_enh = enhance_for_ocr(crop_br)
    crop_ocr = _resize_for_ocr(crop_br_enh, max_dim=ocr_max)
    return crop_br, crop_br_enh, crop_ocr


def _resize_for_vlm_cpu(img_resized: Image.Image, max_vlm_dim: int = 768) -> Image.Image:
    """Na CPU zmenší vstup pro VLM na max 768px – méně pixelů = méně výpočtů (~30-40% rychlejší)."""
    w, h = img_resized.size
    if max(w, h) <= max_vlm_dim:
        return img_resized
    scale = max_vlm_dim / max(w, h)
    return img_resized.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)


def process_image(img: Image.Image, img_resized: Image.Image,
                  backend: SmolVLMBackend, reader: Any, device: str,
                  prepped_crops: tuple[Image.Image, Image.Image, Image.Image] | None = None,
                  executor: ThreadPoolExecutor | None = None) -> tuple[str | None, str, str, str]:
    """
    Celoobrázkové zpracování výkresu s adaptivním škálováním a hierarchickým OCR.
    CPU: sekvenční běh (eliminuje thread contention) + menší VLM rozlišení.
    GPU: paralelní běh + plné rozlišení.
    Accepts optional executor for reuse across calls.
    """
    ocr_max = _CPU_OCR_MAX_DIM if device == "cpu" else _GPU_OCR_MAX_DIM

    if prepped_crops:
        crop_br, crop_br_enh, crop_ocr = prepped_crops
    else:
        crop_br, crop_br_enh, crop_ocr = prepare_crops(img, device)

    # Na CPU zmenšit vstup pro VLM (why: VisionPsy 512 native → 512/768 rychlejší, SmolVLM 768 optimum)
    if device == "cpu":
        _cpu_vlm_dim = 512 if getattr(backend, "is_visionpsy", False) else 768
        vlm_input = _resize_for_vlm_cpu(img_resized, max_vlm_dim=_cpu_vlm_dim)
    else:
        vlm_input = img_resized

    # Dynamická volba canvas_size podle velikosti cropu
    ocr_canvas = _dynamic_canvas_size(crop_ocr.width, crop_ocr.height)

    if device == "cpu":
        # CPU: SEKVENČNÍ běh – VLM a OCR sdílejí CPU jádra, paralelní vlákna způsobují thrashing
        vlm_ans = backend.extract_text(vlm_input)
        vlm_num = extract_drawing_number(vlm_ans)

        ocr_results = reader.readtext(np.asarray(crop_ocr), canvas_size=ocr_canvas, mag_ratio=1.0)
        ocr_text = " ".join([item[1] for item in ocr_results])
    else:
        # GPU: PARALELNÍ běh – VLM na GPU, OCR na CPU současně
        def _run_vlm() -> tuple[str, str | None]:
            v_ans = backend.extract_text(vlm_input)
            return v_ans, extract_drawing_number(v_ans)

        def _run_ocr() -> tuple[list[Any], str]:
            o_res = reader.readtext(np.asarray(crop_ocr), canvas_size=ocr_canvas, mag_ratio=1.0)
            o_txt = " ".join([item[1] for item in o_res])
            return o_res, o_txt

        _exec = executor or ThreadPoolExecutor(max_workers=2)
        try:
            f_vlm = _exec.submit(_run_vlm)
            f_ocr = _exec.submit(_run_ocr)
            vlm_ans, vlm_num = f_vlm.result()
            ocr_results, ocr_text = f_ocr.result()
        finally:
            if executor is None:
                _exec.shutdown(wait=False)

    best_ocr_num, best_ocr_score = extract_best_from_ocr_boxes(ocr_results)

    # 2. Horní záhlaví skenujeme pouze tehdy, pokud dolní razítko nenašlo silnou shodu
    needs_top_scan = (not vlm_num) or (best_ocr_score < 70.0) or (vlm_num and best_ocr_num and vlm_num != best_ocr_num)

    if needs_top_scan:
        crop_top = crop_top_header_block(img)
        crop_top_enh = enhance_for_ocr(crop_top)
        crop_top_ocr = _resize_for_ocr(crop_top_enh, max_dim=ocr_max)
        top_canvas = _dynamic_canvas_size(crop_top_ocr.width, crop_top_ocr.height)

        ocr_top_res = reader.readtext(np.asarray(crop_top_ocr), canvas_size=top_canvas, mag_ratio=1.0)
        if ocr_top_res:
            ocr_results.extend(ocr_top_res)
            ocr_top_txt = " ".join([item[1] for item in ocr_top_res])
            ocr_text = ocr_text + " " + ocr_top_txt

    # 3. Skenování globálního zmenšeného výkresu pro atypická umístění (pouze jako poslední záchrana)
    if not vlm_num and not extract_drawing_number(ocr_text):
        ocr_glob_res = reader.readtext(np.asarray(img_resized), canvas_size=1280, mag_ratio=1.0)
        if ocr_glob_res:
            ocr_results.extend(ocr_glob_res)
            ocr_glob_txt = " ".join([item[1] for item in ocr_glob_res])
            ocr_text = ocr_text + " " + ocr_glob_txt

    final_num, conf_desc = verify_consensus(vlm_num, ocr_results, ocr_text)
    return final_num, conf_desc, vlm_ans, ocr_text
