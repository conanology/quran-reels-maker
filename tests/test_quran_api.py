"""
Tests for core.quran_api module
"""
import pytest
from unittest.mock import patch, Mock

from core.quran_api import (
    get_surah_name,
    get_verse_count,
    validate_verse_range,
    absolute_to_surah_ayah,
    surah_ayah_to_absolute,
    get_total_verses,
    get_total_surahs
)


class TestGetSurahName:
    """Tests for get_surah_name function"""
    
    def test_arabic_name_first_surah(self):
        """Should return Arabic name for Al-Fatihah"""
        assert get_surah_name(1, "ar") == "الفاتحة"
    
    def test_arabic_name_last_surah(self):
        """Should return Arabic name for An-Nas"""
        assert get_surah_name(114, "ar") == "الناس"
    
    def test_english_name_first_surah(self):
        """Should return English name for Al-Fatihah"""
        assert get_surah_name(1, "en") == "Al-Fatihah"
    
    def test_english_name_middle_surah(self):
        """Should return English name for Ya-Sin (36)"""
        assert get_surah_name(36, "en") == "Ya-Sin"
    
    def test_default_language_is_arabic(self):
        """Should default to Arabic when no language specified"""
        # Note: the default in the function is 'ar'
        assert get_surah_name(112) == "الإخلاص"


class TestGetVerseCount:
    """Tests for get_verse_count function"""
    
    def test_fatihah_has_7_verses(self):
        """Al-Fatihah should have 7 verses"""
        assert get_verse_count(1) == 7
    
    def test_baqarah_has_286_verses(self):
        """Al-Baqarah should have 286 verses"""
        assert get_verse_count(2) == 286
    
    def test_ikhlas_has_4_verses(self):
        """Al-Ikhlas should have 4 verses"""
        assert get_verse_count(112) == 4
    
    def test_invalid_surah_returns_zero(self):
        """Invalid surah should return 0"""
        assert get_verse_count(999) == 0


class TestValidateVerseRange:
    """Tests for validate_verse_range function"""
    
    def test_valid_range_unchanged(self):
        """Valid range should be returned unchanged"""
        start, end = validate_verse_range(1, 1, 7)
        assert start == 1
        assert end == 7
    
    def test_clamps_end_to_max(self):
        """End beyond max should be clamped"""
        start, end = validate_verse_range(1, 1, 100)  # Fatihah has only 7
        assert end == 7
    
    def test_clamps_start_to_one(self):
        """Start below 1 should be clamped to 1"""
        start, end = validate_verse_range(1, 0, 5)
        assert start == 1
    
    def test_ensures_start_not_greater_than_end(self):
        """Start should never be greater than end"""
        start, end = validate_verse_range(1, 5, 2)
        assert start <= end


class TestAbsoluteToSurahAyah:
    """Tests for absolute_to_surah_ayah function"""
    
    def test_first_verse(self):
        """Verse 1 should be Surah 1, Ayah 1"""
        surah, ayah = absolute_to_surah_ayah(1)
        assert surah == 1
        assert ayah == 1
    
    def test_eighth_verse(self):
        """Verse 8 should be Surah 2, Ayah 1 (after 7 verses of Fatihah)"""
        surah, ayah = absolute_to_surah_ayah(8)
        assert surah == 2
        assert ayah == 1
    
    def test_last_verse_fatihah(self):
        """Verse 7 should be Surah 1, Ayah 7"""
        surah, ayah = absolute_to_surah_ayah(7)
        assert surah == 1
        assert ayah == 7


class TestSurahAyahToAbsolute:
    """Tests for surah_ayah_to_absolute function"""
    
    def test_first_verse(self):
        """Surah 1, Ayah 1 should be absolute verse 1"""
        assert surah_ayah_to_absolute(1, 1) == 1
    
    def test_first_verse_baqarah(self):
        """Surah 2, Ayah 1 should be absolute verse 8"""
        assert surah_ayah_to_absolute(2, 1) == 8
    
    def test_round_trip(self):
        """Converting to absolute and back should give same result"""
        original_surah, original_ayah = 36, 15
        absolute = surah_ayah_to_absolute(original_surah, original_ayah)
        back_surah, back_ayah = absolute_to_surah_ayah(absolute)
        assert back_surah == original_surah
        assert back_ayah == original_ayah


class TestTotals:
    """Tests for total counting functions"""
    
    def test_total_surahs_is_114(self):
        """Should have 114 surahs"""
        assert get_total_surahs() == 114
    
    def test_total_verses_is_6236(self):
        """Should have 6236 total verses"""
        assert get_total_verses() == 6236
