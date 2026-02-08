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

def search_pexel_video(query: str) -> Optional[Dict]:
    """Search for a video on Pexels matching the query."""
    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY is not set. Using local backgrounds.")
        return None
        
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": 10,
        "orientation": "portrait",
        "size": "medium"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['videos']:
                # Filter for videos roughly 15-60 seconds to be useful
                valid_videos = [
                    v for v in data['videos'] 
                    if 15 <= v['duration'] <= 90
                ]
                if valid_videos:
                    return random.choice(valid_videos)
        return None
    except Exception as e:
        logger.error(f"Pexels search failed: {e}")
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
    
    # If already exists, return it
    if output_path.exists():
        return output_path
        
    logger.info(f"Downloading Pexels video: {video_data['id']} ({target_file['width']}x{target_file['height']})")
    
    try:
        with requests.get(download_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return output_path
    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        return None

def cleanup_cache(max_files: int = 20):
    """Keep only the most recent files to save space."""
    ensure_download_dir()
    files = list(DOWNLOAD_DIR.glob("*.mp4"))
    if len(files) > max_files:
        # Sort by modification time (oldest first)
        files.sort(key=lambda x: x.stat().st_mtime)
        files_to_delete = files[:len(files) - max_files]
        for f in files_to_delete:
            try:
                f.unlink()
                logger.debug(f"Deleted old cache file: {f.name}")
            except Exception:
                pass

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

    cached_files = list(DOWNLOAD_DIR.glob("*.mp4"))

    # 20% chance to reuse an existing cached downloaded video to save API calls/bandwidth
    if cached_files and random.random() < 0.2:
        random.shuffle(cached_files)
        for f in cached_files[:3]:
            if not _video_has_people(f):
                logger.info("Using cached dynamic background")
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
                    return path
                else:
                    path.unlink(missing_ok=True)

    # Fallback: scan all cached for a clean one
    for f in cached_files:
        if not _video_has_people(f):
            logger.warning("Download failed, using cached file fallback")
            return f

    return None
