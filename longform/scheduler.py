"""
Longform Scheduler - Groups surahs from scratch based on VERSE_COUNTS,
tracks compilation progress, and decides what to compile next.
"""
import json
import math
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from loguru import logger

from config.settings import (
    SURAH_NAMES_AR,
    SURAH_NAMES_EN,
    VERSE_COUNTS,
    LONGFORM_MIN_DURATION,
    LONGFORM_MAX_DURATION,
)
from database.models import get_db_session, LongformHistory


def create_compilation_groups_from_scratch(avg_ayah_duration: float = 20.0) -> List[Dict[str, Any]]:
    """
    Create compilation groups from scratch based on Quran VERSE_COUNTS.
    
    Strategy:
    1. Loop from Surah 1 to 114.
    2. Estimate duration = verse_count * avg_ayah_duration.
    3. If duration >= LONGFORM_MIN_DURATION:
       - Finalize any pending short surah group.
       - If duration > LONGFORM_MAX_DURATION, split into parts.
       - Else, compile as a single full surah.
    4. If duration < LONGFORM_MIN_DURATION:
       - Add to current pending group.
       - Once pending group duration >= LONGFORM_MIN_DURATION, finalize it.
    
    Returns:
        List of compilation group dicts with:
        - title: str
        - surah_start: int
        - surah_end: int
        - ayah_start: Optional[int]
        - ayah_end: Optional[int]
        - estimated_duration: float
    """
    compilations = []
    
    pending_surahs = []
    pending_duration = 0.0
    
    def finalize_pending():
        nonlocal pending_surahs, pending_duration
        if not pending_surahs:
            return
        
        surah_start = pending_surahs[0]
        surah_end = pending_surahs[-1]
        
        if surah_start == surah_end:
            name_ar = SURAH_NAMES_AR[surah_start - 1]
            name_en = SURAH_NAMES_EN[surah_start - 1]
            title = f"سورة {name_ar} كاملة | {name_en} Full | Beautiful Quran Recitation"
        else:
            start_ar = SURAH_NAMES_AR[surah_start - 1]
            end_ar = SURAH_NAMES_AR[surah_end - 1]
            start_en = SURAH_NAMES_EN[surah_start - 1]
            end_en = SURAH_NAMES_EN[surah_end - 1]
            title = f"سورة {start_ar} إلى سورة {end_ar} | {start_en} to {end_en} | Beautiful Quran Recitation"
            
        compilations.append({
            "title": title,
            "surah_start": surah_start,
            "surah_end": surah_end,
            "ayah_start": None,
            "ayah_end": None,
            "estimated_duration": pending_duration,
        })
        pending_surahs = []
        pending_duration = 0.0

    for surah_num in range(1, 115):
        verse_count = VERSE_COUNTS[surah_num]
        est_duration = verse_count * avg_ayah_duration
        
        if est_duration >= LONGFORM_MIN_DURATION:
            # First, finalize any short surahs accumulated so far
            finalize_pending()
            
            surah_name_ar = SURAH_NAMES_AR[surah_num - 1]
            surah_name_en = SURAH_NAMES_EN[surah_num - 1]
            
            # Check if it needs splitting
            if est_duration > LONGFORM_MAX_DURATION:
                num_parts = math.ceil(est_duration / LONGFORM_MAX_DURATION)
                verses_per_part = math.ceil(verse_count / num_parts)
                
                for p in range(1, num_parts + 1):
                    start_a = (p - 1) * verses_per_part + 1
                    end_a = min(p * verses_per_part, verse_count)
                    part_duration = (end_a - start_a + 1) * avg_ayah_duration
                    
                    compilations.append({
                        "title": f"سورة {surah_name_ar} - الجزء {p} | {surah_name_en} Part {p} | Beautiful Quran Recitation",
                        "surah_start": surah_num,
                        "surah_end": surah_num,
                        "ayah_start": start_a,
                        "ayah_end": end_a,
                        "estimated_duration": part_duration,
                    })
            else:
                compilations.append({
                    "title": f"سورة {surah_name_ar} كاملة | {surah_name_en} Full | Beautiful Quran Recitation",
                    "surah_start": surah_num,
                    "surah_end": surah_num,
                    "ayah_start": 1,
                    "ayah_end": verse_count,
                    "estimated_duration": est_duration,
                })
        else:
            pending_surahs.append(surah_num)
            pending_duration += est_duration
            
            if pending_duration >= LONGFORM_MIN_DURATION:
                finalize_pending()
                
    # Finalize any remaining at the end
    finalize_pending()
    
    return compilations


def get_already_compiled() -> set:
    """
    Get the set of (surah_start, surah_end, ayah_start, ayah_end) tuples 
    that have already been compiled successfully.
    """
    session = get_db_session()
    try:
        records = session.query(LongformHistory).filter(
            LongformHistory.status.in_(["compiled", "uploaded"])
        ).all()
        return {(r.surah_start, r.surah_end, r.ayah_start, r.ayah_end) for r in records}
    finally:
        session.close()


def get_next_compilation(avg_ayah_duration: float = 20.0) -> Optional[Dict[str, Any]]:
    """
    Get the next compilation group that hasn't been compiled yet.
    
    Returns:
        Compilation group dict, or None if everything has been compiled.
    """
    groups = create_compilation_groups_from_scratch(avg_ayah_duration)
    already_done = get_already_compiled()
    
    for group in groups:
        key = (
            group["surah_start"],
            group["surah_end"],
            group.get("ayah_start"),
            group.get("ayah_end")
        )
        if key not in already_done:
            logger.info(
                f"Next compilation: {group['title']} "
                f"(~{group['estimated_duration']/60:.1f} min)"
            )
            return group
            
    logger.info("All available compilations have been completed!")
    return None


def record_compilation(
    title: str,
    surah_start: int,
    surah_end: int,
    num_clips: int,
    source_clip_ids: List[str],
    duration_seconds: int,
    video_path: str,
    background_video_id: Optional[str] = None,
    ayah_start: Optional[int] = None,
    ayah_end: Optional[int] = None,
) -> int:
    """Record a completed compilation in the database."""
    session = get_db_session()
    try:
        record = LongformHistory(
            title=title,
            surah_start=surah_start,
            surah_end=surah_end,
            ayah_start=ayah_start,
            ayah_end=ayah_end,
            num_clips=num_clips,
            source_clip_ids=json.dumps(source_clip_ids),
            duration_seconds=duration_seconds,
            video_path=video_path,
            background_video_id=background_video_id,
            status="compiled",
        )
        session.add(record)
        session.commit()
        logger.info(f"Recorded compilation #{record.id}: {title}")
        return record.id
    finally:
        session.close()


def update_compilation_youtube(history_id: int, youtube_id: str) -> None:
    """Update a compilation record with YouTube upload info."""
    session = get_db_session()
    try:
        record = session.query(LongformHistory).filter_by(id=history_id).first()
        if record:
            record.youtube_id = youtube_id
            record.youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            record.status = "uploaded"
            record.uploaded_at = datetime.datetime.utcnow()
            session.commit()
            logger.info(f"Updated compilation #{history_id} with YouTube ID: {youtube_id}")
    finally:
        session.close()


def get_compilation_history(limit: int = 10) -> List[Dict]:
    """Get recent compilation history."""
    session = get_db_session()
    try:
        records = session.query(LongformHistory)\
            .order_by(LongformHistory.created_at.desc())\
            .limit(limit)\
            .all()
        
        return [
            {
                "id": r.id,
                "title": r.title,
                "surah_start": r.surah_start,
                "surah_end": r.surah_end,
                "ayah_start": r.ayah_start,
                "ayah_end": r.ayah_end,
                "num_clips": r.num_clips,
                "duration_seconds": r.duration_seconds,
                "duration_formatted": _format_duration(r.duration_seconds),
                "video_path": r.video_path,
                "youtube_id": r.youtube_id,
                "youtube_url": r.youtube_url,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    finally:
        session.close()


def _format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
