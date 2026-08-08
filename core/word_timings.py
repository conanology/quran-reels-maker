"""
Per-word recitation timings from the Quran.com v4 API.

The previous implementation asked /recitations/{id}/by_chapter/{surah} with
segments=true. That endpoint stopped returning segments, and the caller fell
back to evenly estimated timings after only an info-level log, so a broken sync
was indistinguishable from a working one. Timings now come from the verse
endpoint, and a mapped reciter that returns nothing usable raises.
"""
from dataclasses import dataclass
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


def parse_segments(raw_segments: List[Any]) -> Tuple[List[int], List[int]]:
    """
    Pull start and end milliseconds out of the API's segment tuples.

    Tuples carry four values, (index, position, start_ms, end_ms), and arrive
    as ints for some reciters and strings for others, so the last two are taken
    positionally and coerced.
    """
    starts: List[int] = []
    ends: List[int] = []

    for segment in raw_segments:
        if len(segment) < 2:
            raise WordTimingError(f"segment too short to hold timings: {segment}")
        try:
            start, end = int(segment[-2]), int(segment[-1])
        except (TypeError, ValueError) as e:
            raise WordTimingError(f"non-numeric segment {segment}: {e}") from e

        if end < start:
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

    verse = payload.get("verse") or {}
    audio = verse.get("audio") or {}
    raw_segments = audio.get("segments") or []

    words = [
        w.get("text_uthmani", "")
        for w in verse.get("words", [])
        if w.get("char_type_name") == "word"
    ]

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
