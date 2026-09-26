"""
Per-word recitation timings from the Quran.com v4 API.

The previous implementation asked /recitations/{id}/by_chapter/{surah} with
segments=true. That endpoint stopped returning segments, and the caller fell
back to evenly estimated timings after only an info-level log, so a broken sync
was indistinguishable from a working one. Timings now come from the verse
endpoint, and a mapped reciter that returns nothing usable raises.
"""
from dataclasses import dataclass
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from loguru import logger

from config.settings import QURAN_V4_API_BASE, RECITER_MAPPING_V4

REQUEST_TIMEOUT_SECONDS = 30


class WordTimingError(Exception):
    """Timings were expected for this reciter but are missing or unusable."""


@dataclass(frozen=True)
class WordTiming:
    """Recited words and where each one falls in the ayah's audio."""

    words: List[str]
    starts_ms: List[int]
    ends_ms: List[int]
    audio_url: Optional[str]

    def spans_seconds(self) -> List[Tuple[float, float]]:
        """(start, end) per word, in seconds, for clip scheduling."""
        return [
            (start / 1000.0, end / 1000.0)
            for start, end in zip(self.starts_ms, self.ends_ms)
        ]

    def validate_for_audio(self, duration: float) -> None:
        """Validate the timings against the exact downloaded recording, not a estimate."""
        if not math.isfinite(duration) or duration <= 0:
            raise WordTimingError("Audio duration must be finite and positive")
        if not self.words or len(self.words) != len(self.starts_ms) or len(self.words) != len(self.ends_ms):
            raise WordTimingError("Word/timing counts disagree")
        if any(not isinstance(word, str) or not word.strip() for word in self.words):
            raise WordTimingError("Empty Quran word")
        # MP3 sample-frame measurement can differ by one frame; no origin shift.
        bound = duration * 1000 + 50
        previous = 0
        for start, end in zip(self.starts_ms, self.ends_ms):
            if start < previous or start < 0 or end <= start or end > bound:
                raise WordTimingError("Word timings do not fit the downloaded recording")
            previous = end


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not (isinstance(value, int) or isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value)):
        raise WordTimingError("Timing indices and milliseconds must be integers")
    return int(value)


def parse_segments(raw_segments: List[Any]) -> Tuple[List[int], List[int]]:
    """
    Pull start and end milliseconds out of the API's segment tuples.

    Tuples carry four values, (index, position, start_ms, end_ms), and arrive
    as ints for some reciters and strings for others, so the last two are taken
    positionally and coerced.
    """
    starts: List[int] = []
    ends: List[int] = []

    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, (list, tuple)) or len(segment) != 4:
            raise WordTimingError("Expected (index, position, start_ms, end_ms) segment")
        try:
            segment_index, position, start, end = map(_integer, segment)
        except (TypeError, ValueError) as e:
            raise WordTimingError(f"non-numeric segment {segment}: {e}") from e
        if segment_index != index or position != index + 1:
            raise WordTimingError("Segment word positions are missing, duplicated or out of order")
        if start < 0 or end <= start:
            raise WordTimingError(f"segment ends before it starts: {segment}")
        if starts and start < ends[-1]:
            raise WordTimingError(
                f"segments overlap or are not monotonic: {ends[-1]} then {start}"
            )

        starts.append(start)
        ends.append(end)

    return starts, ends


def _fetch_verse(reciter_id: int, surah: int, ayah: int) -> Dict[str, Any]:
    """Fetch one verse with its words and per-word audio segments."""
    url = (
        f"{QURAN_V4_API_BASE}/verses/by_key/{surah}:{ayah}"
        f"?audio={reciter_id}&words=true&word_fields=text_uthmani"
    )
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def get_word_timings(
    reciter_key: str, surah: int, ayah: int
) -> Optional[WordTiming]:
    """
    Word timings for one ayah, or None when the reciter has no upstream
    recitation at all.

    Raises WordTimingError when a mapped reciter returns unusable data, so a
    regression surfaces instead of quietly degrading to estimated timings.
    """
    reciter_id = RECITER_MAPPING_V4.get(reciter_key)
    if reciter_id is None:
        logger.info(f"No word timings published for reciter '{reciter_key}'")
        return None

    try:
        payload = _fetch_verse(reciter_id, surah, ayah)
    except Exception as e:
        raise WordTimingError(
            f"Could not fetch timings for {surah}:{ayah} ({reciter_key}): {e}"
        ) from e

    if not isinstance(payload, dict) or not isinstance(payload.get("verse"), dict):
        raise WordTimingError("Invalid verse response")
    verse = payload["verse"]
    if verse.get("verse_key") != f"{surah}:{ayah}":
        raise WordTimingError("Timing response identifies a different or missing verse reference")
    audio = verse.get("audio") or {}
    if not isinstance(audio, dict) or not isinstance(verse.get("words"), list):
        raise WordTimingError("Invalid audio/word response")
    raw_segments = audio.get("segments") or []
    word_rows = []
    for row in verse["words"]:
        if not isinstance(row, dict):
            raise WordTimingError("Invalid Quran word entry")
        if row.get("char_type_name") == "word":
            word_rows.append(row)
    if any(_integer(row.get("position")) != index + 1 for index, row in enumerate(word_rows)):
        raise WordTimingError("Quran word positions are missing or out of order")
    words = [row.get("text_uthmani", "") for row in word_rows]
    if not words or any(not isinstance(word, str) or not word.strip() for word in words):
        raise WordTimingError("Empty or missing Quran word text")
    if not isinstance(audio.get("url"), str) or not audio["url"].strip():
        raise WordTimingError("The timing response must identify its audio recording")

    if not raw_segments:
        raise WordTimingError(
            f"{reciter_key} returned no segments for {surah}:{ayah}"
        )

    starts, ends = parse_segments(raw_segments)

    if len(starts) != len(words):
        raise WordTimingError(
            f"{surah}:{ayah} ({reciter_key}) has {len(starts)} segments "
            f"but {len(words)} words"
        )

    return WordTiming(
        words=words,
        starts_ms=starts,
        ends_ms=ends,
        audio_url=audio.get("url"),
    )
