"""
YouTube Uploader - Upload videos to YouTube using the Data API v3
"""
import os
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from config.settings import (
    YOUTUBE_CATEGORY_ID,
    YOUTUBE_PRIVACY_STATUS,
    YOUTUBE_MADE_FOR_KIDS,
    YOUTUBE_DEFAULT_TAGS,
    YOUTUBE_TITLE_TEMPLATE,
    YOUTUBE_DESCRIPTION_TEMPLATE,
    SURAH_NAMES_AR,
    SURAH_NAMES_EN,
    RECITERS
)
from youtube.auth import get_authenticated_service, YouTubeAuthError


class YouTubeUploadError(Exception):
    """Custom exception for YouTube upload errors"""
    pass


# Retry configuration for transient errors
MAX_RETRIES = 5
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
RETRIABLE_EXCEPTIONS = (IOError,)


def generate_metadata(
    surah: int,
    start_ayah: int,
    end_ayah: int,
    reciter_key: str,
    full_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate YouTube video metadata (title, description, tags).
    
    Args:
        surah: Surah number (1-114)
        start_ayah: Starting ayah number
        end_ayah: Ending ayah number
        reciter_key: Key from RECITERS dict
        full_text: Optional full Arabic text to include in description
        
    Returns:
        Dict with title, description, and tags
    """
    surah_name_ar = SURAH_NAMES_AR[surah - 1]
    surah_name_en = SURAH_NAMES_EN[surah - 1]
    
    reciter_info = RECITERS.get(reciter_key, {})
    reciter_name_ar = reciter_info.get("name_ar", reciter_key)
    reciter_name_en = reciter_info.get("name_en", reciter_key)
    
    # Format verse range
    if start_ayah == end_ayah:
        verse_range = str(start_ayah)
    else:
        verse_range = f"{start_ayah}-{end_ayah}"
    
    # Generate title
    title = YOUTUBE_TITLE_TEMPLATE.format(
        surah_name_ar=surah_name_ar,
        verse_range=verse_range,
        reciter_name_ar=reciter_name_ar
    )
    
    # Truncate title if too long (YouTube limit is 100 chars)
    if len(title) > 100:
        title = title[:97] + "..."
    
    # Generate description
    description = YOUTUBE_DESCRIPTION_TEMPLATE.format(
        full_text=full_text or "",
        surah_name_ar=surah_name_ar,
        surah_name_en=surah_name_en,
        surah_num=surah,
        verse_start=start_ayah,
        verse_end=end_ayah,
        reciter_name_ar=reciter_name_ar,
        reciter_name_en=reciter_name_en
    )
    
    # Generate tags
    tags = list(YOUTUBE_DEFAULT_TAGS)
    tags.extend([
        f"سورة {surah_name_ar}",
        f"Surah {surah_name_en}",
        reciter_name_ar,
        reciter_name_en
    ])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_tags = []
    for tag in tags:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            unique_tags.append(tag)
    
    return {
        "title": title,
        "description": description,
        "tags": unique_tags[:500]  # YouTube limit
    }


def upload_video(
    video_path: Path,
    metadata: Dict[str, Any],
    privacy_status: str = YOUTUBE_PRIVACY_STATUS,
    notify_subscribers: bool = True
) -> Dict[str, Any]:
    """
    Upload a video to YouTube.
    
    Args:
        video_path: Path to the video file
        metadata: Dict with title, description, and tags
        privacy_status: 'public', 'private', or 'unlisted'
        notify_subscribers: Whether to notify channel subscribers
        
    Returns:
        Dict with upload result including video ID
        
    Raises:
        YouTubeUploadError: If upload fails
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        raise YouTubeUploadError(f"Video file not found: {video_path}")
    
    # Get authenticated service
    try:
        service = get_authenticated_service()
    except YouTubeAuthError as e:
        raise YouTubeUploadError(f"Authentication failed: {e}") from e
    
    # Prepare video metadata
    body = {
        'snippet': {
            'title': metadata['title'],
            'description': metadata['description'],
            'tags': metadata.get('tags', []),
            'categoryId': YOUTUBE_CATEGORY_ID
        },
        'status': {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': YOUTUBE_MADE_FOR_KIDS,
            'madeForKids': YOUTUBE_MADE_FOR_KIDS
        }
    }
    
    # If not notifying subscribers (for test uploads)
    if not notify_subscribers:
        body['status']['notifySubscribers'] = False
    
    logger.info(f"Uploading video: {metadata['title']}")
    logger.debug(f"File: {video_path}")
    
    # Create media upload
    media = MediaFileUpload(
        str(video_path),
        mimetype='video/mp4',
        resumable=True,
        chunksize=1024*1024  # 1MB chunks
    )
    
    # Create upload request
    request = service.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media,
        notifySubscribers=notify_subscribers
    )
    
    # Execute with retry logic
    response = _execute_with_retry(request)
    
    if response:
        video_id = response['id']
        video_url = f"https://youtube.com/shorts/{video_id}"
        
        logger.success(f"✅ Video uploaded successfully!")
        logger.success(f"   Video ID: {video_id}")
        logger.success(f"   URL: {video_url}")
        
        return {
            'success': True,
            'video_id': video_id,
            'url': video_url,
            'title': metadata['title'],
            'privacy_status': privacy_status
        }
    
    raise YouTubeUploadError("Upload returned no response")


def _execute_with_retry(request) -> Optional[Dict]:
    """
    Execute an upload request with exponential backoff retry.
    
    Args:
        request: The upload request to execute
        
    Returns:
        Response dict or None
    """
    response = None
    retry = 0
    
    while response is None:
        try:
            logger.debug("Uploading chunk...")
            status, response = request.next_chunk()
            
            if status:
                progress = int(status.progress() * 100)
                logger.debug(f"Upload progress: {progress}%")
                
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error_msg = f"Retriable HTTP error {e.resp.status}: {e.content}"
            else:
                raise YouTubeUploadError(f"HTTP error: {e.resp.status} - {e.content}")
            
            retry = _handle_retry(retry, error_msg)
            
        except RETRIABLE_EXCEPTIONS as e:
            retry = _handle_retry(retry, str(e))
    
    return response


def _handle_retry(retry_count: int, error_msg: str) -> int:
    """
    Handle retry logic with exponential backoff.
    
    Args:
        retry_count: Current retry count
        error_msg: Error message for logging
        
    Returns:
        Incremented retry count
        
    Raises:
        YouTubeUploadError: If max retries exceeded
    """
    if retry_count >= MAX_RETRIES:
        raise YouTubeUploadError(f"Max retries exceeded. Last error: {error_msg}")
    
    retry_count += 1
    wait_time = random.uniform(0, 2 ** retry_count)
    
    logger.warning(f"Upload error: {error_msg}")
    logger.warning(f"Retrying in {wait_time:.1f} seconds... (attempt {retry_count}/{MAX_RETRIES})")
    
    time.sleep(wait_time)
    return retry_count


def upload_as_private(video_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upload a video as private (for testing).
    
    Args:
        video_path: Path to the video file
        metadata: Video metadata
        
    Returns:
        Upload result dict
    """
    return upload_video(
        video_path,
        metadata,
        privacy_status='private',
        notify_subscribers=False
    )


def upload_as_unlisted(video_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upload a video as unlisted (shareable but not public).
    
    Args:
        video_path: Path to the video file
        metadata: Video metadata
        
    Returns:
        Upload result dict
    """
    return upload_video(
        video_path,
        metadata,
        privacy_status='unlisted',
        notify_subscribers=False
    )


def get_upload_quota_usage() -> Dict[str, Any]:
    """
    Get information about API quota usage.
    Note: YouTube doesn't provide direct quota info,
    this just provides general guidance.
    
    Returns:
        Dict with quota information
    """
    return {
        "daily_quota": 10000,
        "upload_cost": 1600,
        "max_uploads_per_day": 6,
        "note": "YouTube API quotas reset at midnight Pacific Time"
    }


def check_video_status(video_id: str) -> Dict[str, Any]:
    """
    Check the status of an uploaded video.
    
    Args:
        video_id: YouTube video ID
        
    Returns:
        Dict with video status info
    """
    try:
        service = get_authenticated_service()
        
        response = service.videos().list(
            part='status,snippet,statistics',
            id=video_id
        ).execute()
        
        if 'items' in response and len(response['items']) > 0:
            video = response['items'][0]
            return {
                'found': True,
                'id': video_id,
                'title': video['snippet']['title'],
                'privacy_status': video['status']['privacyStatus'],
                'upload_status': video['status']['uploadStatus'],
                'views': video['statistics'].get('viewCount', 0),
                'likes': video['statistics'].get('likeCount', 0)
            }
        
        return {'found': False, 'id': video_id}
        
    except Exception as e:
        logger.error(f"Failed to check video status: {e}")
        return {'found': False, 'id': video_id, 'error': str(e)}
