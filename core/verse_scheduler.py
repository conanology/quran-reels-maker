"""
Verse Scheduler - Smart sequential progression through the Quran
"""
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from loguru import logger

from config.settings import (
    VERSE_COUNTS,
    SURAH_NAMES_AR,
    DEFAULT_VERSES_PER_REEL,
    MAX_VERSES_PER_REEL,
    MAX_REEL_DURATION_SECONDS,
    DEFAULT_RECITER,
    RECITERS
)
from database.models import (
    get_db_session,
    VerseProgress,
    ReelHistory,
    init_database
)
import os
from datetime import datetime
import pytz


class VerseSchedulerError(Exception):
    """Custom exception for verse scheduler errors"""
    pass


def is_friday() -> bool:
    """Check if today is Friday in the configured timezone."""
    from config.settings import TIMEZONE
    now = datetime.now(pytz.timezone(TIMEZONE))
    return now.weekday() == 4


def get_friday_verses() -> tuple:
    """
    Get random verses from Surah Al-Kahf (18) for Friday.
    
    Returns:
        Tuple of (surah, start_ayah, end_ayah) for Al-Kahf
    """
    import random
    
    # Surah Al-Kahf has 110 ayahs
    KAHF_TOTAL = 110
    
    # Pick a random starting point, ensuring we have room for at least 3 verses
    start = random.randint(1, KAHF_TOTAL - 3)
    end = start + 2  # Will be extended by minimum duration logic anyway
    
    return 18, start, end


def get_current_progress() -> Dict[str, Any]:
    """
    Get the current Quran reading progress.
    
    Returns:
        Dict with current surah, ayah, and percentage complete
    """
    session = get_db_session()
    try:
        progress = session.query(VerseProgress).first()
        
        if progress is None:
            # Initialize progress at the beginning
            progress = VerseProgress(
                current_surah=1,
                current_ayah=1,
                total_reels_generated=0
            )
            session.add(progress)
            session.commit()
        if progress.current_surah not in VERSE_COUNTS or not 1 <= progress.current_ayah <= VERSE_COUNTS[progress.current_surah]:
            raise VerseSchedulerError('Invalid journey cursor; explicit recovery is required')
        
        # Calculate percentage complete
        total_verses = sum(VERSE_COUNTS.values())
        current_absolute = sum(VERSE_COUNTS[s] for s in range(1, progress.current_surah)) + progress.current_ayah - 1
        percentage = (current_absolute / total_verses) * 100
        
        return {
            "surah": progress.current_surah,
            "surah_name": SURAH_NAMES_AR[progress.current_surah - 1],
            "ayah": progress.current_ayah,
            "total_reels": progress.total_reels_generated,
            "percentage_complete": round(percentage, 2),
            "verses_remaining": total_verses - current_absolute
        }
    finally:
        session.close()


def get_next_verses(
    verses_count: int = DEFAULT_VERSES_PER_REEL
) -> Tuple[int, int, int]:
    """
    Get the next set of verses to generate a reel for.
    
    Args:
        verses_count: Number of verses to include in the reel
        
    Returns:
        Tuple of (surah, start_ayah, end_ayah)
    """
    if verses_count < 1:
        raise VerseSchedulerError('Verse count must be positive')
    verses_count = min(verses_count, MAX_VERSES_PER_REEL)
    
    session = get_db_session()
    try:
        progress = session.query(VerseProgress).first()
        
        if progress is None:
            # Initialize at beginning of Quran
            return 1, 1, min(verses_count, VERSE_COUNTS[1])
        
        surah = progress.current_surah
        start_ayah = progress.current_ayah
        if surah not in VERSE_COUNTS or not 1 <= start_ayah <= VERSE_COUNTS[surah]:
            raise VerseSchedulerError('Invalid journey cursor; explicit recovery is required')
        
        # Calculate end ayah
        max_ayah_in_surah = VERSE_COUNTS[surah]
        end_ayah = min(start_ayah + verses_count - 1, max_ayah_in_surah)
        
        return surah, start_ayah, end_ayah
        
    finally:
        session.close()


def next_position(surah: int, last_ayah: int) -> tuple:
    if surah not in VERSE_COUNTS or not 1 <= last_ayah <= VERSE_COUNTS[surah]:
        raise VerseSchedulerError('Invalid published Quran range')
    if last_ayah == VERSE_COUNTS[surah]:
        return (surah + 1, 1) if surah < 114 else (1, 1)
    return surah, last_ayah + 1


def advance_progress(surah: int, last_ayah: int) -> Dict[str, Any]:
    """Advance confirmed sequential coverage; automatic flows use job finalization."""
    from database.jobs import writer_lock
    target_surah,target_ayah=next_position(surah,last_ayah)
    with writer_lock():
        session=get_db_session()
        try:
            progress=session.query(VerseProgress).first()
            if progress is None:
                session.add(VerseProgress(current_surah=target_surah,current_ayah=target_ayah,total_reels_generated=1))
            elif progress.current_surah==surah:
                progress.current_surah,progress.current_ayah=target_surah,target_ayah
                progress.total_reels_generated+=1
            else:
                # Friday and other thematic content has a separate reservation.
                return get_current_progress()
            session.commit()
        finally:
            session.close()
    return get_current_progress()


def record_reel_history(
    surah: int,
    start_ayah: int,
    end_ayah: int,
    reciter_key: str,
    video_path: str,
    youtube_id: Optional[str] = None
) -> int:
    """
    Record a generated reel in the history.
    
    Args:
        surah: Surah number
        start_ayah: Starting ayah
        end_ayah: Ending ayah
        reciter_key: Reciter used
        video_path: Path to generated video
        youtube_id: YouTube video ID if uploaded
        
    Returns:
        ID of the created history record
    """
    session = get_db_session()
    try:
        reciter_info = RECITERS.get(reciter_key, {})
        
        history = ReelHistory(
            surah=surah,
            start_ayah=start_ayah,
            end_ayah=end_ayah,
            reciter_key=reciter_key,
            reciter_name=reciter_info.get("name_ar", reciter_key),
            video_path=video_path,
            youtube_id=youtube_id,
            status="generated" if youtube_id is None else "uploaded"
        )
        
        session.add(history)
        session.commit()
        
        logger.info(f"Recorded reel history: {surah}:{start_ayah}-{end_ayah}")
        return history.id
        
    finally:
        session.close()


def update_reel_youtube_id(history_id: int, youtube_id: str) -> None:
    """
    Update a reel history record with its YouTube ID after upload.
    
    Args:
        history_id: ID of the history record
        youtube_id: YouTube video ID
    """
    session = get_db_session()
    try:
        history = session.query(ReelHistory).filter_by(id=history_id).first()
        if history:
            history.youtube_id = youtube_id
            history.status = "uploaded"
            session.commit()
            logger.info(f"Updated reel {history_id} with YouTube ID: {youtube_id}")
    finally:
        session.close()


def get_reel_history(limit: int = 10) -> list[Dict[str, Any]]:
    """
    Get recent reel generation history.
    
    Args:
        limit: Maximum number of records to return
        
    Returns:
        List of history records as dicts
    """
    session = get_db_session()
    try:
        records = session.query(ReelHistory)\
            .order_by(ReelHistory.created_at.desc())\
            .limit(limit)\
            .all()
        
        return [
            {
                "id": r.id,
                "surah": r.surah,
                "surah_name": SURAH_NAMES_AR[r.surah - 1],
                "start_ayah": r.start_ayah,
                "end_ayah": r.end_ayah,
                "reciter": r.reciter_name,
                "video_path": r.video_path,
                "youtube_id": r.youtube_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in records
        ]
    finally:
        session.close()


def check_if_already_posted(surah: int, start_ayah: int, end_ayah: int) -> bool:
    """
    Check if these exact verses have already been posted.
    
    Args:
        surah: Surah number
        start_ayah: Starting ayah
        end_ayah: Ending ayah
        
    Returns:
        True if already posted, False otherwise
    """
    session = get_db_session()
    try:
        existing = session.query(ReelHistory).filter_by(
            surah=surah,
            start_ayah=start_ayah,
            end_ayah=end_ayah,
            status="uploaded"
        ).first()
        
        return existing is not None
    finally:
        session.close()


def reset_progress() -> None:
    """Explicit owner reset also reconciles a legacy publication cursor."""
    set_progress(1,1)


def set_progress(surah: int, ayah: int) -> Dict[str, Any]:
    """Explicit owner reconciliation of the next unpublished Quran position."""
    if surah not in VERSE_COUNTS:
        raise VerseSchedulerError(f'Invalid surah number: {surah}')
    if not 1 <= ayah <= VERSE_COUNTS[surah]:
        raise VerseSchedulerError(f'Invalid ayah {ayah} for surah {surah} (max: {VERSE_COUNTS[surah]})')
    from database.jobs import writer_lock
    from database.models import AppSettings
    with writer_lock():
        init_database()
        session=get_db_session()
        try:
            progress=session.query(VerseProgress).first()
            if progress is None:
                progress=VerseProgress(current_surah=surah,current_ayah=ayah,total_reels_generated=0)
                session.add(progress)
            else:
                progress.current_surah,progress.current_ayah=surah,ayah
            marker=session.query(AppSettings).filter_by(key='publication_cursor_verified').one()
            marker.value='true'
            session.commit()
        finally:
            session.close()
    logger.info(f'Publication cursor reconciled to Surah {surah}, Ayah {ayah}')
    return get_current_progress()


def get_statistics() -> Dict[str, Any]:
    """
    Get overall statistics about reel generation.
    
    Returns:
        Dict with various statistics
    """
    session = get_db_session()
    try:
        progress = get_current_progress()
        
        total_reels = session.query(ReelHistory).count()
        uploaded_reels = session.query(ReelHistory).filter_by(status="uploaded").count()
        
        # Get reciter distribution
        from sqlalchemy import func
        reciter_counts = session.query(
            ReelHistory.reciter_key,
            func.count(ReelHistory.id)
        ).group_by(ReelHistory.reciter_key).all()
        
        return {
            **progress,
            "total_reels_in_history": total_reels,
            "uploaded_reels": uploaded_reels,
            "pending_upload": total_reels - uploaded_reels,
            "reciter_distribution": dict(reciter_counts)
        }
    finally:
        session.close()
