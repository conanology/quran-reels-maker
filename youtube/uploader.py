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
    
    # === AI Brain Metadata Generation ===
    from core.quran_api import get_ayah_translation
    from core.ai_brain import generate_video_metadata
    
    translations = []
    if os.getenv("ENABLE_AI_METADATA", "false").lower() == "true":
        for a in range(start_ayah, end_ayah + 1):
            t = get_ayah_translation(surah, a)
            if t:
                translations.append(t)
    translation_text = " ".join(translations).strip()
    
    ai_metadata = None
    if translation_text:
        try:
            ai_metadata = generate_video_metadata(
                surah_name=surah_name_en,
                start_ayah=start_ayah,
                end_ayah=end_ayah,
                reciter_name=reciter_name_en,
                translation=translation_text
            )
        except Exception as e:
            logger.error(f"Error during AI metadata generation: {type(e).__name__}")
            
    if ai_metadata and ai_metadata.get("title") and ai_metadata.get("description"):
        title = ai_metadata["title"]
        description = ai_metadata["description"]
        tags = ai_metadata.get("tags", [])
        
        # Ensure title limit is respected (YouTube limit is 100 chars)
        if len(title) > 100:
            title = title[:97] + "..."
            
        # Add fallback template tags if missing to ensure discoverability
        for req_tag in [surah_name_ar, f"سورة {surah_name_ar}", surah_name_en, f"Surah {surah_name_en}", reciter_name_ar, reciter_name_en]:
            if req_tag.lower() not in [t.lower() for t in tags]:
                tags.append(req_tag)
                
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
            "tags": unique_tags[:500]
        }
    
    # === FALLBACK TO ORIGINAL TEMPLATES ===
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
    notify_subscribers: bool = True,
    *, automatic: bool = False, job_id=None, expected_channel_id=None,
    approval=None, receipt_callback=None, processing_timeout: float = 120, thumbnail_path=None
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
    if privacy_status not in ('public','private','unlisted'):
        raise YouTubeUploadError('Invalid privacy status')
    if automatic:
        from notifications.publishing_policy import package_digest
        expected_channel_id = expected_channel_id or os.getenv('YOUTUBE_EXPECTED_CHANNEL_ID','')
        if not expected_channel_id or not job_id or not approval:
            raise YouTubeUploadError('Automatic upload requires expected identity, job and final approval')
        digest,_ = package_digest(video_path,metadata,platform='youtube',privacy_status=privacy_status,
                                  expected_account=expected_channel_id,thumbnail_path=thumbnail_path)
        if approval.get('job_id') != job_id or approval.get('package_hash') != digest:
            raise YouTubeUploadError('Approval does not match final package')
        actual_thumbnail=str(Path(thumbnail_path).resolve()) if thumbnail_path else None
        if approval.get('thumbnail_path') != actual_thumbnail:
            raise YouTubeUploadError('Thumbnail differs from reviewed package')
    if job_id:
        from database.jobs import read_upload_receipts, record_upload_receipt, assert_transfer_retry_safe, begin_upload_attempt
        receipts = read_upload_receipts(job_id)
        previous = receipts.get('youtube')
        if previous:
            # A durable remote identifier forbids a second insertion. Resume only
            # reconciles the existing transfer even after a failed DB commit.
            if previous.get('status') in ('published','processed'):
                return previous
            service=get_authenticated_service()
            return _wait_for_processing(service,previous,privacy_status,expected_channel_id,
                                        processing_timeout,lambda r:record_upload_receipt(job_id,'youtube',r))
        assert_transfer_retry_safe(job_id,'youtube')
    
    # Get authenticated service
    try:
        service = get_authenticated_service()
    except YouTubeAuthError as e:
        raise YouTubeUploadError(f"Authentication failed: {e}") from e
    if expected_channel_id:
        identity=service.channels().list(part='id',mine=True).execute()
        ids=[item.get('id') for item in identity.get('items',[])]
        if ids != [expected_channel_id]:
            raise YouTubeUploadError('Authenticated YouTube channel does not match intended identity')
    
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
    if job_id:
        begin_upload_attempt(job_id,'youtube')
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
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        logger.success(f"✅ Video uploaded successfully!")
        logger.success(f"   Video ID: {video_id}")
        logger.success(f"   URL: {video_url}")
        
        receipt = {
            'success': True,
            'video_id': video_id,
            'url': video_url,
            'title': metadata['title'],
            'privacy_status': privacy_status,
            'status': 'transferred'
        }
        def save_receipt(value):
            if job_id:
                record_upload_receipt(job_id,'youtube',value)
            if receipt_callback:
                receipt_callback(value)
        save_receipt(receipt)
        return _wait_for_processing(service,receipt,privacy_status,expected_channel_id,
                                    processing_timeout,save_receipt)
    
    raise YouTubeUploadError("Upload returned no response")


def _wait_for_processing(service, receipt, intended_privacy, expected_channel_id, timeout, save):
    deadline=time.monotonic()+timeout
    while time.monotonic() < deadline:
        result=service.videos().list(part='status,processingDetails,snippet',id=receipt['video_id']).execute()
        items=result.get('items',[])
        if items:
            item=items[0]
            status=item.get('status',{})
            processing=item.get('processingDetails',{}).get('processingStatus')
            if expected_channel_id and item.get('snippet',{}).get('channelId') != expected_channel_id:
                raise YouTubeUploadError('Uploaded video belongs to an unexpected channel')
            if status.get('privacyStatus') != intended_privacy:
                raise YouTubeUploadError('Server visibility differs from intended privacy')
            if processing == 'failed' or status.get('uploadStatus') in ('failed','rejected','deleted'):
                failed=dict(receipt,status='failed',success=False)
                save(failed)
                raise YouTubeUploadError('YouTube processing failed; existing receipt retained')
            if processing == 'succeeded' and status.get('uploadStatus') == 'processed':
                final=dict(receipt,status='published' if intended_privacy=='public' else 'processed',
                           privacy_status=status['privacyStatus'],success=True)
                save(final)
                return final
        time.sleep(min(3,max(0,deadline-time.monotonic())))
    pending=dict(receipt,status='processing',success=False)
    save(pending)
    raise YouTubeUploadError('YouTube processing deadline elapsed; reconcile receipt before retry')


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
                error_msg = f"Retriable HTTP error {e.resp.status}"
            else:
                raise YouTubeUploadError(f"HTTP error: {e.resp.status}")
            
            retry = _handle_retry(retry, error_msg)
            
        except RETRIABLE_EXCEPTIONS as e:
            retry = _handle_retry(retry, type(e).__name__)
    
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
        logger.error(f"Failed to check video status: {type(e).__name__}")
        return {'found': False, 'id': video_id, 'error': str(e)}


def thumbnail_mimetype(thumbnail_path: Path) -> Optional[str]:
    """
    MIME type for a thumbnail, or None if YouTube will not accept it.

    The type was hardcoded to image/jpeg while the documentary path writes PNG,
    so those uploads were declared as the wrong format. thumbnails.set accepts
    only JPEG and PNG - notably not WEBP.
    """
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(thumbnail_path.suffix.lower())


def upload_thumbnail(video_id: str, thumbnail_path: Path, *, automatic=False, approval=None,
                     expected_channel_id=None) -> Optional[Dict[str, Any]]:
    """
    Upload a custom thumbnail for a YouTube video.
    
    Args:
        video_id: The ID of the uploaded YouTube video
        thumbnail_path: Path to the JPG thumbnail file
        
    Returns:
        API response dictionary if successful, None otherwise
    """
    thumbnail_path = Path(thumbnail_path)
    if automatic:
        from notifications.publishing_policy import thumbnail_digest
        from database.jobs import read_upload_receipts
        if not approval or approval.get('thumbnail_path')!=str(thumbnail_path.resolve()) or approval.get('thumbnail_sha256')!=thumbnail_digest(thumbnail_path):
            raise YouTubeUploadError('Thumbnail differs from approved final package')
        receipt=read_upload_receipts(approval['job_id']).get('youtube',{})
        if receipt.get('video_id')!=video_id:
            raise YouTubeUploadError('Thumbnail target differs from approved job receipt')
        expected_channel_id=expected_channel_id or approval.get('expected_account')
        if not expected_channel_id:
            raise YouTubeUploadError('Thumbnail requires intended channel identity')
    if not thumbnail_path.exists():
        logger.error(f"Thumbnail file not found: {thumbnail_path}")
        return None

    mimetype = thumbnail_mimetype(thumbnail_path)
    if mimetype is None:
        logger.error(
            f"Unsupported thumbnail format '{thumbnail_path.suffix}'; "
            f"YouTube accepts JPEG and PNG only"
        )
        return None

    try:
        service = get_authenticated_service()
        if expected_channel_id:
            identity=service.channels().list(part='id',mine=True).execute()
            if [item.get('id') for item in identity.get('items',[])] != [expected_channel_id]:
                raise YouTubeUploadError('Thumbnail channel identity mismatch')
            target=service.videos().list(part='snippet',id=video_id).execute().get('items',[])
            if len(target)!=1 or target[0].get('snippet',{}).get('channelId')!=expected_channel_id:
                raise YouTubeUploadError('Thumbnail target channel identity mismatch')
        logger.info(f"Uploading custom thumbnail for video {video_id} from {thumbnail_path.name}...")

        media = MediaFileUpload(
            str(thumbnail_path),
            mimetype=mimetype
        )
        
        request = service.thumbnails().set(
            videoId=video_id,
            media_body=media
        )
        
        response = request.execute()
        logger.success(f"✅ Successfully uploaded custom thumbnail for video {video_id}")
        return response
        
    except Exception as e:
        logger.error(f"Failed to upload custom thumbnail for video {video_id}: {type(e).__name__}")
        return None

