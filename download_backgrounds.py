"""
Download sample background videos from Pexels
Run this once to get some starter backgrounds
"""
import os
import requests
from pathlib import Path

# Sample nature video URLs (direct links to free stock videos)
# These are placeholders - replace with actual Pexels video URLs
SAMPLE_VIDEOS = [
    # You'll need to manually download from Pexels or Pixabay
    # Here are some search suggestions:
    # - https://www.pexels.com/search/videos/nature/
    # - https://www.pexels.com/search/videos/forest/
    # - https://www.pexels.com/search/videos/ocean/
]

def download_backgrounds():
    """Download sample background videos."""
    backgrounds_dir = Path(__file__).parent / "assets" / "backgrounds"
    backgrounds_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*50)
    print("📥 BACKGROUND VIDEO SETUP")
    print("="*50)
    print(f"\nBackgrounds folder: {backgrounds_dir}")
    print("""
To add background videos:

1. Go to https://www.pexels.com/videos/
2. Search for: "nature", "forest", "ocean", "clouds", "mountains"
3. Download 3-5 videos (720p or 1080p)
4. Save them to: assets/backgrounds/

Example filenames:
  - nature_forest_01.mp4
  - ocean_waves_02.mp4
  - clouds_sky_03.mp4
  - mountains_sunset_04.mp4

The videos will be automatically cropped to 9:16 vertical format.
    """)
    
    # Check if any videos exist
    existing = list(backgrounds_dir.glob("*.mp4"))
    if existing:
        print(f"✅ Found {len(existing)} existing background(s):")
        for v in existing:
            print(f"   - {v.name}")
    else:
        print("⚠️ No background videos found yet!")
        print("   Please add some MP4 files to continue.")

if __name__ == "__main__":
    download_backgrounds()
