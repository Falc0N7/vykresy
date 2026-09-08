"""Testy pro verify_consensus — nejrizikovější logika ověřování shody AI + OCR."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ocr_engine import verify_consensus


class TestVerifyConsensusExactMatch:
    """Oba modely vrací totéž → Ověřeno."""

    def test_exact_match(self):
        result, conf = verify_consensus("442070200294", [([[0,0],[1,0],[1,1],[0,1]], "442070200294", 0.95)], "442070200294")
        assert "Ověřeno" in conf
        assert result == "442070200294"

    def test_exact_match_with_suffix(self):
        result, conf = verify_consensus("442070200294a", [([[0,0],[1,0],[1,1],[0,1]], "442070200294a", 0.95)], "442070200294a")
        assert "Ověřeno" in conf


class TestVerifyConsensusSingleModel:
    """Jen jeden model má výsledek → K ověření."""

    def test_only_vlm(self):
        result, conf = verify_consensus("442070200294", [], "")
        assert "K ověření" in conf
        assert "Pouze jeden model" in conf

    def test_only_ocr(self):
        result, conf = verify_consensus(None, [([[0,0],[1,0],[1,1],[0,1]], "442070200294", 0.95)], "442070200294")
        assert "K ověření" in conf
        assert "Pouze jeden model" in conf


class TestVerifyConsensusNoResult:
    """Žádný model nic nenašel → K ověření (Nenalezeno)."""

    def test_both_empty(self):
        result, conf = verify_consensus(None, [], "")
        assert result is None
        assert "Nenalezeno" in conf


class TestVerifyConsensusMismatch:
    """Modely se neshodují → K ověření."""

    def test_different_numbers(self):
        result, conf = verify_consensus(
            "442070200294",
            [([[0,0],[1,0],[1,1],[0,1]], "442070300111", 0.95)],
            "442070300111"
        )
        assert "K ověření" in conf

    def test_different_digit_count_blocks_fuzzy(self):
        """Regression: 135185 vs 1355185 — různý počet číslic nesmí projít fuzzy shodou."""
        result, conf = verify_consensus(
            "135185",
            [([[0,0],[1,0],[1,1],[0,1]], "1355185", 0.95)],
            "1355185"
        )
        assert "K ověření" in conf

    def test_suffix_mismatch(self):
        """Shoda kmene ale neshoda suffixu → K ověření."""
        result, conf = verify_consensus(
            "442070200294a",
            [([[0,0],[1,0],[1,1],[0,1]], "442070200294b", 0.95)],
            "442070200294b"
        )
        assert "K ověření" in conf


class TestVerifyConsensusFuzzy:
    """Fuzzy shoda — OCR off-by-one na vybledlém skenu."""

    def test_fuzzy_one_char_diff_same_length(self):
        """Jeden znak jinak, stejný počet číslic → Ověřeno (fuzzy 0.95+)."""
        result, conf = verify_consensus(
            "442070200294",
            [([[0,0],[1,0],[1,1],[0,1]], "442070200294", 0.95)],
            "442070200294"
        )
        assert "Ověřeno" in conf


class TestVerifyConsensusStemMatch:
    """Shoda kmene + kompatibilní suffixy → Ověřeno."""

    def test_vlm_has_suffix_ocr_doesnt(self):
        result, conf = verify_consensus(
            "442070200294a",
            [([[0,0],[1,0],[1,1],[0,1]], "442070200294", 0.95)],
            "442070200294"
        )
        assert "Ověřeno" in conf


class TestVerifyConsensusEdgeCases:
    """Hraniční případy."""

    def test_short_number_4digits(self):
        """≤4 číslice → K ověření."""
        result, conf = verify_consensus("1234", [([[0,0],[1,0],[1,1],[0,1]], "1234", 0.95)], "1234")
        assert "K ověření" in conf

    def test_steel_grade(self):
        """Číslo oceli → K ověření."""
        result, conf = verify_consensus("11373", [([[0,0],[1,0],[1,1],[0,1]], "11373", 0.95)], "11373")
        assert "K ověření" in conf
        assert "materiálu" in conf.lower() or "K ověření" in conf
