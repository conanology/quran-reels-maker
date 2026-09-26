"""
Stock Footage Manager - Fetch dynamic backgrounds from Pexels
"""
import os
import random
import requests
from pathlib import Path
from typing import Optional, List, Dict
from loguru import logger
from config.settings import ASSETS_DIR
from core.person_detector import has_people

# You need to get an API key from https://www.pexels.com/api/
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
DOWNLOAD_DIR = ASSETS_DIR / "downloaded_bg"

# SAFE search queries - Nature ONLY, no people
# Carefully chosen to avoid any inappropriate content
SEARCH_QUERIES = [
    "mountain landscape vertical",
    "clouds sky vertical",
    "river stream vertical",
    "forest trees vertical",
    "ocean waves vertical",
    "sunset sky vertical",
    "stars night sky vertical",
    "desert sand dunes vertical",
    "rain drops vertical",
    "green leaves vertical",
    "waterfall nature vertical",
    "aurora borealis vertical",
    "misty mountains vertical",
    "calm lake vertical"
]

def ensure_download_dir():
    """Ensure the download directory exists."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Pexels stops returning results after page 6, so 6 x 80 is the real reachable
# depth per query. Drawing only from page 1 is why every video looked alike.
PEXELS_PER_PAGE = 80
PEXELS_MAX_PAGE = 6


def search_pexel_video(query: str) -> Optional[Dict]:
    """Search for a video on Pexels matching the query."""
    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY is not set. Using local backgrounds.")
        return None

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}

    # Walk pages in random order so repeated runs do not converge on page 1.
    pages = list(range(1, PEXELS_MAX_PAGE + 1))
    random.shuffle(pages)

    for page in pages:
        params = {
            "query": query,
            "per_page": PEXELS_PER_PAGE,
            "page": page,
            "orientation": "portrait",
            "size": "medium",
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code != 200:
                logger.warning(f"Pexels search HTTP {response.status_code} for '{query}'")
                return None
            videos = response.json().get("videos", [])
            valid_videos = [v for v in videos if 15 <= v["duration"] <= 90]
            if valid_videos:
                logger.debug(
                    f"Pexels '{query}' page {page}: {len(valid_videos)} candidates"
                )
                from core.background_history import pick_pexels_video_candidate
                return pick_pexels_video_candidate(valid_videos)
        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return None

    return None

def download_video(video_data: Dict) -> Optional[Path]:
    """Download the highest quality video file from the Pexels metadata."""
    if not video_data:
        return None
        
    # Find best quality file (hd, but not 4k to save bandwidth/time)
    video_files = video_data.get('video_files', [])
    # Sort by size to get best quality that isn't excessively huge
    video_files.sort(key=lambda x: x['width'] * x['height'], reverse=True)
    
    target_file = None
    # Prefer HD (1080x1920) or similar
    for vf in video_files:
        if vf['width'] >= 720 and vf['height'] >= 1280:
            target_file = vf
            break
    
    if not target_file:
        target_file = video_files[0] if video_files else None
        
    if not target_file:
        return None
        
    download_url = target_file['link']
    filename = f"pexels_{video_data['id']}_{target_file['height']}p.mp4"
    output_path = DOWNLOAD_DIR / filename
    
    from core.asset_provenance import download_background_asset
    try:
        return download_background_asset(output_path, download_url, {
            "provider": "Pexels", "video_id": video_data["id"],
            "source_url": video_data.get("url"), "creator": video_data.get("user", {}).get("name"),
            "creator_url": video_data.get("user", {}).get("url")})
    except Exception as exc:
        logger.warning("Background download/validation failed ({})", type(exc).__name__)
        return None


def cleanup_cache(max_files: int = 20):
    """Report the bounded cache; never evict a file another render may use."""
    ensure_download_dir()
    files = list(DOWNLOAD_DIR.glob("*.mp4"))
    if len(files) > max_files:
        logger.warning("Background cache exceeds configured budget; explicit inactive-asset archival is required")

def _video_has_people(path: Path) -> bool:
    """Check if a video contains people, with logging."""
    result = has_people(path)
    if result:
        logger.info(f"Rejected {path.name} — people detected")
    return result


def get_dynamic_background() -> Optional[Path]:
    """
    Main entry point: Get a background video.
    Tries Pexels first. If fails or no key, falls back to None (caller should use local).
    Videos containing people are rejected.
    """
    ensure_download_dir()

    from core.background_history import record_background_usage, pick_background_candidate
    from core.asset_provenance import validate_background
    cached_files = []
    for candidate in DOWNLOAD_DIR.glob("*.mp4"):
        try:
            validate_background(candidate)
            cached_files.append(candidate)
        except Exception:
            continue
    preferred = pick_background_candidate(cached_files)
    if preferred in cached_files:
        cached_files.remove(preferred)
        cached_files.insert(0, preferred)

    # 20% chance to reuse an existing cached downloaded video to save API calls/bandwidth
    if cached_files and random.random() < 0.2:
        random.shuffle(cached_files)
        for f in cached_files[:3]:
            if not _video_has_people(f):
                logger.info("Using cached dynamic background")
                record_background_usage(f, source="Pexels cache; review required")
                return f

    # Fresh download with up to 3 retries using different queries
    tried_queries = set()
    for _ in range(3):
        available = [q for q in SEARCH_QUERIES if q not in tried_queries]
        if not available:
            break
        query = random.choice(available)
        tried_queries.add(query)
        logger.info(f"Searching Pexels for: '{query}'")

        video_data = search_pexel_video(query)
        if video_data:
            path = download_video(video_data)
            if path:
                if not _video_has_people(path):
                    cleanup_cache()
                    record_background_usage(path, source="Pexels; review required")
                    return path
                # Keep rejected cache evidence: another render may own this file.

    # Fallback: scan all cached for a clean one
    for f in cached_files:
        if not _video_has_people(f):
            logger.warning("Download failed, using cached file fallback")
            record_background_usage(f, source="Pexels fallback; review required")
            return f

    return None
