"""
Telegram Bot - Notification and Approval System
"""
import os
import time
import requests
import secrets
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
            logger.error(f"Telegram send failed: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Telegram request failed: {type(e).__name__}")
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
                logger.error(f"Telegram video send failed: HTTP {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Telegram video request failed: {type(e).__name__}")
        return None


def send_photo(photo_path: Path, caption: str = '') -> Optional[Dict]:
    """Deliver the exact proposed thumbnail for the bound final package review."""
    if not is_configured():
        return None
    try:
        with Path(photo_path).open('rb') as source:
            response=requests.post(f'{TELEGRAM_API}/sendPhoto',
                data={'chat_id':TELEGRAM_CHAT_ID,'caption':caption},files={'photo':source},timeout=30)
        return response.json() if response.status_code==200 else None
    except Exception as error:
        logger.error(f'Thumbnail review delivery failed: {type(error).__name__}')
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
        logger.error(f"Telegram updates request failed: {type(e).__name__}")
        return []


def wait_for_approval(timeout_seconds: int = None, *, request_message_id=None,
                      nonce=None, package_hash=None, job_id=None, initial_offset=None) -> str:
    """
    Wait for user approval response.
    
    Returns:
        'approved' - User approved
        'rejected' - User rejected
        'regenerate' - User wants regeneration
        'timeout' - No response within timeout
        'unavailable' - required review configuration is missing
    """
    if not is_configured():
        return 'unavailable'
    
    approver_id = os.getenv('TELEGRAM_APPROVER_ID', '')
    if not all((approver_id, request_message_id, nonce, package_hash, job_id)):
        return 'unavailable'
    
    timeout = timeout_seconds or APPROVAL_TIMEOUT_SECONDS
    start_time = time.time()
    last_update_id = initial_offset
    
    logger.info(f"Waiting for approval (timeout: {timeout}s)...")
    
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
            if str(message.get('from', {}).get('id', '')) != approver_id:
                continue
            if str(message.get('reply_to_message', {}).get('message_id', '')) != str(request_message_id):
                continue
            # Require explicit nonce plus package hash. An old "ok" must never
            # authorize another video or concurrent job.
            pieces = text.split()
            if len(pieces) != 3 or not secrets.compare_digest(pieces[1], nonce.lower()) or not secrets.compare_digest(pieces[2], package_hash.lower()):
                continue
            text = pieces[0]
            
            if text in ['approve', 'yes', '✅', 'ok', 'نعم', 'موافق']:
                logger.info("User approved the video")
                send_message("✅ <b>Approved.</b> The reviewed platform operation may now proceed.")
                return 'approved'
            
            elif text in ['reject', 'no', '❌', 'delete', 'لا', 'رفض']:
                logger.info("User rejected the video")
                send_message("❌ <b>Rejected.</b> Publication stopped; local media retained.")
                return 'rejected'
            
            elif text in ['regenerate', 'retry', 'again', '🔄', 'اعادة']:
                logger.info("User requested regeneration")
                send_message("🔄 <b>Regeneration requested.</b> The same reserved verses and reciter will be reviewed again.")
                return 'regenerate'
        
        # Wait a bit before checking again
        time.sleep(2)
    
    logger.warning("Approval timeout reached")
    send_message("⏰ <b>Timeout.</b> No publication was authorized.")
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
