"""
Parsovací modul pro extrakci čísel výkresů z textu.
Univerzální extrakce pro různorodé formáty čísel a alfanumerických kódů bez hardcoded omezení.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Pre-kompilované regulární výrazy – chytřejší normalizace pro historické skeny
_RE_DOTTED_PAIRS = re.compile(r'(?<!\d)(\d{2})[.,](\d{2})[.,](\d{2})(?!\d)')
_RE_DOTTED_TRIPLETS = re.compile(r'(?<!\d)(\d{3})[.,](\d{3})(?!\d)')
_RE_DOTTED_2_4 = re.compile(r'(?<!\d)(\d{2})[.,](\d{4})(?!\d)')
_RE_DOTTED_4_2 = re.compile(r'(?<!\d)(\d{4})[.,](\d{2})(?!\d)')
# why: původní (\d{2,4})\s+(\d{3,4}) nepokryje 442 01075 (4+5) ani 029 4 (3+1) – GLM dává 4 fragmenty
_RE_GLUE_SPACE = re.compile(r'(\d)\s+(?=\d)')
_RE_GLUE_DOT = re.compile(r'(?<=\d)[.,](?=\d)')
_RE_SLASH_SUFFIX = re.compile(r'(?<!\w)([A-Za-z]?\d{4,12})[/\-]+([a-zA-Z])(?!\w)')
_RE_CHANGE_SUFFIX = re.compile(r'^[\s.]*(zenny|zmeny|změny|zmen|zen|anderungs|ander|andr|an|no|n\.)', re.IGNORECASE)
_RE_PART_NUMBER = re.compile(r'^[\s]*[/\-_]+[\s]*(\d{1,3}(?:\.\d+)?)')
_RE_R_WORD = re.compile(r'\br\b', re.IGNORECASE)
_RE_L_WORD = re.compile(r'\bl\b', re.IGNORECASE)

# why: K20, sp1, E, R_L musí být rozpoznány i s mezerou – původní neznalo R_L a E
_RE_SPACE_SUFFIX = re.compile(r'(?<!\w)([A-Za-z]?\d{4,14})\s+([a-eA-E]|sp\d?|SP\d?|[Kk]\d{1,2}|[Ee]\d?|R_L)(?!\w)')
# why: K\d a sp musí být součástí čísla, jinak split je odřízne – group(2) musí zůstat suffix, case-insensitive K
_RE_UNIVERSAL_DRAWING = re.compile(r'\b([A-Za-z]{0,2}\d{4,14})(?:[\-_/]?([a-zA-Z]{1,3}\d{0,2}(?:\-[a-zA-Z])?|[Kk]\d{1,2}|sp\d?|R_L))?(?!\d)\b')
_RE_ALPHANUM_DRAWING = re.compile(r'\b([A-Za-z]{1,4}[\-_]?\d{3,10})(?:[\-_/]?([a-zA-Z]{1,2}\d{0,2}))?\b')

# Kontextové regex pro skórování — why: původně kompilovány uvnitř extract_drawing_number() při každém volání (pomalé)
_RE_DATE_PREFIX = re.compile(r'(dne|datum|rok|schvalil|zkousel|kreslil|am|v\.|den|\b\d{1,2}[./]\s*\d{1,2}[./]|\b\d{1,2}[./]\s*[ivxlcdm]+[./])', re.IGNORECASE)
_RE_DRAWING_LABEL = re.compile(r'(vykres|vykr|cislo|cisl|zeichnung|nr|no|modell|soucast|dil|polozka|bl|list|tab)', re.IGNORECASE)
_RE_CHANGE_LABEL = re.compile(r'(zmen|změn|anderung|änderung|revision|rev\b|index\b|zmena|změna)', re.IGNORECASE)
_RE_STANDARD_LABEL = re.compile(r'(csn|čsn|din|iso|on|pn|tl|tloustka|mat\b|mat\.|material|materiál|jakost|ocel|werkstoff|polotovar|druh)', re.IGNORECASE)

# Známé standardní jakosti ocelí ČSN (třída 10-19), které se často vyskytují v kolonce materiálu
_KNOWN_STEEL_GRADES = {
    "11373", "11500", "11523", "11600", "11700",
    "12010", "12020", "12040", "12050", "12060", "12070",
    "14220", "15142", "15230", "15241", "16220", "17021", "19573", "19830"
}


def clean_text_for_numbers(text: str) -> str:
    """
    Chytřejší normalizace – iterativní glue pro 442 01075 029 4 a podobné fragmenty:
    - Spojí všechny číselné skupiny oddělené mezerami/tečkami/čárkami do jednoho čísla (pokud celkem 5-14 číslic)
    - Zachová lomítka pro čísla dílů a suffixy
    """
    if not text:
        return ""
    
    # 1. Zachovat původní specifické spoje pro rychlost (tečky mezi dvojicemi)
    text = _RE_DOTTED_PAIRS.sub(r'\1\2\3', text)
    text = _RE_DOTTED_TRIPLETS.sub(r'\1\2', text)
    text = _RE_DOTTED_2_4.sub(r'\1\2', text)
    text = _RE_DOTTED_4_2.sub(r'\1\2', text)
    # 2. Iterativní glue mezer – why: GLM dává 442 01075 029 4 (4 fragmenty), původní spojil jen jednou 2-4+3-4
    # why: spojí 442 01075 -> 44201075, pak 029 4 -> 0294, pak 44201075 0294 -> 442010750294
    for _ in range(3):  # max 3 iterace pro 4 fragmenty
        new = _RE_GLUE_SPACE.sub(r'\1', text)
        if new == text:
            break
        text = new
    # 3. Odstranit tečky/čárky mezi číslicemi – iterativně
    text = _RE_GLUE_DOT.sub('', text)
    # 4. Spojí suffixy oddělené mezerou (např. 105303 a -> 105303a, 115515 K20 -> 115515K20)
    text = _RE_SPACE_SUFFIX.sub(r'\1\2', text)
    # 5. Převede lomítko se suffixem (např. 100805/b -> 100805b)
    text = _RE_SLASH_SUFFIX.sub(r'\1\2', text)
    return text


def split_drawing_details(num_str: str) -> tuple[str, str, str]:
    """
    Rozdělí číslo výkresu na základní kód (base), suffix a číslo dílu (part).
    Např.:
      '104102_3' -> ('104102', '', '3')
      '106275d' -> ('106275', 'd', '')
      '108515a-b' -> ('108515', 'a-b', '')
      'E103322' -> ('E103322', '', '')
      '442010750294' -> ('442010750294', '', '')
    """
    if not num_str:
        return "", "", ""

    # Dlouhá jednolitá čísla (10-14 číslic)
    if re.fullmatch(r'\d{10,14}', num_str):
        return num_str, "", ""

    # 1. Detekce partu na konci (_1, _11, apod.)
    part = ""
    part_match = re.search(r'_([a-zA-Z\d]+)$', num_str)
    if part_match:
        part = part_match.group(1)
        num_str = num_str[:part_match.start()]

    # 2. Detekce suffixu – chytřejší: K\d, sp, R_L musí zůstat pohromadě
    # why: původní [a-zA-Z]{1,3} odřízlo K20 na K2, sp1 na sp, R_L na R; musí být case-insensitive
    suffix_match = re.search(r'([Kk]\d{1,2}|sp\d?|SP\d?|R_L|[a-zA-Z]{1,3}(?:\-[a-zA-Z])?)$', num_str)
    if suffix_match and not num_str.isalpha():
        matched_suf = suffix_match.group(1)
        base_cand = num_str[:-len(matched_suf)]
        # why: E103322 nesmí být rozděleno na E10332+2
        if any(c.isdigit() for c in base_cand):
            # why: K20 musí být celý, ne K2
            return base_cand, matched_suf, part

    return num_str, "", part


def extract_drawing_number(text: str) -> str | None:
    """
    Univerzálně extrahuje číslo výkresu z textu bez ohledu na konkrétní číselnou řadu.
    Podporuje libovolné délky a formáty:
      - 4-14místná čísla, alfanumerické kódy (např. 105303, 70123, 442010750294, E103322)
      - Písmenné indexy a rozsahy (např. 100463a, 108515a-b, sp1)
      - Čísla dílů (/1, /11, -3)
      - Pravolevost (R_L)
    """
    if not isinstance(text, str) or not text.strip():
        return None

    text_clean = clean_text_for_numbers(text)
    lower_text = text.lower()

    # Detekce pravé a levé strany (R a L)
    has_r_l = False
    if any(k in lower_text for k in ['lev', 'prav', 'link', 'recht']) or ('r' in lower_text and 'l' in lower_text):
        if (_RE_R_WORD.search(lower_text) and _RE_L_WORD.search(lower_text)) or \
           any(k in lower_text for k in ['r_l', 'r+l', 'r a l']):
            has_r_l = True

    candidates = []

    # 1. Hledání standardních i různorodých čísel
    for match in _RE_UNIVERSAL_DRAWING.finditer(text_clean):
        base_num = match.group(1)
        suffix = match.group(2) or ''

        # Odstranění falešných indexů (např. slova změny)
        if suffix:
            after_suffix = text_clean[match.end():match.end()+20].lower().strip()
            if _RE_CHANGE_SUFFIX.match(after_suffix):
                suffix = ''

        full_candidate = base_num + suffix
        start_idx = match.start()
        end_idx = match.end()

        # Detekce čísla dílu za číslem výkresu (např. 105336/3 -> part 3)
        following_text = text_clean[end_idx:end_idx+15].strip()
        part_match = _RE_PART_NUMBER.match(following_text)
        part_num = None
        if part_match:
            part_str = part_match.group(1)
            clean_p = re.sub(r'\D', '', part_str)
            if 1 <= len(clean_p) <= 3:
                part_num = clean_p

        # Kontext před a za číslem – why: 30 nestačí pro oddělené kolonky (Číslo výkresu 20 znaků daleko)
        ctx_before = text_clean[max(0, start_idx-60):start_idx].lower()
        ctx_after = text_clean[end_idx:min(len(text_clean), end_idx+60)].lower()

        # Výpočet skóre kandidáta
        digits_only = re.sub(r'\D', '', full_candidate)
        digits_count = len(digits_only)

        # Základní skóre podle délky
        score = digits_count * 10

        # 1. Speciální penalizace pro letopočty (1900 - 1999)
        is_year_like = (digits_count == 4 and digits_only.startswith('19') and 1900 <= int(digits_only) <= 1999)
        if is_year_like:
            score -= 60  # Letopočty v razítku mají nízkou prioritu
            if _RE_DATE_PREFIX.search(ctx_before) or _RE_DATE_PREFIX.search(ctx_after):
                score -= 50  # Potvrzeno v kontextu data

        # 2. Detekce složených dat (např. 291923 = 29. 1. 1923, 161924, 2012_192, 51923)
        is_fused_date = bool(re.search(r'\b\d{1,2}(?:19[1-8]\d)\b|\b(?:19[1-8]\d)\d{1,2}\b', digits_only))
        if is_fused_date:
            score -= 70  # Falešné datum schválení v razítku

        # 3. Penalizace čísel změn v tabulce změn / revizí (Änderungs-Nr. / Změny)
        if _RE_CHANGE_LABEL.search(ctx_before) or _RE_CHANGE_LABEL.search(ctx_after):
            score -= 100

        # 4. Posílení u označení čísla výkresu (pouze pokud to není změna)
        elif _RE_DRAWING_LABEL.search(ctx_before) or _RE_DRAWING_LABEL.search(ctx_after):
            score += 35

        # 5. Penalizace norem ČSN / DIN / materiálu / měřítka – why: okno 60 lépe zachytí vzdálené labely
        if _RE_STANDARD_LABEL.search(ctx_before) or _RE_STANDARD_LABEL.search(ctx_after):
            score -= 80

        # 6. Penalizace jakostí ocelí – why: 12020 v materiálu nesmí být výkres, ale velké písmo v razítku může být výkres
        if digits_only in _KNOWN_STEEL_GRADES and not (_RE_DRAWING_LABEL.search(ctx_before) or _RE_DRAWING_LABEL.search(ctx_after)):
            score -= 50  # why: zmírněno z -70, aby velké písmo v razítku nebylo tvrdě shazováno

        # Bonusy pro technická čísla výkresů
        if 5 <= digits_count <= 14 and not is_fused_date:
            # why: 5-místné 00210 je validní legacy, nepenalizovat pokud začíná 0
            if digits_count == 5 and digits_only.startswith('0'):
                score += 15
            elif digits_only not in _KNOWN_STEEL_GRADES:
                score += 25
        if suffix:
            # why: K20/sp/R_L jsou silné indikátory výkresu, vyšší bonus než obecné a-b
            if re.match(r'K\d|sp|R_L', suffix, re.IGNORECASE):
                score += 20
            else:
                score += 10
        if part_num:
            score += 10

        candidates.append({
            "candidate": full_candidate,
            "part": part_num,
            "has_r_l": has_r_l,
            "index": start_idx,
            "score": score
        })

    # 2. Hledání alfanumerických formátů pokud nic nenalezeno
    if not candidates:
        for match in _RE_ALPHANUM_DRAWING.finditer(text_clean):
            base_num = match.group(1)
            suffix = match.group(2) or ''
            candidates.append({
                "candidate": base_num + suffix,
                "part": None,
                "has_r_l": has_r_l,
                "index": match.start(),
                "score": len(base_num) * 8
            })

    if candidates:
        # Seřadit podle skóre (nejvyšší priorita) a pozice
        candidates.sort(key=lambda c: (c["score"], -c["index"]), reverse=True)
        best = candidates[0]

        # Pokud nejlepší kandidát má záporné skóre (např. izolovaný datum), ignorovat
        if best["score"] < 0:
            return None

        num_str = best["candidate"]
        if best["part"]:
            num_str += f"_{best['part']}"
        elif best["has_r_l"]:
            num_str += " R_L"

        logger.debug("Extrahováno číslo výkresu: %s (skóre %d)", num_str, best["score"])
        return num_str

    return None


def disambiguate_drawing_number(cand: str) -> str:
    """
    Opravuje typické záměny znaků ve starých písmech razítek:
    - J/I/l na začátku 6místného čísla -> 1 (např. J00416 -> 100416)
    - o/O uvnitř čísla -> 0 (např. 1004o -> 10040)
    - _5 na konci sestav -> sp1 (např. 100541_5 -> 100541sp1)
    - ab / a_b -> a-b
    """
    if not cand:
        return cand

    # 1. Záměna písmene 'o' / 'O' za nulu v číselných řadách
    if re.search(r'\d[oO]|\b[oO]\d', cand):
        cand = re.sub(r'(?<=\d)[oO]', '0', cand)
        cand = re.sub(r'[oO](?=\d)', '0', cand)

    # 2. Záměna 'J'/'I'/'l' na začátku čísla 10xxxx
    if re.match(r'^[JIl]00\d{3}', cand):
        cand = '1' + cand[1:]

    # 3. Sestavy a soupravy (sp1)
    if cand.endswith('_5') or cand.endswith('_s'):
        cand = cand[:-2] + 'sp1'
    elif cand.endswith('sp') or cand.endswith('SP'):
        cand = cand + '1'

    # 4. Rozsahy indexů a-b
    cand = re.sub(r'([a-e])_([a-e])', r'\1-\2', cand)
    cand = re.sub(r'([a-e])([a-e])$', r'\1-\2', cand)

    return cand


def extract_best_from_ocr_boxes(ocr_results: list[list]) -> tuple[str | None, float]:
    """
    Vyhodnotí všechny bounding boxy z OCR s využitím geometrie, výšky písma
    a prostorových vztahů v razítku.
    Vrací (nejlepší_číslo, spolehlivost_skóre).
    """
    if not ocr_results:
        return None, 0.0

    valid_boxes = []
    heights = []

    for item in ocr_results:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        bbox = item[0]
        text = str(item[1]).strip()
        conf = float(item[2]) if len(item) > 2 else 0.8

        if not text:
            continue

        # Výpočet výšky a středu boxu
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            ys = [p[1] for p in bbox if isinstance(p, (list, tuple)) and len(p) >= 2]
            xs = [p[0] for p in bbox if isinstance(p, (list, tuple)) and len(p) >= 2]
            h = max(ys) - min(ys) if ys else 15.0
            w = max(xs) - min(xs) if xs else 50.0
            cy = sum(ys) / len(ys) if ys else 0.0
            cx = sum(xs) / len(xs) if xs else 0.0
        else:
            h, w, cy, cx = 15.0, 50.0, 0.0, 0.0

        heights.append(h)
        valid_boxes.append({
            "bbox": bbox, "text": text, "conf": conf,
            "h": h, "w": w, "cx": cx, "cy": cy
        })

    if not valid_boxes:
        return None, 0.0

    median_h = sorted(heights)[len(heights) // 2] if heights else 15.0
    median_h = max(median_h, 5.0)

    candidates = []

    # 1. Horizontální spojování sousedních boxů – why: 0.5*median_h dělí zkreslené řádky, 0.8 je robustnější
    row_clusters = []
    sorted_by_y = sorted(valid_boxes, key=lambda b: b["cy"])
    for box in sorted_by_y:
        added = False
        for cluster in row_clusters:
            if abs(cluster["cy"] - box["cy"]) < (0.8 * median_h):
                cluster["boxes"].append(box)
                cluster["cy"] = sum(b["cy"] for b in cluster["boxes"]) / len(cluster["boxes"])
                added = True
                break
        if not added:
            row_clusters.append({"cy": box["cy"], "boxes": [box]})

    for cluster in row_clusters:
        if len(cluster["boxes"]) >= 2:
            cluster["boxes"].sort(key=lambda b: b["cx"])
            # why: GLM dává 442 01075 029 4 s mezerami – clean_text je spojí
            raw_merged = " ".join([b["text"] for b in cluster["boxes"]])
            cleaned_merged = clean_text_for_numbers(raw_merged)
            # zkusit přímo 4420\d{8,10} po vyčištění
            match_long = re.search(r'\b(4420\d{8,10})\b', cleaned_merged)
            if match_long:
                long_cand = match_long.group(1)
                candidates.append((long_cand, 85.0))
            else:
                # zkusit i na raw s mezerami – iterativní glue už je v clean_text
                cand_merged = extract_drawing_number(cleaned_merged)
                if cand_merged:
                    cand_merged = disambiguate_drawing_number(cand_merged)
                    if len(re.sub(r'\D', '', cand_merged)) >= 5:  # why: 5-místné 00210 je validní
                        candidates.append((cand_merged, 45.0))

    # 2. Vyhodnocení jednotlivých bounding boxů
    for box in valid_boxes:
        raw_num = extract_drawing_number(box["text"])
        if not raw_num:
            continue

        cand_num = disambiguate_drawing_number(raw_num)
        h_ratio = box["h"] / median_h
        digits_count = len(re.sub(r'\D', '', cand_num))

        # Geometrické skóre:
        box_score = (h_ratio * 25.0) + (box["conf"] * 20.0)

        if 5 <= digits_count <= 14:
            box_score += 35.0
        elif digits_count == 4:
            # why: cand_num může obsahovat písmena (např. "19ab") — chránit int() před ValueError
            if cand_num.startswith("19") and cand_num[:4].isdigit() and 1900 <= int(cand_num[:4]) <= 1999:
                box_score -= 60.0  # Letopočet
            else:
                box_score += 10.0

        t_lower = box["text"].lower()
        if any(k in t_lower for k in ["vykr", "cisl", "nr", "no", "modell", "zeichnung"]):
            box_score += 25.0

        candidates.append((cand_num, box_score))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_num, best_score = candidates[0]
        if best_score > 0:
            return best_num, best_score

    # Fallback na celkový sloučený text
    full_text = " ".join([b["text"] for b in valid_boxes])
    fallback = extract_drawing_number(full_text)
    if fallback:
        fallback = disambiguate_drawing_number(fallback)
    return fallback, 15.0 if fallback else 0.0
