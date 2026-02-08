"""
Quran API - Fetch Quranic text and metadata from online APIs
"""
import json
import requests
from pathlib import Path
from requests.exceptions import RequestException
from typing import Optional, Dict, Any
from loguru import logger

from core.utils import retry_with_backoff
from config.settings import (
    QURAN_TEXT_API,
    VERSE_COUNTS,
    SURAH_NAMES_AR,
    SURAH_NAMES_EN,
    DATABASE_DIR
)


class QuranAPIError(Exception):
    """Custom exception for Quran API errors"""
    pass


# =============================================================================
# LOCAL CACHE for Quran text (reduces API calls)
# =============================================================================

CACHE_FILE = DATABASE_DIR / "quran_cache.json"
_cache: Dict[str, str] = {}

def _load_cache():
    """Load cache from disk"""
    global _cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _cache = json.load(f)
            logger.debug(f"Loaded {len(_cache)} cached entries")
        except Exception as e:
            logger.warning(f"Could not load cache: {e}")
            _cache = {}

def _save_cache():
    """Save cache to disk"""
    try:
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save cache: {e}")

# Load cache on module import
_load_cache()


@retry_with_backoff(max_retries=3, exceptions=(RequestException, QuranAPIError))
def get_ayah_text(surah: int, ayah: int) -> str:
    """
    Fetch the Uthmani text of a specific ayah.
    
    Args:
        surah: Surah number (1-114)
        ayah: Ayah number within the surah
        
    Returns:
        The Arabic text of the ayah in Uthmani script
        
    Raises:
        QuranAPIError: If the API request fails
    """
    # Check cache first
    cache_key = f"text:{surah}:{ayah}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    url = QURAN_TEXT_API.format(surah=surah, ayah=ayah)
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 200 and "data" in data:
            text = data["data"]["text"]
            # Cache the result
            _cache[cache_key] = text
            _save_cache()
            return text
        else:
            raise QuranAPIError(f"Unexpected API response: {data}")
            
    except requests.RequestException as e:
        logger.error(f"Failed to fetch ayah {surah}:{ayah} - {e}")
        raise QuranAPIError(f"Failed to fetch ayah {surah}:{ayah}") from e


# Translation editions available
TRANSLATION_EDITIONS = {
    "en": "en.sahih",      # Sahih International (English)
    "ur": "ur.jalandhry",  # Urdu
    "id": "id.indonesian", # Indonesian
    "tr": "tr.diyanet",    # Turkish
    "fr": "fr.hamidullah", # French
    "de": "de.bubenheim",  # German
}


@retry_with_backoff(max_retries=2, exceptions=(RequestException,))
def get_ayah_translation(surah: int, ayah: int, language: str = "en") -> Optional[str]:
    """
    Fetch the translation of a specific ayah.
    
    Args:
        surah: Surah number (1-114)
        ayah: Ayah number within the surah
        language: Language code ('en', 'ur', 'id', etc.)
        
    Returns:
        The translated text, or None if translation fails
    """
    # Check cache first
    cache_key = f"trans:{language}:{surah}:{ayah}"
    if cache_key in _cache:
        return _cache[cache_key]
    
    edition = TRANSLATION_EDITIONS.get(language, "en.sahih")
    url = f"https://api.alquran.cloud/v1/ayah/{surah}:{ayah}/{edition}"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 200 and "data" in data:
            text = data["data"]["text"]
            # Cache the result
            _cache[cache_key] = text
            _save_cache()
            return text
        return None
        
    except Exception as e:
        logger.warning(f"Translation fetch failed for {surah}:{ayah}: {e}")
        return None


def get_multiple_ayat(surah: int, start_ayah: int, end_ayah: int) -> list[Dict[str, Any]]:
    """
    Fetch multiple consecutive ayat from a surah.
    
    Args:
        surah: Surah number (1-114)
        start_ayah: Starting ayah number
        end_ayah: Ending ayah number (inclusive)
        
    Returns:
        List of dicts with ayah number and text
    """
    ayat = []
    for ayah_num in range(start_ayah, end_ayah + 1):
        text = get_ayah_text(surah, ayah_num)
        ayat.append({
            "surah": surah,
            "ayah": ayah_num,
            "text": text
        })
        logger.debug(f"Fetched ayah {surah}:{ayah_num}")
    
    return ayat


def get_full_text(surah: int, start_ayah: int, end_ayah: int) -> str:
    """
    Get the combined text of multiple ayat as a single string.
    
    Args:
        surah: Surah number (1-114)
        start_ayah: Starting ayah number
        end_ayah: Ending ayah number (inclusive)
        
    Returns:
        Combined Arabic text with verse markers
    """
    ayat = get_multiple_ayat(surah, start_ayah, end_ayah)
    
    # Combine texts with verse number markers
    combined = " ".join([
        f"{a['text']} ﴿{a['ayah']}﴾" for a in ayat
    ])
    
    return combined


def get_surah_name(surah: int, language: str = "ar") -> str:
    """
    Get the name of a surah.
    
    Args:
        surah: Surah number (1-114)
        language: 'ar' for Arabic, 'en' for English
        
    Returns:
        Surah name in the requested language
    """
    index = surah - 1
    if language == "ar":
        return SURAH_NAMES_AR[index]
    return SURAH_NAMES_EN[index]


def get_verse_count(surah: int) -> int:
    """
    Get the number of verses in a surah.
    
    Args:
        surah: Surah number (1-114)
        
    Returns:
        Number of verses in the surah
    """
    return VERSE_COUNTS.get(surah, 0)


def validate_verse_range(surah: int, start_ayah: int, end_ayah: int) -> tuple[int, int]:
    """
    Validate and adjust verse range to be within surah bounds.
    
    Args:
        surah: Surah number (1-114)
        start_ayah: Starting ayah number
        end_ayah: Ending ayah number
        
    Returns:
        Tuple of (validated_start, validated_end)
    """
    max_ayah = get_verse_count(surah)
    
    # Clamp to valid range
    start = max(1, min(start_ayah, max_ayah))
    end = max(start, min(end_ayah, max_ayah))
    
    return start, end


def get_total_verses() -> int:
    """Get total number of verses in the entire Quran."""
    return sum(VERSE_COUNTS.values())


def get_total_surahs() -> int:
    """Get total number of surahs in the Quran."""
    return len(VERSE_COUNTS)


# Utility function to convert absolute verse number to surah:ayah
def absolute_to_surah_ayah(absolute_verse: int) -> tuple[int, int]:
    """
    Convert an absolute verse number (1 to 6236) to surah:ayah format.
    
    Args:
        absolute_verse: Verse number counting from start of Quran
        
    Returns:
        Tuple of (surah_number, ayah_number)
    """
    cumulative = 0
    for surah_num in range(1, 115):
        surah_verses = VERSE_COUNTS[surah_num]
        if cumulative + surah_verses >= absolute_verse:
            ayah = absolute_verse - cumulative
            return surah_num, ayah
        cumulative += surah_verses
    
    # Return last verse if out of range
    return 114, 6


def surah_ayah_to_absolute(surah: int, ayah: int) -> int:
    """
    Convert surah:ayah to absolute verse number.
    
    Args:
        surah: Surah number (1-114)
        ayah: Ayah number within surah
        
    Returns:
        Absolute verse number (1 to 6236)
    """
    absolute = 0
    for s in range(1, surah):
        absolute += VERSE_COUNTS[s]
    return absolute + ayah
