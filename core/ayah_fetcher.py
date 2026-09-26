"""
Ayah Fetcher - Fetch ayah data with word timings and heuristic segmentation
"""
from pathlib import Path
import hashlib
import json
from typing import Callable, Dict, List, Any, Optional
from loguru import logger

from config.settings import RECITER_MAPPING_V4, RECITERS
from core.quran_api import get_ayah_text, get_ayah_translation
from core.word_timings import get_word_timings
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
    if reciter_key not in RECITERS:
        raise ValueError(f"Unknown reciter: {reciter_key}")
    audio_dir.mkdir(parents=True, exist_ok=True)
    v4_reciter_id = RECITER_MAPPING_V4.get(reciter_key)
    audio_url: Optional[str] = None
    word_segments: List[Dict[str, Any]] = []
    word_texts: List[Dict[str, Any]] = []

    # Words, timing and audio originate in ONE verse response. Expected timing
    # errors propagate; selecting another recording would invalidate alignment.
    timing = get_word_timings(reciter_key, surah, ayah)
    if timing is not None:
        audio_url = timing.audio_url

    # Download audio
    audio_path = download_and_process_ayah(
        reciter_key, surah, ayah, audio_dir, audio_url=audio_url
    )

    audio_duration = get_duration_fn(audio_path)
    if timing is not None:
        timing.validate_for_audio(audio_duration)
        text = " ".join(timing.words)
    else:
        text = get_ayah_text(surah, ayah)
    text_with_marker = f"{text} ﴿{ayah}﴾"

    translation = get_ayah_translation(surah, ayah, "en")
    text_source = {
        "provider": "quran.com" if timing is not None else "alquran.cloud",
        "edition": "text_uthmani" if timing is not None else "quran-uthmani",
        "verse_key": f"{surah}:{ayah}",
        "text_sha256": hashlib.sha256(text_with_marker.encode("utf-8")).hexdigest(),
    }
    timing_source = {"status": "not_available", "word_count": 0}
    if timing is not None:
        timing_source = {"status": "validated", "provider": "quran.com", "recitation_id": v4_reciter_id,
            "word_count": len(timing.words), "segment_count": len(timing.starts_ms),
            "segments_sha256": hashlib.sha256(json.dumps(list(zip(timing.starts_ms, timing.ends_ms)),
                separators=(",", ":")).encode("utf-8")).hexdigest()}

    return {
        "ayah": ayah,
        "audio_path": audio_path,
        "audio_duration": audio_duration,
        "text": text_with_marker,
        "word_segments": word_segments,
        "word_texts": word_texts,
        "translation": translation,
        "word_timing": timing,
        "reciter_key": reciter_key,
        "recording_url": audio_url or "https://everyayah.com/data/" + RECITERS[reciter_key]["id"] + f"/{surah:03d}{ayah:03d}.mp3",
        "audio_source": "quran.com" if timing is not None else "everyayah.com",
        "text_source": text_source,
        "timing_source": timing_source,
        "start_time": current_time,
        "end_time": current_time + audio_duration,
        "segment_end": current_time + audio_duration + ayah_padding,
    }
