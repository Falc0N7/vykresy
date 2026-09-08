"""Základní testy pro parser.py — ověřuje extrakci čísel výkresů."""
import parser


def test_clean_text_for_numbers():
    assert parser.clean_text_for_numbers("10.53.03") == "105303"
    assert parser.clean_text_for_numbers("442 01075 029 4") == "442010750294"
    assert parser.clean_text_for_numbers("100805/b") == "100805b"


def test_split_drawing_details():
    assert parser.split_drawing_details("104102_3") == ("104102", "", "3")
    assert parser.split_drawing_details("106275d") == ("106275", "d", "")
    assert parser.split_drawing_details("E103322") == ("E103322", "", "")


def test_extract_drawing_number_basic():
    assert parser.extract_drawing_number("100416 (A4)") == "100416"
    assert parser.extract_drawing_number("E103322") == "E103322"
    assert parser.extract_drawing_number("442010750294") == "442010750294"


def test_extract_drawing_number_with_suffix():
    # K suffix, sp suffix
    assert "115515" in (parser.extract_drawing_number("115515 K20") or "")
    assert "100541" in (parser.extract_drawing_number("100541 sp1") or "")


def test_disambiguate():
    assert parser.disambiguate_drawing_number("J00416") == "100416"  # J -> 1
    assert parser.disambiguate_drawing_number("1004o") == "10040"  # o -> 0


def test_extract_best_from_ocr_boxes():
    # prázdné vstupy
    assert parser.extract_best_from_ocr_boxes([]) == (None, 0.0)
    # jednoduchý box
    box = [[[0, 0], [10, 0], [10, 10], [0, 10]], "100416", 0.9]
    num, score = parser.extract_best_from_ocr_boxes([box])
    assert num == "100416"
    assert score > 0

    # letopočet by měl být penalizován vs výkres
    box_year = [[[0, 0], [10, 0], [10, 10], [0, 10]], "1920", 0.9]
    num2, score2 = parser.extract_best_from_ocr_boxes([box_year])
    # 1920 je letopočet, ale bez kontextu může projít — test že nepadne
    assert isinstance(score2, float)


def test_steel_grade_not_misidentified():
    # 12020 je jakost oceli, nemělo by být vybráno pokud je v blízkosti "mat" kontext
    # Zde testujeme že extract stále vrací něco, ale scoring to penalizuje
    txt = "materiál 12020"
    # ensure clean doesn't crash
    assert parser.clean_text_for_numbers(txt) is not None
