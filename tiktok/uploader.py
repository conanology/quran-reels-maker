"""
TikTok Uploader - Upload videos to TikTok using either cookies.txt or Content Posting API
"""
from pathlib import Path
from typing import Dict, Any, Optional
import os
import requests
from loguru import logger

from config.settings import TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_TOKEN_PATH
from tiktok.auth import get_tiktok_token


def is_configured() -> bool:
    """Check if TikTok uploading is configured via either cookies.txt or Developer API."""
    if Path("cookies.txt").exists():
        return True
    token = get_tiktok_token()
    return token is not None


def generate_tiktok_metadata(
    surah_name_ar: str,
    surah_name_en: str,
    surah_num: int,
    start_ayah: int,
    end_ayah: int,
    reciter_name_ar: str
) -> Dict[str, Any]:
    """Generate metadata for TikTok upload."""
    verse_range = f"{start_ayah}" if start_ayah == end_ayah else f"{start_ayah}-{end_ayah}"
    
    caption = f"""🕌 سورة {surah_name_ar} | آية {verse_range}
📖 Surah {surah_name_en} ({surah_num})
🎙️ {reciter_name_ar}

#Quran #القرآن #Islam #QuranRecitation #Islamic #Muslim #Deen #Allah #QuranVerses #QuranDaily"""

    return {
        "caption": caption,
        "description": f"Surah {surah_name_en} Ayah {verse_range}",
    }


def upload_to_tiktok_api(video_path: Path, caption: str) -> Optional[Dict[str, Any]]:
    """Upload using the official Content Posting API."""
    token = get_tiktok_token()
    if not token:
        return {"status": "failed", "error": "TikTok API not authenticated."}
        
    video_size = video_path.stat().st_size
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8"
    }
    
    payload = {
        "post_info": {
            "title": caption,
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,
            "total_chunk_count": 1
        }
    }
    
    try:
        init_res = requests.post(init_url, headers=headers, json=payload, timeout=20)
        if init_res.status_code != 200:
            return {"status": "failed", "error": f"Init HTTP {init_res.status_code}"}
            
        res_data = init_res.json()
        error_info = res_data.get("error", {})
        if error_info.get("code") != "ok":
            return {"status": "failed", "error": f"API error: {error_info.get('message')}"}
            
        data = res_data.get("data", {})
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        
        # PUT request
        put_headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(video_size),
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}"
        }
        
        with open(video_path, 'rb') as f:
            video_bytes = f.read()
            
        put_res = requests.put(upload_url, headers=put_headers, data=video_bytes, timeout=120)
        if put_res.status_code in [200, 201]:
            logger.success(f"Video uploaded to TikTok via official API. ID: {publish_id}")
            return {"status": "uploaded", "publish_id": publish_id}
            
        return {"status": "failed", "error": f"PUT HTTP {put_res.status_code}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _get_tiktok_cookies_path() -> Path:
    """Filter cookies.txt to TikTok-only cookies and return path to filtered file."""
    src = Path("cookies.txt")
    filtered = Path("tiktok_cookies.txt")
    
    # Re-generate filtered file if source is newer or filtered doesn't exist
    if not filtered.exists() or src.stat().st_mtime > filtered.stat().st_mtime:
        lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
        header = [l for l in lines if l.startswith("#") or l.strip() == ""][:4]
        tiktok = [l for l in lines if "tiktok" in l.lower() and not l.startswith("#")]
        with open(filtered, "w", encoding="utf-8") as f:
            f.writelines(header)
            f.writelines(tiktok)
        logger.debug(f"Filtered {len(tiktok)} TikTok cookies from {len(lines)} total lines")
    
    return filtered


def _dismiss_tiktok_modals(page) -> None:
    """Dismiss any TikTok modal overlays (copyright check, joyride tutorial, split window, etc.)."""
    import time
    
    # Wait a moment for modals to fully render
    time.sleep(1)
    
    # === 1. Dismiss react-joyride onboarding tutorial overlay ===
    try:
        joyride = page.locator("div.react-joyride__overlay")
        if joyride.is_visible(timeout=1500):
            logger.info("Joyride tutorial overlay detected, removing...")
            # Try clicking skip/close button first
            for skip_sel in [
                "button:has-text('Skip')",
                "button:has-text('Got it')",
                "button:has-text('Next')",
                "[data-test-id='button-skip']",
                "button[aria-label='Close']",
            ]:
                try:
                    skip_btn = page.locator(skip_sel).first
                    if skip_btn.is_visible(timeout=500):
                        skip_btn.click(force=True)
                        time.sleep(0.5)
                        logger.debug(f"Clicked joyride dismiss via: {skip_sel}")
                        break
                except Exception:
                    continue
            
            # Fallback: remove via JavaScript
            page.evaluate("""
                document.querySelectorAll('#react-joyride-portal').forEach(el => el.remove());
                document.querySelectorAll('.react-joyride__overlay').forEach(el => el.remove());
                document.querySelectorAll('[data-test-id="overlay"]').forEach(el => el.remove());
            """)
            logger.debug("Removed joyride overlay via JavaScript")
            time.sleep(0.5)
    except Exception:
        pass
    
    # === 2. Dismiss TUXModal overlays (copyright check, etc.) ===
    modal_dismiss_strategies = [
        "div.TUXModal-overlay button",
        "button:has-text('Got it')",
        "button:has-text('OK')",
        "button:has-text('Confirm')",
        "div.TUXModal-overlay [data-e2e='modal-close-btn']",
        "div.TUXModal-overlay svg",
    ]
    
    for attempt in range(3):
        modal = page.locator("div.TUXModal-overlay")
        try:
            if not modal.is_visible(timeout=1500):
                break
        except Exception:
            break
        
        logger.info(f"TUXModal overlay detected (attempt {attempt + 1}), dismissing...")
        dismissed = False
        
        for selector in modal_dismiss_strategies:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=800):
                    btn.click(force=True)
                    time.sleep(0.5)
                    dismissed = True
                    logger.debug(f"Clicked dismiss via: {selector}")
                    break
            except Exception:
                continue
        
        if not dismissed:
            try:
                page.evaluate("""
                    document.querySelectorAll('div.TUXModal-overlay').forEach(el => el.remove());
                    document.querySelectorAll('[data-floating-ui-portal]').forEach(el => el.remove());
                """)
                logger.debug("Removed TUXModal overlay via JavaScript")
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Failed to remove modal via JS: {e}")
    
    # === 3. Final cleanup: force-remove any remaining blocking overlays ===
    try:
        page.evaluate("""
            // Remove any remaining overlays that block pointer events
            document.querySelectorAll('#react-joyride-portal').forEach(el => el.remove());
            document.querySelectorAll('.react-joyride__overlay').forEach(el => el.remove());
            document.querySelectorAll('[data-floating-ui-portal]').forEach(el => {
                if (el.querySelector('.TUXModal-overlay')) el.remove();
            });
        """)
    except Exception:
        pass
    
    logger.debug("Modal dismissal complete")


def upload_to_tiktok_cookies(video_path: Path, caption: str) -> Optional[Dict[str, Any]]:
    """Upload using Playwright browser automation with cookies."""
    try:
        from tiktok_uploader.upload import (
            TikTokUploader, _convert_videos_dict,
            _go_to_upload, _remove_cookies_window, _set_video,
            _remove_split_window, _set_interactivity,
            _set_description, _post_video
        )
        from tiktok_uploader import config
        import time
        
        cookies_path = str(_get_tiktok_cookies_path())
        logger.info(f"Initializing Playwright TikTok upload with filtered cookies...")
        
        uploader = TikTokUploader(
            cookies=cookies_path,
            browser="chromium",
            headless=True,
        )
        
        try:
            page = uploader.page  # triggers auth & browser launch
            
            # Navigate to upload page
            _go_to_upload(page)
            _remove_cookies_window(page)
            
            # Upload the video file
            _set_video(page, path=str(video_path.resolve()), num_retries=3)
            
            # CRITICAL: Dismiss copyright check / split modals BEFORE interacting
            _dismiss_tiktok_modals(page)
            _remove_split_window(page)
            _dismiss_tiktok_modals(page)
            
            # Set interactivity options
            _set_interactivity(page)
            
            # Set description/caption
            _dismiss_tiktok_modals(page)
            _set_description(page, caption)
            
            # Post the video
            _dismiss_tiktok_modals(page)
            _post_video(page)
            
            logger.success("✅ Video successfully uploaded to TikTok!")
            return {
                "status": "uploaded",
                "publish_id": "cookies_upload",
                "message": "Uploaded successfully via Playwright cookies automation"
            }
        finally:
            try:
                uploader.close()
            except Exception:
                pass
                
    except ImportError as e:
        logger.error(f"tiktok-uploader package is missing: {e}")
        return {"status": "failed", "error": f"tiktok-uploader package not installed: {e}"}
    except Exception as e:
        logger.error(f"TikTok cookie upload failed: {e}")
        return {"status": "failed", "error": str(e)}


def upload_to_tiktok(video_path: Path, metadata: Dict[str, Any], **kwargs) -> Optional[Dict[str, Any]]:
    """
    Upload a video to TikTok using either the cookies.txt method or the official API.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return {"status": "failed", "error": "Video file not found"}
        
    caption = metadata.get("caption", "Beautiful Quran Recitation")
    if len(caption) > 2200:
        caption = caption[:2197] + "..."
        
    # Method 1: cookies.txt (prioritized for simplicity)
    if Path("cookies.txt").exists():
        return upload_to_tiktok_cookies(video_path, caption)
        
    # Method 2: Official Developer API
    if get_tiktok_token():
        return upload_to_tiktok_api(video_path, caption)
        
    return {"status": "failed", "error": "No TikTok upload method configured. Add cookies.txt or developer keys."}


def get_tiktok_status() -> Dict[str, Any]:
    """Get overall TikTok configuration status."""
    if Path("cookies.txt").exists():
        try:
            import tiktok_uploader
            lib_installed = True
        except ImportError:
            lib_installed = False
            
        return {
            "enabled": True,
            "configured": True,
            "library_installed": lib_installed,
            "message": "TikTok active via cookies.txt automation" + ("" if lib_installed else " (tiktok-uploader package missing)")
        }
        
    has_keys = bool(TIKTOK_CLIENT_KEY) and bool(TIKTOK_CLIENT_SECRET)
    token_cached = Path(TIKTOK_TOKEN_PATH).exists()
    authorized = is_configured()
    
    if not has_keys:
        return {
            "enabled": False,
            "configured": False,
            "library_installed": True,
            "message": "TikTok not configured. Add cookies.txt or Developer API keys."
        }
        
    if not token_cached or not authorized:
        return {
            "enabled": True,
            "configured": False,
            "library_installed": True,
            "message": "TikTok Developer API keys found, but OAuth has not been authenticated."
        }
        
    return {
        "enabled": True,
        "configured": True,
        "library_installed": True,
        "message": "TikTok integration active via Developer API!"
    }
