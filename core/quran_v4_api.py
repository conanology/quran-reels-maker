"""
Quran API V4 - Fetch Quranic data from Quran.com API V4
Used for getting precise word-level timestamps and audio.
"""
import requests
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger
from requests.exceptions import RequestException

from core.utils import retry_with_backoff
from config.settings import DATABASE_DIR

# Constants
API_BASE = "https://api.quran.com/api/v4"
CACHE_FILE = DATABASE_DIR / "quran_v4_cache.json"

# In-memory cache
_cache: Dict[str, Any] = {}

def _load_cache():
    """Load cache from disk"""
    global _cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _cache = json.load(f)
            logger.debug(f"Loaded {len(_cache)} cached V4 entries")
        except Exception as e:
            logger.warning(f"Could not load V4 cache: {e}")
            _cache = {}

def _save_cache():
    """Save cache to disk"""
    try:
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save V4 cache: {e}")

# Load on import
_load_cache()

@retry_with_backoff(max_retries=3, exceptions=(RequestException,))
def get_verse_audio_with_timings(reciter_id: int, surah: int, ayah: int) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Fetch audio URL and word timings for a specific verse.
    
    Args:
        reciter_id: Quran.com Reciter ID (e.g. 7 for Mishary)
        surah: Surah number
        ayah: Ayah number
        
    Returns:
        Tuple[audio_url, list_of_word_segments]
        word_segments is a list of dicts: {'word': 'Text', 'start_ms': 0, 'end_ms': 500}
    """
    # Create a unique cache key
    cache_key = f"audio_v4:{reciter_id}:{surah}:{ayah}"
    if cache_key in _cache:
        return _cache[cache_key]['audio_url'], _cache[cache_key]['segments']
    
    # 1. Fetch Audio URL & Timestamps
    # Endpoint: /recitations/{reciter_id}/by_ayah/{surah}:{ayah}
    # Note: 'recitations' endpoint might return segments if segments=true is passed?
    # Let's try the endpoint we verified: recitations/{id}/by_chapter/{chapter}?segments=true
    # But filtering for just one ayah is inefficient if we do it every time.
    # However, API V4 has /verses/by_key/{verse_key}/audio?reciter={id} which might work.
    
    # Let's stick to the method we verified: Verse-by-Verse list for the chapter.
    # To avoid fetching the whole chapter list every time, we should probably fetch the whole chapter ONCE
    # and cache ALL ayahs in it.
    
    # Check if we have *any* data for this chapter/reciter cached? 
    # For simplicity, let's just fetch the whole chapter list if not cached.
    # Using the verified endpoint: recitations/{id}/by_chapter/{chapter}?segments=true
    
    url = f"{API_BASE}/recitations/{reciter_id}/by_chapter/{surah}?segments=true"
    
    try:
        logger.info(f"Fetching V4 audio data for Surah {surah}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        audio_files = data.get('audio_files', [])
        found_data = None
        
        # Process and cache ALL files in the response
        verse_key_prefix = f"{surah}:"
        
        for file_data in audio_files:
            v_key = file_data.get('verse_key') # e.g. "112:1"
            if not v_key:
                continue
                
            # Parse segments
            # V4 segments format: [ [word_idx, start_ms, end_ms, duration_ms], ... ] OR timestamps key
            # From investigation: key is 'timestamps'
            # timestamps: { segments: [ [0, start, end], ... ] } OR just list of lists?
            # Let's handle generic case or what we saw: "timestamps" -> ...
            
            segments = []
            
            # The 'timestamps' key usually contains a structure
            # If it's just a list of lists: [[0, 100, 200], [1, 250, 400]]
            ts_data = file_data.get('timestamps')
            raw_segments = []
            
            if isinstance(ts_data, dict) and 'segments' in ts_data:
                raw_segments = ts_data['segments']
                logger.debug(f"Found {len(raw_segments)} segments in dict")
            elif isinstance(ts_data, list):
                raw_segments = ts_data
                logger.debug(f"Found {len(raw_segments)} segments in list")
            
            # We also need the TEXT of the words to map indices to words.
            # This is hard because this endpoint ONLY returns audio.
            # We need to fetch text separately or rely on 'word_index' matching standard uthmani text.
            # For now, let's store the raw timing [start_ms, end_ms] mapped to word index.
            
            segments_processed = []
            for seg in raw_segments:
                # Expecting [word_index, start_ms, end_ms]
                if len(seg) >= 3:
                     segments_processed.append({
                         'word_index': seg[0],
                         'start_ms': seg[1],
                         'end_ms': seg[2]
                     })
            
            raw_url = file_data.get('url')
            if raw_url and not raw_url.startswith('http'):
                if raw_url.startswith('//'):
                    raw_url = f"https:{raw_url}"
                else:
                    raw_url = f"https://verses.quran.com/{raw_url}"
                
            entry = {
                'audio_url': raw_url,
                'segments': segments_processed
            }
            
            # Cache it
            # v_key is "112:1". Split it.
            try:
                s_str, a_str = v_key.split(':')
                k_int = f"audio_v4:{reciter_id}:{int(s_str)}:{int(a_str)}"
                _cache[k_int] = entry
                
                if int(s_str) == surah and int(a_str) == ayah:
                    found_data = entry
                    
            except ValueError:
                pass

        _save_cache()
        
        if found_data:
             return found_data['audio_url'], found_data['segments']
        else:
            logger.warning(f"Audio for {surah}:{ayah} not found in API response")
            return None, []

    except Exception as e:
        logger.error(f"Failed to fetch V4 audio: {e}")
        return None, []

@retry_with_backoff(max_retries=3, exceptions=(RequestException,))
def get_verse_words(surah: int, ayah: int) -> List[Dict[str, Any]]:
    """
    Fetch word text (Uthmani) for a verse to match with timings.
    Endpoint: /verses/by_key/{verse_key}?words=true
    """
    cache_key = f"words:{surah}:{ayah}"
    if cache_key in _cache:
        return _cache[cache_key]
        
    # Correct parameter is word_fields, not fields
    url = f"{API_BASE}/verses/by_key/{surah}:{ayah}?words=true&word_fields=text_uthmani"
    
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        # Structure: { verse: { words: [ ... ] } }
        words_data = data.get('verse', {}).get('words', [])
        
        cleaned_words = []
        for w in words_data:
            # Skip "end marker" if present (usually has char_type_name="end")
            if w.get('char_type_name') == 'end':
                continue
                
            # Get text: try text_uthmani, fall back to text
            text_val = w.get('text_uthmani', w.get('text'))
            
            cleaned_words.append({
                'text': text_val,
                'transliteration': w.get('transliteration', {}).get('text'),
                'position': w.get('position') # 1-based index usually
            })
            
        _cache[cache_key] = cleaned_words
        _save_cache()
        return cleaned_words
        
    except Exception as e:
        logger.error(f"Failed to fetch words for {surah}:{ayah}: {e}")
        return []
