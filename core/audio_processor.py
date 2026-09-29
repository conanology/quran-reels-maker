"""
Audio Processor - Audio quality enhancements and ambient mixing
"""
import math
import hashlib
import tempfile
import json
import time
from urllib.parse import urljoin, urlparse
import os
import random
import shutil
from pathlib import Path
from typing import Optional
from loguru import logger
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range
import requests
from requests.exceptions import RequestException

from core.utils import retry_with_backoff
from config.settings import ASSETS_DIR, AUDIO_DIR


class AudioProcessingError(RuntimeError):
    pass


def normalize_recording_url(url: str) -> str:
    """Resolve Quran.com recording paths while restricting download origins."""
    if not isinstance(url, str) or not url.strip():
        raise AudioProcessingError("Audio recording URL is missing")
    resolved = urljoin("https://verses.quran.com/", url)
    parsed = urlparse(resolved)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname not in {
        "verses.quran.com", "audio.qurancdn.com", "download.quranicaudio.com", "everyayah.com"
    }:
        raise AudioProcessingError("Unexpected Quran recording download origin")
    return resolved


def _download_recording(url: str, output_path: Path) -> Path:
    """Bounded, atomic download. Incomplete bytes never become a cache hit."""
    from core.runtime_safety import exclusive_lock, atomic_write_json
    from core.utils import file_sha256
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(str(output_path) + ".source.json")
    with exclusive_lock(Path(str(output_path) + ".lock")):
        if output_path.is_file() and source_path.is_file():
            try:
                source = json.loads(source_path.read_text(encoding="utf-8"))
                if source.get("recording_url") == url and source.get("sha256") == file_sha256(output_path):
                    get_audio_duration(output_path)
                    return output_path
            except (OSError, ValueError, AudioProcessingError):
                pass
        fd, partial = tempfile.mkstemp(prefix="recording_", suffix=".part", dir=output_path.parent)
        try:
            total = 0
            deadline = time.monotonic() + 120
            with os.fdopen(fd, "wb") as destination, requests.get(url, stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                normalize_recording_url(response.url)
                for chunk in response.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > 64 * 1024 * 1024 or time.monotonic() > deadline:
                        raise AudioProcessingError("Ayah recording exceeded download size/time limit")
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if not total:
                raise AudioProcessingError("Downloaded audio is empty")
            duration = get_audio_duration(Path(partial))
            os.replace(partial, output_path)
            atomic_write_json(source_path, {"recording_url": url, "sha256": file_sha256(output_path), "duration_seconds": duration})
            return output_path
        finally:
            Path(partial).unlink(missing_ok=True)

# Configure FFmpeg for pydub on Windows
def _find_ffmpeg():
    """Auto-detect FFmpeg installation"""
    # Check if already in PATH
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
        
    # Check imageio_ffmpeg (installed by moviepy)
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and os.path.exists(ffmpeg_exe):
            logger.debug(f"Found FFmpeg via imageio_ffmpeg: {ffmpeg_exe}")
            return ffmpeg_exe
    except ImportError:
        pass
    
    # Common Windows installation paths
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        os.path.expanduser(r"~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    # Check environment variable
    env_path = os.getenv("FFMPEG_BINARY")
    if env_path and os.path.exists(env_path):
        return env_path
    
    return None

# Set FFmpeg path for pydub
_ffmpeg_path = _find_ffmpeg()
if _ffmpeg_path:
    AudioSegment.converter = _ffmpeg_path
    # Also set ffprobe
    _ffprobe_path = _ffmpeg_path.replace("ffmpeg", "ffprobe")
    if os.path.exists(_ffprobe_path):
        AudioSegment.ffprobe = _ffprobe_path
    logger.debug(f"FFmpeg configured: {_ffmpeg_path}")
else:
    logger.warning("FFmpeg not found. Audio processing may fail. Install FFmpeg or set FFMPEG_BINARY env var.")

AMBIENT_DIR = ASSETS_DIR / "ambient"

# Environment config
AMBIENT_ENABLED = os.getenv("AMBIENT_SOUND_ENABLED", "false").lower() == "true"
AMBIENT_VOLUME = float(os.getenv("AMBIENT_VOLUME", "0.12"))  # 12% volume by default
AUDIO_NORMALIZE = os.getenv("AUDIO_NORMALIZE", "true").lower() == "true"



def normalize_audio(audio_path: Path) -> Path:
    """
    Normalize audio volume for consistent levels.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Path to normalized audio (same file, overwritten)
    """
    if not AUDIO_NORMALIZE:
        return audio_path
        
    try:
        audio = AudioSegment.from_file(str(audio_path))
        
        # Normalize volume
        normalized = normalize(audio)
        
        # Optional: gentle compression for more consistent dynamics
        # normalized = compress_dynamic_range(normalized, threshold=-20.0, ratio=3.0)
        
        normalized.export(str(audio_path), format="mp3")
        logger.debug(f"Normalized audio: {audio_path.name}")
        
        return audio_path
        
    except Exception as e:
        logger.warning(f"Audio normalization failed: {e}")
        return audio_path


def amplitude_ratio_to_db(ratio: float) -> float:
    """
    Convert an amplitude ratio to the dB gain pydub expects.

    The previous expression, 20 * sqrt(ratio) subtracted from 20, is not a dB
    conversion: at the default 0.12 it applied -13.07 dB (22% amplitude) rather
    than the intended -18.42 dB, leaving the bed about 1.85x too loud under the
    recitation.
    """
    if ratio <= 0:
        return -120.0  # effectively silent
    return 20.0 * math.log10(ratio)


def get_ambient_sound(duration: float, output_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Get an ambient sound file, trimmed/looped to match duration.
    
    Args:
        duration: Required duration in seconds
        
    Returns:
        Path to ambient audio file, or None if unavailable
    """
    if not AMBIENT_ENABLED:
        return None
        
    AMBIENT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Find ambient files
    ambient_files = list(AMBIENT_DIR.glob("*.mp3")) + list(AMBIENT_DIR.glob("*.wav"))
    
    if not ambient_files:
        logger.debug("No ambient sound files found in assets/ambient/")
        return None
    
    # Pick random ambient
    ambient_path = random.choice(ambient_files)
    
    try:
        ambient = AudioSegment.from_file(str(ambient_path))
        if len(ambient) <= 0:
            raise AudioProcessingError("Ambient sound is empty")
        
        # Convert duration to milliseconds
        target_ms = int(duration * 1000)
        
        # Loop if too short
        while len(ambient) < target_ms:
            ambient = ambient + ambient
        
        # Trim to exact duration
        ambient = ambient[:target_ms]
        
        # Reduce volume to AMBIENT_VOLUME of the original amplitude
        ambient = ambient + amplitude_ratio_to_db(AMBIENT_VOLUME)
        
        # Add fade in/out
        ambient = ambient.fade_in(2000).fade_out(2000)
        
        # Export to temp file
        destination = output_dir or AUDIO_DIR
        destination.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="ambient_", suffix=".mp3", dir=destination)
        os.close(fd)
        output_path = Path(name)
        ambient.export(str(output_path), format="mp3")
        
        logger.info(f"Created ambient track: {output_path.name}")
        return output_path
        
    except Exception as e:
        logger.warning(f"Ambient audio processing failed: {e}")
        return None


def mix_audio_with_ambient(main_audio_path: Path, ambient_path: Path) -> Path:
    """
    Mix main audio with ambient background.
    
    Args:
        main_audio_path: Path to main audio (recitation)
        ambient_path: Path to ambient sound
        
    Returns:
        Path to mixed audio
    """
    try:
        main = AudioSegment.from_file(str(main_audio_path))
        ambient = AudioSegment.from_file(str(ambient_path))
        
        # Make sure ambient is same length
        if len(ambient) < len(main):
            while len(ambient) < len(main):
                ambient = ambient + ambient
        ambient = ambient[:len(main)]
        
        # Overlay ambient under main audio
        mixed = main.overlay(ambient)
        
        output_path = main_audio_path.parent / f"mixed_{main_audio_path.name}"
        mixed.export(str(output_path), format="mp3")
        
        return output_path
        
    except Exception as e:
        logger.warning(f"Audio mixing failed: {e}")
        return main_audio_path


def enhance_recitation_audio(audio_path: Path) -> Path:
    """
    Apply all audio enhancements to a recitation file.
    
    Args:
        audio_path: Path to original audio
        
    Returns:
        Path to enhanced audio
    """
    # Step 1: Normalize
    enhanced_path = normalize_audio(audio_path)
    
    return enhanced_path


# ============================================================================
# AUDIO DOWNLOAD AND PROCESSING (Required by video_generator.py)
# ============================================================================

import requests
import subprocess
from config.settings import QURAN_AUDIO_BASE, RECITERS


@retry_with_backoff(max_retries=3, exceptions=(RequestException,))
def download_ayah_audio(reciter_key: str, surah: int, ayah: int, output_dir: Path) -> Path:
    """
    Download audio for a specific ayah.
    
    Args:
        reciter_key: Key for the reciter in RECITERS dict
        surah: Surah number (1-114)
        ayah: Ayah number
        output_dir: Directory to save the audio file
        
    Returns:
        Path to the downloaded audio file
    """
    if reciter_key not in RECITERS:
        raise AudioProcessingError(f"Unknown reciter: {reciter_key}")
    reciter_id = RECITERS[reciter_key]["id"]
    
    # Build URL
    url = QURAN_AUDIO_BASE.format(reciter=reciter_id, surah=surah, ayah=ayah)
    
    # Output filename - INCLUDE RECITER to prevent cache collisions
    filename = f"ayah_{reciter_key}_{surah:03d}_{ayah:03d}.mp3"
    output_path = output_dir / filename
    
    return _download_recording(normalize_recording_url(url), output_path)


def trim_silence(audio_path: Path) -> Path:
    """
    Trim silence from the beginning and end of an audio file.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Path to trimmed audio (same file, overwritten)
    """
    try:
        audio = AudioSegment.from_file(str(audio_path))
        
        # Detect silence threshold (in dBFS)
        silence_thresh = audio.dBFS - 16
        
        # Find non-silent chunks
        from pydub.silence import detect_nonsilent
        nonsilent = detect_nonsilent(audio, min_silence_len=200, silence_thresh=silence_thresh)
        
        if nonsilent:
            start, end = nonsilent[0][0], nonsilent[-1][1]
            # Add small padding
            start = max(0, start - 50)
            end = min(len(audio), end + 100)
            trimmed = audio[start:end]
            trimmed.export(str(audio_path), format="mp3")
        
        return audio_path
        
    except Exception as e:
        logger.warning(f"Could not trim silence from {audio_path.name}, using original: {e}")
        return audio_path


def download_and_process_ayah(reciter_key: str, surah: int, ayah: int, output_dir: Path, audio_url: str = None) -> Path:
    """
    Download and process an ayah's audio.
    
    Args:
        reciter_key: Key for the reciter
        surah: Surah number
        ayah: Ayah number
        output_dir: Directory to save audio
        audio_url: Optional direct URL to download from (skips everyayah.com)
        
    Returns:
        Path to processed audio file
    """
    if reciter_key not in RECITERS:
        raise AudioProcessingError(f"Unknown reciter: {reciter_key}")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Preserve the downloaded recording's time origin and sample content.
    if audio_url:
        url = normalize_recording_url(audio_url)
        source_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        filename = f"ayah_{reciter_key}_{surah:03d}_{ayah:03d}_{source_hash}.mp3"
        audio_path = _download_recording(url, output_dir / filename)
    else:
        audio_path = download_ayah_audio(reciter_key, surah, ayah, output_dir)
    return audio_path


def get_audio_duration(audio_path: Path) -> float:
    """
    Get the duration of an audio file in seconds.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Duration in seconds
    """
    try:
        audio = AudioSegment.from_file(str(audio_path))
        duration = len(audio) / 1000.0
        if not math.isfinite(duration) or duration <= 0:
            raise AudioProcessingError("Audio has no positive duration")
        return duration
    except Exception as e:
        logger.error(f"Could not get duration for {audio_path}: {e}")
        raise AudioProcessingError(f"Could not measure downloaded audio: {audio_path.name}") from e


def cleanup_audio_files(audio_dir: Path) -> None:
    """
    Remove temporary audio files from the output directory.
    
    Args:
        audio_dir: Directory containing audio files to clean
    """
    if not audio_dir.exists():
        return
        
    count = 0
    for f in audio_dir.glob("*.mp3"):
        try:
            f.unlink()
            count += 1
        except OSError as e:
            logger.debug(f"Could not delete {f}: {e}")
    
    if count > 0:
        logger.info(f"Cleaned up {count} audio files from {audio_dir}")
