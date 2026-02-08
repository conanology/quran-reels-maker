"""
Audio Processor - Audio quality enhancements and ambient mixing
"""
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
AMBIENT_ENABLED = os.getenv("AMBIENT_SOUND_ENABLED", "true").lower() == "true"
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


def get_ambient_sound(duration: float) -> Optional[Path]:
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
        
        # Convert duration to milliseconds
        target_ms = int(duration * 1000)
        
        # Loop if too short
        while len(ambient) < target_ms:
            ambient = ambient + ambient
        
        # Trim to exact duration
        ambient = ambient[:target_ms]
        
        # Reduce volume
        volume_db = 20 * (AMBIENT_VOLUME ** 0.5)  # Convert ratio to dB reduction
        ambient = ambient - (20 - volume_db)  # Reduce volume significantly
        
        # Add fade in/out
        ambient = ambient.fade_in(2000).fade_out(2000)
        
        # Export to temp file
        output_path = AUDIO_DIR / f"ambient_mix_{random.randint(1000, 9999)}.mp3"
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
    reciter_info = RECITERS.get(reciter_key, {})
    reciter_id = reciter_info.get("id", "Alafasy_64kbps")
    
    # Build URL
    url = QURAN_AUDIO_BASE.format(reciter=reciter_id, surah=surah, ayah=ayah)
    
    # Output filename - INCLUDE RECITER to prevent cache collisions
    filename = f"ayah_{reciter_key}_{surah:03d}_{ayah:03d}.mp3"
    output_path = output_dir / filename
    
    # Check if already exists (for THIS reciter)
    if output_path.exists():
        return output_path
    
    logger.info(f"Downloading audio: {surah}:{ayah} ({reciter_key})")
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        return output_path
        
    except RequestException as e:
        logger.error(f"Failed to download audio: {e}")
        raise


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
    # Download
    if audio_url:
        # If standard URL is provided, download directly
        filename = f"{surah:03d}{ayah:03d}.mp3"
        audio_path = output_dir / filename
        
        if not audio_path.exists():
            import requests
            try:
                logger.info(f"Downloading from V4 URL: {audio_url}")
                response = requests.get(audio_url, timeout=30)
                response.raise_for_status()
                with open(audio_path, 'wb') as f:
                    f.write(response.content)
            except Exception as e:
                logger.error(f"Failed to download audio URL: {e}")
                raise
        
        # When using V4 audio with timestamps, we usually DO NOT want to trim silence
        # because the timestamps are relative to the original file.
        # Trimming would shift the audio and break sync.
        # So we skip trim_silence() here.
        
    else:
        # Fallback to EveryAyah logic
        audio_path = download_ayah_audio(reciter_key, surah, ayah, output_dir)
        # Trim silence only for legacy/EveryAyah source
        audio_path = trim_silence(audio_path)
    
    # Normalize volume (safe to do, doesn't change timing)
    audio_path = normalize_audio(audio_path)
    
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
        return len(audio) / 1000.0  # Convert ms to seconds
    except Exception as e:
        logger.error(f"Could not get duration for {audio_path}: {e}")
        return 5.0  # Default fallback


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
