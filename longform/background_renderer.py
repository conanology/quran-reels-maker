"""
Background Renderer - Cinematic 16:9 B-roll backgrounds for long-form videos.
Downloads landscape-oriented nature footage from Pexels with usage tracking
to ensure no video is ever repeated.
"""
import os
import json
import random
import requests
from pathlib import Path
from typing import Optional, Dict, List

from loguru import logger

from config.settings import OUTPUTS_DIR
from core.person_detector import has_people

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

BACKGROUNDS_DIR = OUTPUTS_DIR / "longform" / "backgrounds"
BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)

BACKGROUND_USAGE_FILE = OUTPUTS_DIR / "longform" / "background_usage.json"

# Cinematic 16:9 landscape search queries — nature only, no people
SEARCH_QUERIES_LANDSCAPE = [
    "mosque interior cinematic",
    "islamic architecture aerial",
    "desert sunrise cinematic",
    "ocean waves aerial landscape",
    "mountain clouds timelapse",
    "starry night sky landscape",
    "calm river landscape cinematic",
    "golden sunset landscape",
    "misty forest aerial",
    "sand dunes desert cinematic",
]


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

def _load_usage_history() -> List[int]:
    """Load the set of previously-used Pexels video IDs."""
    if BACKGROUND_USAGE_FILE.exists():
        try:
            data = json.loads(BACKGROUND_USAGE_FILE.read_text(encoding="utf-8"))
            return data.get("used_ids", [])
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupted background usage file — starting fresh")
    return []


def _save_usage_history(used_ids: List[int]) -> None:
    """Persist the list of used Pexels video IDs."""
    BACKGROUND_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKGROUND_USAGE_FILE.write_text(
        json.dumps({"used_ids": used_ids}, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Pexels API helpers
# ---------------------------------------------------------------------------

def _search_pexels_landscape(query: str, min_duration: int = 30) -> List[Dict]:
    """
    Search Pexels for LANDSCAPE-oriented videos matching the query.
    Returns a list of video metadata dicts filtered by minimum duration.
    """
    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY is not set. Cannot fetch backgrounds.")
        return []

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": 15,
        "orientation": "landscape",
        "size": "large",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # Keep only videos at or above the minimum duration
            return [
                v for v in data.get("videos", [])
                if v.get("duration", 0) >= min_duration
            ]
        logger.warning(f"Pexels API returned status {response.status_code}")
        return []
    except Exception as e:
        logger.error(f"Pexels landscape search failed: {e}")
        return []


def _pick_best_hd_file(video_data: Dict) -> Optional[Dict]:
    """
    Select the best HD video file (prefer >= 1920x1080) from Pexels metadata.
    Falls back to the largest available file.
    """
    video_files = video_data.get("video_files", [])
    if not video_files:
        return None

    # Sort by resolution descending
    video_files.sort(key=lambda vf: vf.get("width", 0) * vf.get("height", 0), reverse=True)

    # Prefer HD (1920x1080 or higher)
    for vf in video_files:
        if vf.get("width", 0) >= 1920 and vf.get("height", 0) >= 1080:
            return vf

    # Fallback to largest available
    return video_files[0]


def _download_pexels_video(video_data: Dict, target_file: Dict) -> Optional[Path]:
    """Download a single Pexels video file to the backgrounds directory."""
    download_url = target_file.get("link")
    if not download_url:
        return None

    height = target_file.get("height", 0)
    filename = f"pexels_{video_data['id']}_{height}p.mp4"
    output_path = BACKGROUNDS_DIR / filename

    if output_path.exists():
        return output_path

    logger.info(
        f"Downloading Pexels landscape video: {video_data['id']} "
        f"({target_file.get('width', '?')}x{height})"
    )

    try:
        with requests.get(download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return output_path
    except Exception as e:
        logger.error(f"Failed to download Pexels video {video_data['id']}: {e}")
        # Clean up partial file
        output_path.unlink(missing_ok=True)
        return None


def _video_has_people(path: Path) -> bool:
    """Check if a video contains people, with logging."""
    result = has_people(path)
    if result:
        logger.info(f"Rejected {path.name} — people detected")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cinematic_background(min_duration: int = 30) -> Optional[Path]:
    """
    Main entry point: acquire a cinematic 16:9 background video.

    1. Load usage history to avoid repeats.
    2. Search Pexels for landscape-oriented videos.
    3. Filter out already-used video IDs.
    4. Download the best HD file (>= 1920x1080).
    5. Reject videos with people.
    6. Record the video ID in usage history.
    7. Fall back to any cached landscape video if Pexels fails.

    Returns:
        Path to the downloaded/cached background video, or None.
    """
    used_ids = _load_usage_history()

    # Try up to 3 different queries
    tried_queries: set[str] = set()
    for _ in range(3):
        available = [q for q in SEARCH_QUERIES_LANDSCAPE if q not in tried_queries]
        if not available:
            break
        query = random.choice(available)
        tried_queries.add(query)
        logger.info(f"Searching Pexels (landscape) for: '{query}'")

        videos = _search_pexels_landscape(query, min_duration=min_duration)
        # Filter out already-used IDs
        fresh = [v for v in videos if v.get("id") not in used_ids]
        if not fresh:
            logger.debug(f"No fresh videos for query '{query}', trying another")
            continue

        random.shuffle(fresh)

        for video_data in fresh[:5]:
            best_file = _pick_best_hd_file(video_data)
            if not best_file:
                continue

            path = _download_pexels_video(video_data, best_file)
            if not path:
                continue

            if _video_has_people(path):
                path.unlink(missing_ok=True)
                continue

            # Success — record usage and return
            used_ids.append(video_data["id"])
            _save_usage_history(used_ids)
            logger.info(f"Selected background: {path.name}")
            return path

    # Fallback: use any cached landscape video in backgrounds dir
    cached = list(BACKGROUNDS_DIR.glob("*.mp4"))
    if cached:
        random.shuffle(cached)
        for f in cached:
            if not _video_has_people(f):
                logger.warning(f"Pexels download failed — using cached background: {f.name}")
                return f

    logger.error("No cinematic background available (Pexels and cache both exhausted)")
    return None


def get_ai_landscape_background(surah: int, start_ayah: int) -> Optional[Path]:
    """
    Generate a landscape AI themed background video based on the translation of the first ayah.
    1. Fetch translation.
    2. Generate visual prompt.
    3. Download landscape (1920x1080) image from Pollinations.ai.
    4. Convert image to 60-second zoom-in MP4 video.
    5. Return video Path.
    """
    import subprocess
    import time
    import urllib.parse
    from core.quran_api import get_ayah_translation
    from core.ai_brain import generate_visual_prompt

    # 1. Fetch translation
    try:
        translation = get_ayah_translation(surah, start_ayah)
    except Exception as e:
        logger.warning(f"Could not get translation for AI background: {e}")
        return None

    if not translation:
        logger.warning(f"No translation found for {surah}:{start_ayah}")
        return None

    # 2. Generate visual prompt
    visual_prompt = generate_visual_prompt(translation)
    if not visual_prompt:
        logger.warning("Could not generate visual prompt from AI brain.")
        return None

    # 3. Download landscape image
    encoded_prompt = urllib.parse.quote(visual_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1920&height=1080&model=flux&nologo=true"
    
    temp_jpg = BACKGROUNDS_DIR / f"temp_ai_bg_{int(time.time())}.jpg"
    try:
        logger.info(f"Downloading themed AI landscape background from Pollinations: {temp_jpg.name}")
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            with open(temp_jpg, "wb") as f:
                f.write(response.content)
        else:
            logger.error(f"Pollinations landscape API error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Failed to download AI landscape image: {e}")
        return None

    # 4. Convert image to 60-second zoom-in MP4 video using FFmpeg
    output_mp4 = BACKGROUNDS_DIR / f"ai_landscape_bg_{int(time.time())}.mp4"
    logger.info(f"Converting static image to 60-second video clip using FFmpeg: {output_mp4.name}")
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(temp_jpg),
        "-vf", "zoompan=z='1.0+0.05*(on/1800)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=1920x1080:fps=30",
        "-c:v", "libx264",
        "-t", "60",
        "-pix_fmt", "yuv420p",
        str(output_mp4)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.success(f"Generated landscape background video from AI image: {output_mp4.name}")
        return output_mp4, temp_jpg
    except Exception as e:
        logger.error(f"FFmpeg image to video conversion failed: {e}")
        if 'result' in locals() and result.stderr:
             logger.error(f"FFmpeg stderr: {result.stderr}")
        temp_jpg.unlink(missing_ok=True)
        output_mp4.unlink(missing_ok=True)
        return None
