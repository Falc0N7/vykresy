"""Testy pro pomocné funkce gui.py (bez Tkinter)."""
import gui


def test_sanitize_filename():
    assert gui.sanitize_filename("test<>file*.tif") == "testfile.tif"
    assert gui.sanitize_filename("file...   ") == "file"
    assert gui.sanitize_filename("a/b\\c:d") == "abcd"
    assert gui.sanitize_filename("") == ""


def test_clean_only_drawing_number():
    assert gui.clean_only_drawing_number("100416 (A4).tif") == "100416"
    assert gui.clean_only_drawing_number("100416 (A4)") == "100416"
    assert gui.clean_only_drawing_number("E103322.tif") == "E103322"
    assert gui.clean_only_drawing_number("") == ""


def test_export_to_excel():
    import os
    import tempfile
    items = [("100416", "Hřídel", "A4"), ("100999", "Páka", "A3")]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "test.xlsx")
        assert gui.export_to_excel(out, items) is True
        assert os.path.exists(out)
        # prázdné položky → False
        out2 = os.path.join(td, "empty.xlsx")
        assert gui.export_to_excel(out2, []) is False
