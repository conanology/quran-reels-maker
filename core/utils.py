"""
Utility functions for QuranReelsMaker
"""
import time
import functools
import hashlib
import json
import subprocess
import math
from pathlib import Path
from typing import Type, Tuple
from loguru import logger
from requests.exceptions import RequestException


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_media_streams(path: Path, expected_duration: float, width: int, height: int) -> dict:
    """Require complete audio/video streams before an artifact can be published."""
    if not math.isfinite(expected_duration) or expected_duration <= 0:
        raise ValueError("Invalid expected media duration")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError("Output must have exactly one video and one recitation audio stream")
    if (videos[0].get("width"), videos[0].get("height")) != (width, height):
        raise ValueError("Output dimensions disagree with the requested format")
    durations = [float(s.get("duration", "nan")) for s in (videos[0], audios[0])]
    if any(not math.isfinite(d) or abs(d - expected_duration) > 0.25 for d in durations):
        raise ValueError("Output stream durations do not preserve complete verse coverage")
    return {"video_duration": durations[0], "audio_duration": durations[1], "width": width, "height": height}


def write_media_manifest(video_path: Path, manifest: dict) -> dict:
    from core.runtime_safety import atomic_write_json
    streams = manifest.get("streams")
    if not isinstance(streams, dict) or not streams.get("width") or not streams.get("height"):
        raise ValueError("Verified stream dimensions are required before writing coverage")
    # A sidecar cannot claim verification from untrusted caller flags alone.
    verified_streams = verify_media_streams(video_path, manifest.get("duration_seconds"), streams["width"], streams["height"])
    data = dict(manifest, schema_version=1, verified=True, coverage_complete=True,
                video_sha256=file_sha256(video_path), streams=verified_streams)
    atomic_write_json(Path(str(video_path) + ".manifest.json"), data)
    return data


def load_media_manifest(video_path: Path) -> dict:
    """Reject missing, incomplete or changed generated content at publishing time."""
    with Path(str(video_path) + ".manifest.json").open(encoding="utf-8") as source:
        manifest = json.load(source)
    from config.settings import VERSE_COUNTS, RECITERS
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("verified") is not True or manifest.get("coverage_complete") is not True:
        raise ValueError("A verified, complete media manifest is required")
    if not manifest.get("coverage") or not manifest.get("verses") or not manifest.get("reciter_key"):
        raise ValueError("Media manifest is missing verse/reciter coverage")
    if manifest["reciter_key"] not in RECITERS:
        raise ValueError("Media manifest identifies an unknown reciter")
    expected = []
    for interval in manifest["coverage"]:
        if not isinstance(interval, dict):
            raise ValueError("Invalid manifest coverage interval")
        surah, start, end = interval.get("surah"), interval.get("start_ayah"), interval.get("end_ayah")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (surah, start, end)) or surah not in VERSE_COUNTS or not 1 <= start <= end <= VERSE_COUNTS[surah]:
            raise ValueError("Invalid manifest verse bounds")
        expected.extend((surah, ayah) for ayah in range(start, end + 1))
    verses = manifest["verses"]
    if not isinstance(verses, list) or any(not isinstance(verse, dict) for verse in verses):
        raise ValueError("Invalid manifest verse list")
    if [(v.get("surah"), v.get("ayah")) for v in verses] != expected:
        raise ValueError("Manifest omitted, duplicated or reordered a requested verse")
    for verse in verses:
        text, text_source, timing_source = verse.get("text"), verse.get("text_source"), verse.get("timing_source")
        if not isinstance(text, str) or not text.strip() or not isinstance(text_source, dict) or text_source.get("verse_key") != f"{verse['surah']}:{verse['ayah']}" or not text_source.get("provider") or text_source.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest():
            raise ValueError("Manifest Quran text provenance is incomplete or changed")
        if not isinstance(timing_source, dict) or timing_source.get("status") not in {"validated", "not_available"}:
            raise ValueError("Manifest timing provenance is missing")
        count = timing_source.get("word_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0 or (timing_source["status"] == "validated" and (count == 0 or timing_source.get("segment_count") != count or not timing_source.get("provider") or not timing_source.get("segments_sha256"))):
            raise ValueError("Manifest word/timing count is invalid")
        checksum = verse.get("audio_sha256")
        if verse.get("reciter_key") != manifest["reciter_key"] or not isinstance(verse.get("recording_url"), str) or not verse["recording_url"] or not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("Manifest recording identity is incomplete")
        duration = verse.get("audio_duration")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Manifest recording duration is invalid")
    if manifest.get("video_sha256") != file_sha256(video_path):
        raise ValueError("Video changed after coverage verification")
    return manifest


def require_manifest_coverage(manifest, *, surah_start, start_ayah, surah_end, end_ayah, reciter_key):
    """Bind claimed/reserved content to verified media before any transfer."""
    from config.settings import VERSE_COUNTS
    if surah_start not in VERSE_COUNTS or surah_end not in VERSE_COUNTS or surah_end < surah_start:
        raise ValueError("Invalid requested surah coverage")
    if not 1 <= start_ayah <= VERSE_COUNTS[surah_start] or not 1 <= end_ayah <= VERSE_COUNTS[surah_end]:
        raise ValueError("Invalid requested verse coverage")
    expected = [{"surah": surah, "start_ayah": start_ayah if surah == surah_start else 1,
                 "end_ayah": end_ayah if surah == surah_end else VERSE_COUNTS[surah]}
                for surah in range(surah_start, surah_end + 1)]
    if manifest.get("coverage") != expected or manifest.get("reciter_key") != reciter_key:
        raise ValueError("Verified media differs from the requested content identity/coverage")


def close_media_resources(resources) -> None:
    """Close source readers as well as MoviePy composites on every exit path."""
    visited = set()
    def close(clip):
        if clip is None or id(clip) in visited:
            return
        visited.add(id(clip))
        children = getattr(clip, "clips", ())
        if isinstance(children, (tuple, list)):
            for child in children:
                close(child)
        close(getattr(clip, "audio", None))
        close(getattr(clip, "mask", None))
        try:
            clip.close()
        except (AttributeError, OSError):
            pass
    for resource in reversed(resources):
        close(resource)


def retry_with_backoff(
    max_retries: int = 3,
    exceptions: Tuple[Type[Exception], ...] = (RequestException,),
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        exceptions: Tuple of exception types to catch and retry
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay after each retry
        
    Returns:
        Decorated function with retry logic
        
    Example:
        @retry_with_backoff(max_retries=3)
        def fetch_data(url):
            return requests.get(url)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
            
            # Re-raise the last exception if all retries failed
            raise last_exception
        
        return wrapper
    return decorator
