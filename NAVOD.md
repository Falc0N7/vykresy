# Uživatelský návod — Přejmenování výkresů v2.2.0

Aplikace slouží k dávkovému rozpoznání čísel výkresů (VLM + OCR), vizuální kontrole a hromadnému přejmenování s exportem do Excelu.

> Python 3.10+ · Windows 10/11

---

## Soubory a struktura

- **`run.bat`** — poklepejte pro spuštění; nastaví kódování, zkontroluje Python a spustí `main.py`
- **`main.py`** — při prvním spuštění automaticky nainstaluje chybějící knihovny a připraví prostředí
- **`gui.py`** — celé rozhraní: dialogy, progress s ETA, splitter, náhledy, checkpointy, přejmenování
- **`ocr_engine.py`** — lokální VLM `SmolVLM-500M-Instruct` + `RapidOCR` + ověření shody; při prvním spuštění sám stáhne model (~7 GB)
- **`parser.py`** — filtrace letopočtů, norem ČSN/DIN a jakostí oceli, skórování kandidátů
- **`config.py` / `config.json`** — detekce CPU/RAM/GPU a profily Výkonný/Úsporný (Turbo/Eco); poslední volba se ukládá do `config.json`
- **`requirements.txt`** — závislosti pro `pip install -r requirements.txt`
- **`models/`** — lokální váhy modelu (vytvoří se automaticky)
- **`session_checkpoint.json` / `undo_backup.json` / `seznam_vykresu.xlsx` / `rename_drawings.log`** — vznikají automaticky za běhu

Požadavky: Python 3.10+, Windows 10/11, ~10 GB volno, internet při prvním spuštění.

---

## 1. Spuštění a první instalace

1. Dvakrát klikněte na **`run.bat`**. Pokud chybí Python, zobrazí se návod s odkazem na https://www.python.org/downloads/ (zaškrtněte „Add Python to PATH“).
2. **První spuštění trvá déle:** aplikace zobrazí okno „Instalace závislostí / Stahuji AI model“ (knihovny ~3 GB, model ~7 GB). Nevypínejte PC, sledujte progress. Vyžaduje internet.
3. Vyberte složku s výkresy — dialog „Vyberte složku…“ . Podporováno: `.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png` (podpora velkých formátů až do 500 Mpx / 500_000_000 pixelů). Prázdná složka → hláška „Nebyly nalezeny žádné výkresy.“
4. **Detekce rozpracované práce (Checkpoint):**
   - Pokud jste dříve zpracování přerušili nebo zavřeli okno, zobrazí se dialog **„Nalezeno rozpracované zpracování“**:
     - **`▶ Pokračovat ve zpracování`** — dopočítá pouze zbývající výkresy, hotové načte z `session_checkpoint.json`.
     - **`🔎 Zkontrolovat hotové`** — přeskočí zbytek a rovnou otevře revizní okno s dosud hotovými.
     - **`🔄 Od začátku`** — smaže záznam a začne znovu od prvního souboru.
5. V okně **Nastavení zpracování výkresů** (`520×420`):

   - **1. Formát papíru:** textové pole, výchozí `A4` z `config.json`. Vloží se jako ` (A4)` před příponu — např. `100416 (A4).tif`.
   - **2. Výpočetní zařízení:** radio dle detekce (`⚡ GPU` pokud `torch.cuda.is_available()`, jinak disabled) + `💻 CPU` vždy. Předvybráno `Auto` (GPU pokud je, jinak CPU).
   - **3. Výkon:** `🚀 Výkonný` (Rychlejší zpracování, vyšší zatížení PC.) vs `🌱 Úsporný` (Pomalejší zpracování, PC zůstává plynulý.). Předvybráno `🚀 Výkonný` — aplikace se sama přizpůsobí vašemu PC (počet jader, RAM, VRAM).

6. **Spustit zpracování** uloží volbu do `config.json` a otevře okno postupu.

---

## 2. Okno zpracování a pozastavení (vypnutí PC)

- Nejprve „Inicializace AI a OCR…“ s procenty (načítání / stahování modelu, načítání OCR).
- Po načtení modelů přechod na `determinate` progress:
  - `Zpracovávám: <soubor>`
  - `X% | Zbývá ~M min S s (Z.Z s/soubor)` — ETA počítáno z průměru
  - `I / N souborů | <profil> | CUDA/CPU` a progressbar
- **⏸ Tlačítko „Pozastavit a bezpečně ukončit“** (i křížek okna `X`):
  - Dokončí aktuální soubor, uloží všechny dosavadní výsledky do `session_checkpoint.json` a zobrazí potvrzení.
  - **Můžete bez obav vypnout počítač.** Při příštím spuštění a volbě stejné složky dialog nabídne pokračování.
- Automatické ukládání probíhá **po každém jednotlivém výkresu**, takže nepřijdete o data ani při výpadku proudu.

---

## 3. Revizní okno

Po dokončení se otevře maximalizované okno (`1600×920`, `zoomed`) se statistikou a přepínačem režimu v horní liště:

`Celkem: N výkresů | ● Ověřeno (dole): X | ● K ověření (nahoře): Y   [Tažením příčky uprostřed lze měnit šířku panelů]   [⚙ Auto-ověření]`

*(Stav výkresu je v rozhraní graficky znázorněn barevnými kroužky: zelený kroužek = ověřeno, červený kroužek = k ověření.)*

- **Tlačítko nastavení režimu `⚙ Auto-ověření` / `⚙ Manuální kontrola`:** V horní liště vpravo přepíná způsob schvalování:
  - **`Auto-ověření`** (výchozí) — konsenzus AI + OCR; výkresy se shodou jsou automaticky označeny zeleným kroužkem jako ověřené a předvybrány k přejmenování.
  - **`Manuální kontrola`** — přepne všechny položky do stavu k ověření (červený kroužek), takže každá položka vyžaduje ruční potvrzení uživatelem (dříve ručně potvrzené výkresy klávesou Enter zůstávají zelené).

### Rozložení

```
+--------------------------------------------------------------------------+
| Celkem: N | ● Ověřeno: X | ● K ověření: Y              [⚙ Auto-ověření] |
+---------------------------------------+----------------------------------+
| LEVÝ: Tabulka                         | PRAVÝ: Živý náhled               |
| hlavička 5 sloupců                    | 📄 soubor  [⟲ 100%] [Otevřít F3] |
| 🔴 100999 | Páka řazení ... K ověření | +-- obrázek (autokontrast) ----+ |
| 🟢 100416 | Hřídel ...... Ověřeno     | |                              | |
|                                       | +------------------------------+ |
|                                       | 📌 Rozpoznané číslo: 100416    |
|                                       | stav (zelený/červený kroužek)  |
+--------------------------------------------------------------------------+
| [✓ Vybrat vše] [✗ Odškrtnout]                    [Přejmenovat vybrané] |
+--------------------------------------------------------------------------+
```

- **Splitter** `PanedWindow HORIZONTAL` — tažením svislé příčky upravíte šířku.
- **Scroll:** kolečko = svisle, `Shift+kolečko` = vodorovně (nad levým panelem).
- **Tabulka:** 5 sloupců:
  1. `Původní soubor` — kliknutím vyberete řádek
  2. `Číslo výkresu` — editovatelné pole (předvyplněno rozpoznaným číslem)
  3. `Název výkresu` — pole pro váš zápis názvu součásti (editovatelné)
  4. `Stav` — barevný kroužek: zelený kroužek (🟢 Ověřeno) / červený kroužek (🔴 K ověření)
  5. `Přejmenovat?` — zaškrtávátko
- **Automatické ukládání rozpracované kontroly:** Vaše úpravy čísel/názvů a zaškrtnutí se automaticky ukládají při zavření okna křížkem (`X`) do `session_checkpoint.json` a zároveň se exportují do `seznam_vykresu.xlsx` ve zdrojové složce. Žádné tlačítko „Uložit“ není potřeba — stačí zavřít okno. Při příštím otevření stejné složky se vše obnoví.

### Schvalování

1. Klikněte do řádku nebo použijte `↓` — pravý panel okamžitě ukáže celý výkres.
2. Zkontrolujte / upravte číslo a vepište název do `Název výkresu`.
3. Stiskněte **`Enter`**: řádek získá zelený kroužek (`Ověřeno (Uživatelem)`), zaškrtne se, přesune se dolů mezi ověřené a fokus přeskočí na další výkres.

### Náhled vpravo

- Vždy celý výkres (autokontrast + zostření), zoom kolečkem `0.25×–5×`, tažení myší = pan (při zoom >100 %).
- Tlačítko `⟲ 100%` vrátí na fit; `Otevřít (F3)` otevře originál ve Windows prohlížeči.
- Pod obrázkem: žluté `📌 Rozpoznané číslo: …` a barevný stav ověření (zelený kroužek = ověřeno, červený kroužek = k ověření).

---

## 4. Export do Excelu a přejmenování

Při jakémkoliv zavření revizního okna křížkem **i** po kliknutí na **Přejmenovat vybrané** se automaticky vytvoří / aktualizuje **`seznam_vykresu.xlsx`** v cílové složce:

- **Sloupec A:** `Číslo výkresu` — čisté číslo (zadané nebo rozpoznané)
- **Sloupec B:** `Název výkresu` — vámi vyplněný název
- **Sloupec C:** `Formát` — např. `A4`, `A3`

Excel je formátován: modrá hlavička `#1976D2`, bílé tučné písmo, rámečky, auto šířka. Pokud je soubor otevřen v Excelu, uloží se jako `seznam_vykresu_nove.xlsx` nebo s timestampem.

Tlačítko **`Přejmenovat vybrané (Ctrl+Enter)`**:
1. Přejmenuje zaškrtnuté soubory na `Číslo (Formát).přípona` (kolize → `Číslo (A4) (2).tif`)
2. Zapíše zálohu pro vrácení (`undo_backup.json`)
3. Zaktualizuje `seznam_vykresu.xlsx`

Tipy:
- Neplatné znaky Windows (`\ / : * ? " < > |`) se odstraní automaticky.
- Přípona a ` (A4)` se při editaci ignorují (pole drží čisté číslo).
- `Ctrl+A` / `Ctrl+D` zaškrtne/odškrtne vše.

---

## 5. Klávesové zkratky

| Zkratka | Funkce |
|---|---|
| `Enter` / `Num Enter` | Schválit → zelený kroužek + přesun dolů |
| `↑` / `↓` | Předchozí / další výkres |
| `F3` / `Ctrl+O` | Otevřít výkres |
| `Ctrl+A` / `Ctrl+D` | Vybrat / odškrtnout vše |
| `Ctrl+Enter` | Přejmenovat vybrané |
| `kolečko` | Svislý posun tabulky |
| `Shift+kolečko` | Vodorovný posun tabulky |
| `kolečko` nad náhledem | Zoom, tažení = pan |

---

## 6. Řešení potíží

- **Chybí knihovny / instalace selhala:** zkontrolujte internet, spusťte ručně `pip install -r requirements.txt`, viz `rename_drawings.log`.
- **Model se nestahuje:** zkontrolujte místo (~10 GB volno), proxy.
- **Žádné výkresy ve složce:** info dialog a konec — zkontrolujte přípony.
- **Excel je otevřen:** viz fallback `seznam_vykresu_nove.xlsx`.
- **Soubor zamčen:** přeskočí se, na konci „Dokončeno s chybami“.
- **CUDA OOM:** pokračuje na CPU; viz log.
- **Pomalý náhled:** cache je 30 položek, zoom reset `⟲ 100%`.
- **Příliš velký obrázek (DecompressionBomb):** limit velikosti je nastaven na 500 Mpx (500_000_000 pixelů), což spolehlivě pokryje i rozsáhlé velkoformátové skeny A0+ při 600 DPI.

Log: `rename_drawings.log` (rotace `10 MB ×2`) v adresáři aplikace.
