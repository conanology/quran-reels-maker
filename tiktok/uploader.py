"""
TikTok Uploader - Placeholder (Currently Disabled)

TikTok's anti-automation measures make reliable automated uploads difficult.
For now, videos should be uploaded manually via the TikTok app or web interface.

Your generated videos are saved in: outputs/videos/
"""

from pathlib import Path
from typing import Dict, Any, Optional


def is_configured() -> bool:
    """TikTok upload is currently disabled."""
    return False


def generate_tiktok_metadata(
    surah_name_ar: str,
    surah_name_en: str,
    surah_num: int,
    start_ayah: int,
    end_ayah: int,
    reciter_name_ar: str
) -> Dict[str, Any]:
    """Generate metadata for manual TikTok upload."""
    verse_range = f"{start_ayah}" if start_ayah == end_ayah else f"{start_ayah}-{end_ayah}"
    
    caption = f"""🕌 سورة {surah_name_ar} | آية {verse_range}

📖 Surah {surah_name_en} ({surah_num})
🎙️ {reciter_name_ar}

#Quran #القرآن #Islam #QuranRecitation #Islamic #Muslim #Deen #Allah #QuranVerses #QuranDaily"""

    return {
        "caption": caption,
        "description": f"Surah {surah_name_en} Ayah {verse_range}",
    }


def upload_to_tiktok(video_path: Path, metadata: Dict[str, Any], **kwargs) -> Optional[Dict[str, Any]]:
    """TikTok upload is currently disabled."""
    return {"status": "disabled", "message": "TikTok upload disabled. Please upload manually."}


def get_tiktok_status() -> Dict[str, Any]:
    """Get TikTok status."""
    return {
        "enabled": False,
        "configured": False,
        "message": "TikTok upload disabled - use manual upload"
    }
