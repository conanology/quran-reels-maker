"""
Telegram Bot - Notification and Approval System
"""
import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger

# Telegram settings from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
APPROVAL_REQUIRED = os.getenv("APPROVAL_REQUIRED", "true").lower() == "true"
APPROVAL_TIMEOUT_SECONDS = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "3600"))  # 1 hour default

# Telegram API base URL
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def is_configured() -> bool:
    """Check if Telegram is properly configured."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_message(text: str, reply_markup: Optional[Dict] = None) -> Optional[Dict]:
    """Send a text message to the configured chat."""
    if not is_configured():
        logger.warning("Telegram not configured. Skipping notification.")
        return None
    
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Telegram send failed: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return None


def send_video(video_path: Path, caption: str, reply_markup: Optional[Dict] = None) -> Optional[Dict]:
    """Send a video file to the configured chat."""
    if not is_configured():
        logger.warning("Telegram not configured. Skipping video notification.")
        return None
    
    url = f"{TELEGRAM_API}/sendVideo"
    
    try:
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML"
            }
            
            if reply_markup:
                import json
                data["reply_markup"] = json.dumps(reply_markup)
            
            response = requests.post(url, data=data, files=files, timeout=120)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Telegram video send failed: {response.text}")
                return None
    except Exception as e:
        logger.error(f"Telegram video error: {e}")
        return None


def send_approval_request(
    video_path: Path,
    surah_name: str,
    surah_num: int,
    start_ayah: int,
    end_ayah: int,
    reciter_name: str,
    duration: float
) -> Optional[str]:
    """
    Send video for approval and return message ID for tracking.
    """
    caption = f"""🕌 <b>New Quran Reel Ready for Review</b>

📖 <b>Surah:</b> {surah_name} ({surah_num})
🔢 <b>Verses:</b> {start_ayah} - {end_ayah}
🎙️ <b>Reciter:</b> {reciter_name}
⏱️ <b>Duration:</b> {duration:.1f}s

<i>Reply with:</i>
✅ <code>approve</code> - Upload to YouTube
❌ <code>reject</code> - Delete and regenerate
🔄 <code>regenerate</code> - New background/reciter"""

    result = send_video(video_path, caption)
    
    if result and result.get('ok'):
        message_id = result['result']['message_id']
        logger.info(f"Approval request sent. Message ID: {message_id}")
        return str(message_id)
    
    return None


def get_updates(offset: Optional[int] = None) -> list:
    """Get new messages/updates from Telegram."""
    if not is_configured():
        return []
    
    url = f"{TELEGRAM_API}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    
    try:
        response = requests.get(url, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            return data.get('result', [])
        return []
    except Exception as e:
        logger.error(f"Telegram getUpdates error: {e}")
        return []


def wait_for_approval(timeout_seconds: int = None) -> str:
    """
    Wait for user approval response.
    
    Returns:
        'approved' - User approved
        'rejected' - User rejected
        'regenerate' - User wants regeneration
        'timeout' - No response within timeout
        'skip' - Telegram not configured (auto-approve)
    """
    if not is_configured():
        logger.info("Telegram not configured. Auto-approving.")
        return 'skip'
    
    if not APPROVAL_REQUIRED:
        logger.info("Approval not required. Auto-approving.")
        return 'approved'
    
    timeout = timeout_seconds or APPROVAL_TIMEOUT_SECONDS
    start_time = time.time()
    last_update_id = None
    
    logger.info(f"Waiting for approval (timeout: {timeout}s)...")
    
    # First, clear any old updates
    updates = get_updates()
    if updates:
        last_update_id = updates[-1]['update_id'] + 1
    
    while (time.time() - start_time) < timeout:
        updates = get_updates(offset=last_update_id)
        
        for update in updates:
            last_update_id = update['update_id'] + 1
            
            # Check for message
            message = update.get('message', {})
            text = message.get('text', '').lower().strip()
            chat_id = str(message.get('chat', {}).get('id', ''))
            
            # Only accept from configured chat
            if chat_id != TELEGRAM_CHAT_ID:
                continue
            
            if text in ['approve', 'yes', '✅', 'ok', 'نعم', 'موافق']:
                logger.info("User approved the video")
                send_message("✅ <b>Approved!</b> Uploading to YouTube...")
                return 'approved'
            
            elif text in ['reject', 'no', '❌', 'delete', 'لا', 'رفض']:
                logger.info("User rejected the video")
                send_message("❌ <b>Rejected.</b> Video will be deleted.")
                return 'rejected'
            
            elif text in ['regenerate', 'retry', 'again', '🔄', 'اعادة']:
                logger.info("User requested regeneration")
                send_message("🔄 <b>Regenerating...</b> New background and reciter will be selected.")
                return 'regenerate'
        
        # Wait a bit before checking again
        time.sleep(2)
    
    logger.warning("Approval timeout reached")
    send_message("⏰ <b>Timeout!</b> No response received. Video will NOT be uploaded.")
    return 'timeout'


def notify_upload_success(youtube_url: str):
    """Notify user that upload was successful."""
    send_message(f"""🎉 <b>Upload Successful!</b>

🔗 <a href="{youtube_url}">{youtube_url}</a>

The video is now live on YouTube!""")


def notify_upload_failure(error: str):
    """Notify user that upload failed."""
    send_message(f"""⚠️ <b>Upload Failed</b>

Error: <code>{error}</code>

The video has been saved locally. You can retry manually.""")
