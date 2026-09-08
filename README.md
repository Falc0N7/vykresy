# 🏭 Přejmenování výkresů — AI rozpoznávání čísel výkresů

Automatický nástroj pro rozpoznávání a přejmenování naskenovaných technických výkresů pomocí umělé inteligence (VLM + OCR). Obsahuje desktopové GUI pro kontrolu výsledků a hromadné přejmenování souborů.

## 📋 Co to dělá

1. **Načte složku** s naskenovanými výkresy (`.tif`, `.jpg`, `.png`, podpora formátů A0+ až do 500 Mpx)
2. **AI automaticky rozpozná** čísla výkresů z razítek a záhlaví
3. **Zobrazí výsledky** v přehledné tabulce s náhledem výkresu
4. **Operátor zkontroluje** a potvrdí/opraví rozpoznaná čísla (tlačítko **⚙ Auto-ověření / Manuální kontrola** pro přepínání režimu verifikace)
5. **Hromadně přejmenuje** soubory podle zjištěných čísel výkresů
6. **Exportuje seznam** do Excelu (`seznam_vykresu.xlsx`)

## ⚙️ Systémové požadavky

| Požadavek | Minimum | Doporučeno |
|:----------|:--------|:-----------|
| **Python** | 3.10+ | 3.11 |
| **OS** | Windows 10+ | Windows 10/11 |
| **RAM** | 8 GB | 16 GB |
| **Disk** | 10 GB volného místa | 15 GB |
| **GPU** | Volitelná | NVIDIA s 4+ GB VRAM |

> **Poznámka:** Aplikace běží i bez GPU (na procesoru), ale s GPU je zpracování ~3× rychlejší.

## 🚀 Spuštění

```
run.bat
```

Nebo přímo:
```
python main.py
```

### Co se stane při prvním spuštění

1. ✅ Zkontroluje verzi Pythonu (vyžaduje 3.10+)
2. 📦 Automaticky nainstaluje chybějící knihovny z `requirements.txt`
3. 🤖 Stáhne AI model (~7 GB) — zobrazí průběh stahování
4. 🔥 Zahřeje výpočetní modely a spustí GUI

> **Poznámka:** Při prvním spuštění je potřeba připojení k internetu. Poté aplikace funguje offline.

## 🏗️ Architektura

```
main.py          Vstupní bod — kontrola Pythonu, automatická instalace, spuštění
config.py        Detekce hardware (CUDA/MPS/XPU/CPU), konfigurace, logování
ocr_engine.py    AI rozpoznávací jádro (VLM + OCR), stahování modelů, verifikace
parser.py        Extrakce čísel výkresů, heuristiky, korekce OCR chyb
gui.py           Grafické rozhraní (Tkinter) — prohlížeč, kontrola, přejmenování
```

### Detekce hardware

Aplikace automaticky detekuje dostupný hardware a přizpůsobí výpočetní parametry:

| Zařízení | Detekce | Přesnost výpočtu | Poznámka |
|:---------|:--------|:-----------------|:---------|
| NVIDIA GPU | `torch.cuda.is_available()` | FP16 / 4-bit | Automatický fallback na CPU při nedostatku VRAM |
| Apple Silicon | `torch.backends.mps.is_available()` | FP32 | Sdílená paměť |
| Intel XPU | `torch.xpu.is_available()` | FP32 | Experimentální |
| CPU | Vždy dostupný | INT8 kvantizace | Počet vláken automaticky dle jader |

### Výkonnostní profily

- **🚀 Výkonný** — vyšší výkon, plné využití CPU/GPU, vysoká priorita procesu
- **🌱 Úsporný** — nízké zatížení PC, 1–2 vlákna, nízká priorita (PC zůstává plynulý)

## 📁 Struktura projektu

```
├── .env.example              Šablona konfiguračních proměnných prostředí
├── .github/workflows/ci.yml  CI pipeline (Windows, Python 3.11, automatické testy)
├── .gitignore                Pravidla pro ignorování souborů v Gitu
├── CHANGELOG.md              Historie verzí a změn
├── DOKUMENTACE.md            Technická dokumentace architektury
├── LICENSE                   Licence
├── NAVOD.md                  Uživatelský návod (CZ)
├── README.md                 Tento soubor
├── VERSION                   Aktuální verze aplikace
├── config.py                 Konfigurace a detekce hardware
├── gui.py                    Grafické rozhraní (Tkinter)
├── main.py                   Vstupní bod aplikace
├── models/                   Cache pro AI modely (automaticky staženy)
│   └── .gitkeep
├── ocr_engine.py             AI výpočetní jádro
├── parser.py                 Parsování a extrakce čísel výkresů
├── requirements.txt          Python závislosti
├── run.bat                   Spouštěcí skript pro Windows
└── tests/                    Automatické testy (pytest)
    ├── test_config.py        Testy detekce hardware
    ├── test_gui_helpers.py   Testy pomocných funkcí GUI
    ├── test_parser.py        Testy parseru čísel výkresů
    └── test_verify_consensus.py  Testy ověřovacího konsensu (shoda AI + OCR)
```

## 🔧 Konfigurace prostředí

Zkopírujte `.env.example` → `.env` a upravte dle potřeby:

```env
# Cesta k AI modelům
HF_HOME=./models

# Vypnutí automatické instalace (pro správce)
FINAAL_NO_AUTO_INSTALL=0

# Vypnutí automatického stahování modelů (offline režim)
FINAAL_NO_AUTO_DOWNLOAD=0
```

> Existující systémové proměnné mají přednost před hodnotami v `.env`.

## 🧪 Spuštění testů

```bash
pip install pytest
python -m pytest tests -q
```

> `pytest` není součástí `requirements.txt` (je potřeba jen pro testy).

## 📚 Další dokumentace

- **[NAVOD.md](NAVOD.md)** — Uživatelský návod (krok za krokem)
- **[DOKUMENTACE.md](DOKUMENTACE.md)** — Technická dokumentace (architektura, algoritmy)
- **[CHANGELOG.md](CHANGELOG.md)** — Historie verzí

## 📄 Licence

Viz [LICENSE](LICENSE).
