"""
Ayah Fetcher - Fetch ayah data with word timings and heuristic segmentation
"""
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional
from loguru import logger

from config.settings import RECITER_MAPPING_V4
from core.quran_api import get_ayah_text, get_ayah_translation
from core.quran_v4_api import get_verse_audio_with_timings, get_verse_words
from core.audio_processor import download_and_process_ayah


def build_heuristic_segments(
    word_texts: List[Dict[str, Any]],
    audio_duration: float,
) -> List[Dict[str, Any]]:
    """
    Generate timing segments based on character-length heuristic when
    the V4 API does not provide real timestamps.

    Args:
        word_texts: List of word dicts with 'text' and 'position' keys
        audio_duration: Total audio duration in seconds

    Returns:
        List of segment dicts with word_index, start_ms, end_ms
    """
    valid_words = [w for w in word_texts if w.get("text")]
    total_chars = sum(len(w["text"]) for w in valid_words)

    if total_chars == 0:
        return []

    char_duration = audio_duration / total_chars
    segments: List[Dict[str, Any]] = []
    current_pos = 0.0

    for w in valid_words:
        w_len = len(w["text"])
        w_dur_ms = w_len * char_duration * 1000

        segments.append(
            {
                "word_index": w.get("position"),
                "start_ms": current_pos * 1000,
                "end_ms": (current_pos * 1000) + w_dur_ms,
            }
        )
        current_pos += w_dur_ms / 1000.0

    return segments


def fetch_single_ayah(
    surah: int,
    ayah: int,
    reciter_key: str,
    audio_dir: Path,
    get_duration_fn: Callable[[Path], float],
    current_time: float,
    ayah_padding: float,
) -> Dict[str, Any]:
    """
    Fetch all data for a single ayah: audio, text, word timings, translation.

    Args:
        surah: Surah number
        ayah: Ayah number
        reciter_key: Reciter key from RECITERS dict
        audio_dir: Directory to save audio files
        get_duration_fn: Callable that returns duration in seconds for an audio Path
        current_time: The start time for this ayah in the overall timeline
        ayah_padding: Seconds of silence after this ayah

    Returns:
        Dict with keys: ayah, audio_path, audio_duration, text,
        word_segments, word_texts, translation, start_time, end_time, segment_end
    """
    v4_reciter_id = RECITER_MAPPING_V4.get(reciter_key)
    audio_url: Optional[str] = None
    word_segments: List[Dict[str, Any]] = []
    word_texts: List[Dict[str, Any]] = []

    if v4_reciter_id:
        try:
            audio_url, word_segments = get_verse_audio_with_timings(
                v4_reciter_id, surah, ayah
            )
            if word_segments:
                word_texts = get_verse_words(surah, ayah)
                logger.debug(
                    f"Got {len(word_segments)} segments and {len(word_texts)} words for {surah}:{ayah}"
                )
            else:
                word_texts = get_verse_words(surah, ayah)
                logger.info(
                    f"V4 segments missing for {surah}:{ayah}, will use heuristic estimation."
                )
        except Exception as e:
            logger.warning(f"V4 API failed for {surah}:{ayah}, falling back: {e}")

    # Download audio
    audio_path = download_and_process_ayah(
        reciter_key, surah, ayah, audio_dir, audio_url=audio_url
    )

    audio_duration = get_duration_fn(audio_path)

    # Heuristic segmentation fallback
    if not word_segments and word_texts:
        logger.info(
            f"Generating heuristic segments for Ayah {ayah} "
            f"(Duration: {audio_duration:.2f}s, Words: {len(word_texts)})"
        )
        word_segments = build_heuristic_segments(word_texts, audio_duration)

    text = get_ayah_text(surah, ayah)
    text_with_marker = f"{text} ﴿{ayah}﴾"

    translation = get_ayah_translation(surah, ayah, "en")

    return {
        "ayah": ayah,
        "audio_path": audio_path,
        "audio_duration": audio_duration,
        "text": text_with_marker,
        "word_segments": word_segments,
        "word_texts": word_texts,
        "translation": translation,
        "start_time": current_time,
        "end_time": current_time + audio_duration,
        "segment_end": current_time + audio_duration + ayah_padding,
    }
