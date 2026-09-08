# Uživatelský návod – Přejmenování výkresů

**Program pro automatické přejmenování naskenovaných technických výkresů**

Verze 2.2.0

---

## Co tento program dělá?

Program slouží k **automatickému přejmenování naskenovaných technických výkresů**. Místo toho, abyste ručně hledali číslo výkresu v razítku a přejmenovávali soubory jeden po druhém, program to udělá za vás.

**Jak to funguje jednoduše:**

1. Vyberte složku, kde máte uložené naskenované výkresy
2. Program pomocí umělé inteligence přečte čísla z razítek výkresů
3. Vy zkontrolujete, zda program přečetl čísla správně
4. Program přejmenuje soubory a vytvoří Excel seznam

**Podporované formáty souborů:** `.tif`, `.tiff`, `.jpg`, `.jpeg`, `.png`

---

## Co budete potřebovat

| Požadavek | Hodnota |
|-----------|---------|
| **Operační systém** | Windows 10 nebo 11 |
| **Paměť RAM** | Alespoň 8 GB (lépe 16 GB) |
| **Volné místo na disku** | Alespoň 10 GB |
| **Python** | Verze 3.10 nebo novější |
| **Internet** | Potřeba pouze při prvním spuštění |

> **Poznámka:** Pokud máte v počítači grafickou kartu NVIDIA, program bude pracovat rychleji. Bez ní program funguje také, jen o něco pomaleji.

---

## Instalace krok za krokem

### Krok 1: Nainstalujte Python

1. Otevřete internetový prohlížeč a přejděte na adresu: **https://www.python.org/downloads/**
2. Klikněte na tlačítko **„Download Python"** (stáhněte nejnovější verzi)
3. Spusťte stažený instalátor
4. **DŮLEŽITÉ:** Při instalaci zaškrtněte políčko **„Add Python to PATH"** (je dole na první obrazovce instalátoru)
5. Klikněte na **„Install Now"**

### Krok 2: První spuštění programu

1. Otevřete složku s programem (kde máte soubor `run.bat`)
2. **Dvakrát klikněte** na soubor **`run.bat`**
3. Při prvním spuštění program automaticky:
   - Nainstaluje potřebné knihovny (~3 GB) – zobrazí se okno s průběhem
   - Stáhne AI model (~7 GB) – zobrazí se průběh stahování
4. **Nevypínejte počítač!** Počkejte, než se vše dokončí (může to trvat 5–15 minut)

> **Při dalších spuštěních** se program spustí rychle, protože vše už bude nainstalované.

---

## Jak program používat

### 1. Spuštění programu

Dvakrát klikněte na soubor **`run.bat`** ve složce programu.

### 2. Výběr složky s výkresy

Po spuštění se zobrazí okno pro výběr složky. **Vyberte složku**, kde máte uložené naskenované výkresy, a potvrďte.

> Pokud ve složce nejsou žádné výkresy (soubory `.tif`, `.jpg` nebo `.png`), program vás o tom informuje.

### 3. Nastavení zpracování

Zobrazí se okno s nastavením, kde vyberete:

**Formát papíru:**
- Napište formát papíru vašich výkresů (např. `A4`, `A3`, `A2`)
- Tento formát se přidá do názvu přejmenovaného souboru

**Výpočetní zařízení:**
- **Automaticky (doporučeno)** – program sám vybere nejlepší možnost
- Grafická karta (GPU) – pokud ji máte, zpracování bude rychlejší
- Procesor (CPU) – funguje vždy

**Výkon:**
- **🚀 Výkonný** – rychlejší zpracování, ale počítač bude více zatížený
- **🌱 Úsporný** – pomalejší zpracování, ale na počítači můžete dělat i jiné věci

Klikněte na **„Spustit zpracování"**.

### 4. Čekání na zpracování

Program nyní zpracovává vaše výkresy. Na obrazovce uvidíte:

- Jaký soubor se právě zpracovává
- Kolik procent je hotovo
- Odhadovaný zbývající čas
- Počet zpracovaných souborů

**Tipy:**
- Můžete kdykoliv kliknout na **„⏸ Pozastavit a bezpečně ukončit"** – program uloží postup a při dalším spuštění nabídne pokračování
- I při neočekávaném výpadku proudu se postup automaticky ukládá po každém výkresu

### 5. Kontrola výsledků

Po zpracování se otevře hlavní okno programu rozdělené na dvě části:

**Levá část – Tabulka:**

| Sloupec | Popis |
|---------|-------|
| **Původní soubor** | Jak se soubor jmenuje teď |
| **Číslo výkresu** | Co program přečetl z razítka (můžete upravit) |
| **Název výkresu** | Sem můžete napsat název součásti (volitelné) |
| **Stav** | 🟢 zelená = ověřeno, 🔴 červená = ke kontrole |
| **Přejmenovat?** | Zaškrtávátko – zda se má soubor přejmenovat |

**Pravá část – Náhled:**

- Zobrazuje vybraný výkres ve velkém
- Pod obrázkem je žlutě zobrazené rozpoznané číslo

**Jak kontrolovat:**

1. Klikněte na řádek v tabulce – vpravo se zobrazí výkres
2. Porovnejte číslo v tabulce s číslem na výkresu
3. Pokud je číslo správné, stiskněte **Enter** – řádek se označí zeleně
4. Pokud je číslo špatné, opravte ho v poli „Číslo výkresu" a stiskněte **Enter**
5. Do pole „Název výkresu" můžete volitelně napsat název součásti

> **Položky se zelenou tečkou** (🟢) program ověřil automaticky – přesto je doporučeno je zkontrolovat.

### 6. Přejmenování souborů

Když jste s kontrolou spokojeni:

1. Zaškrtněte soubory, které chcete přejmenovat (nebo použijte **Ctrl+A** pro označení všech)
2. Klikněte na **„Přejmenovat vybrané"** (nebo stiskněte **Ctrl+Enter**)
3. Potvrďte přejmenování v dialogu

**Soubory budou přejmenovány** ve formátu: `ČísloVýkresu (Formát).přípona`
Například: `100416 (A4).tif`

**Zároveň se automaticky vytvoří Excel soubor** `seznam_vykresu.xlsx` ve složce s výkresy, obsahující:
- Sloupec A: Číslo výkresu
- Sloupec B: Název výkresu
- Sloupec C: Formát

---

## Klávesové zkratky

| Klávesa | Co udělá |
|---------|----------|
| **Enter** | Potvrdí aktuální výkres a přejde na další |
| **↑** / **↓** | Přechod na předchozí / následující výkres |
| **F3** | Otevře výkres v prohlížeči obrázků Windows |
| **Ctrl+A** | Zaškrtne všechny výkresy k přejmenování |
| **Ctrl+D** | Odškrtne všechny výkresy |
| **Ctrl+Enter** | Spustí přejmenování zaškrtnutých |
| **Kolečko myši** | Posouvání v tabulce / přibližování náhledu |

---

## Pokračování v rozpracované práci

Pokud program zavřete (křížkem nebo tlačítkem Pozastavit) uprostřed práce, **nic se neztratí!**

Při dalším spuštění a výběru stejné složky se zobrazí dialog s možnostmi:

- **▶ Pokračovat** – dopočítá zbývající výkresy a naváže tam, kde jste skončili
- **🔎 Zkontrolovat hotové** – otevře kontrolní okno jen s již zpracovanými výkresy
- **🔄 Od začátku** – smaže předchozí postup a začne znovu

> **Vaše úpravy** (opravená čísla, dopsané názvy, zaškrtnutí) se automaticky ukládají při zavření okna.

---

## Režim ověřování

V horním pravém rohu kontrolního okna je tlačítko **⚙ Auto-ověření / Manuální kontrola**:

- **Auto-ověření** (výchozí) – výkresy, kde se AI a OCR shodly, jsou automaticky zelené
- **Manuální kontrola** – všechny výkresy budou červené a musíte je ručně potvrdit Enterem

---

## Řešení problémů

| Problém | Řešení |
|---------|--------|
| Program se nespustí | Zkontrolujte, že máte nainstalovaný Python 3.10+ a zaškrtnuté „Add Python to PATH" |
| Chybí knihovny | Zkontrolujte připojení k internetu a spusťte program znovu |
| Model se nestahuje | Zkontrolujte, že máte alespoň 10 GB volného místa na disku |
| Špatně přečtené číslo | Opravte ho ručně v poli „Číslo výkresu" |
| Excel nelze uložit | Zavřete Excel soubor, pokud ho máte otevřený; program zkusí uložit jako `seznam_vykresu_nove.xlsx` |
| Zpracování je pomalé | Zkuste režim „Výkonný" místo „Úsporný" |
| Program spadne | Spusťte znovu – postup byl automaticky uložen |

**Soubor s podrobným logem** chyb najdete ve složce programu: `rename_drawings.log`

---

## Důležité soubory programu

| Soubor | K čemu slouží |
|--------|--------------|
| `run.bat` | Tímto souborem spouštíte program |
| `seznam_vykresu.xlsx` | Automaticky vytvořený Excel seznam výkresů |
| `session_checkpoint.json` | Uložený postup rozpracovaného zpracování |
| `rename_drawings.log` | Podrobný záznam činnosti programu (pro řešení problémů) |

> **Ostatní soubory** ve složce programu jsou technické soubory – **nemazejte je** a **neupravujte je**.

---

*Tento návod je zjednodušený pro běžné uživatele. Podrobná technická dokumentace je k dispozici v souboru `DOKUMENTACE.md`.*
