"""
DailyQuran Growth Engine - AI Decision Brain for automated content generation and publishing.
Implements the 6 Core Modules of the Master Blueprint.
"""
import os
import random
import datetime
import re
import math
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import pytz
from loguru import logger

from config.settings import (
    VERSE_COUNTS,
    SURAH_NAMES_AR,
    SURAH_NAMES_EN,
    RECITERS,
    DEFAULT_RECITER,
    SHORTS_RECITERS,
    LONGFORM_OUTPUT_DIR,
    VIDEOS_DIR
)
from database.models import get_db_session, ReelHistory, LongformHistory, VerseProgress
from core.ai_brain import generate_video_metadata, generate_longform_video_metadata
from longform.compiler import generate_longform
from core.video_generator import generate_reel

# ---------------------------------------------------------------------------
# Constants & Blueprint Definitions
# ---------------------------------------------------------------------------

# Module 2: Surah Priority Matrices
S_TIER_SURAHS = [2, 18, 36, 55, 67]   # Al-Baqarah, Al-Kahf, Yasin, Ar-Rahman, Al-Mulk
A_TIER_SURAHS = [19, 20, 56, 32, 44]  # Maryam, Taha, Al-Waqi'ah, As-Sajdah, Ad-Dukhan
B_TIER_SURAHS = [50, 72, 71, 73, 74]  # Qaf, Al-Jinn, Nuh, Al-Muzzammil, Al-Muddaththir

# Longform reciter weights. Shorts use the fixed publication rotation.
RECITER_WEIGHTS = {
    # format: {reciter_key: weight}
    "weekly_compilation": {
        "alafasy": 0.40,
        "sudais": 0.30,
        "maher_muaiqly": 0.30
    },
    "full_surah_long": {
        "alafasy": 0.50,
        "maher_muaiqly": 0.30,
        "sudais": 0.20
    },
    "sleep_long": {
        "alafasy": 0.40,
        "husary": 0.30,
        "maher_muaiqly": 0.30
    }
}

# Stand-in for analytics rows whose source record never captured a reciter.
UNKNOWN_RECITER_KEY = "unknown"

# Module 5: Thumbnail visual prompts mapping
THUMBNAIL_PROMPTS = {
    "Mosque Gold": "majestic mosque interior with gold outlines, arches, soft warm lighting, 16:9 landscape, cinematic nature scenery visible outside windows",
    "Kaaba Night": "holy Kaaba silhouette at night under a deep indigo starry sky with a bright crescent moon, spiritual glowing light, 16:9 landscape",
    "Open Quran": "open holy Quran book placed on a traditional wooden book stand, soft warm light focusing on the pages, peaceful mystical background, 16:9 landscape",
    "Reciter Showcase": "beautiful scenic nature horizon, mountains, sea, dawn, majestic glowing golden light rays, 16:9 landscape"
}


# ---------------------------------------------------------------------------
# Module 1 & 6: Time & Schedule Selector
# ---------------------------------------------------------------------------

def get_mecca_time() -> datetime.datetime:
    """Get the current time in Mecca (UTC+3) timezone."""
    mecca_tz = pytz.timezone("Asia/Riyadh")
    return datetime.datetime.now(mecca_tz)


def get_current_slot(mecca_time: datetime.datetime) -> Optional[str]:
    """
    Determine the current scheduled publishing slot based on Mecca time.
    Returns slot name ('morning_short', 'evening_short', 'friday_long', 'saturday_sleep')
    if within a 2-hour window, else None.
    """
    weekday = mecca_time.weekday()  # Monday=0, Friday=4, Saturday=5
    hour = mecca_time.hour
    
    # Friday spiritual peak
    if weekday == 4 and 21 <= hour < 23:
        return "friday_long"
        
    # Saturday bi-weekly sleep
    if weekday == 5 and 22 <= hour < 24:
        return "saturday_sleep"
        
    # Daily morning short (Fajr time peak)
    if 5 <= hour < 7:
        return "morning_short"
        
    # Daily evening short (Maghrib/Isha peak)
    if 21 <= hour < 23:
        return "evening_short"
        
    return None


def get_slot_format(slot: str) -> str:
    """Map a slot name to its target blueprint video format."""
    if slot == "morning_short":
        return "standard_short"
    elif slot == "evening_short":
        return "standard_short"
    elif slot == "friday_long":
        return "full_surah_long"
    elif slot == "saturday_sleep":
        return "sleep_long"
    raise ValueError(f"Unknown publishing slot: {slot}")


# ---------------------------------------------------------------------------
# Module 2 & 3: Selection Logic with Guardrails
# ---------------------------------------------------------------------------

def is_combo_repeated_recently(surah: int, reciter_key: str, days: int = 7) -> bool:
    """
    Check if the same surah and reciter combo was published in the past N days.
    """
    session = get_db_session()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    try:
        # Check Shorts
        recent_reel = session.query(ReelHistory).filter(
            ReelHistory.surah == surah,
            ReelHistory.reciter_key == reciter_key,
            ReelHistory.created_at >= cutoff
            , ReelHistory.status == "uploaded"
        ).first()
        if recent_reel:
            return True
            
        # Check Longform
        recent_long = session.query(LongformHistory).filter(
            LongformHistory.surah_start == surah,
            LongformHistory.reciter_key == reciter_key,
            LongformHistory.created_at >= cutoff
            , LongformHistory.status == "uploaded"
        ).first()
        if recent_long:
            return True
            
        return False
    finally:
        session.close()


def pick_reciter(format_type: str) -> str:
    """Shorts follow the owner-approved cycle; longform retains its selection."""
    if "short" in format_type:
        from database.jobs import get_next_shorts_selection
        return get_next_shorts_selection()['reciter_key']
    weights = RECITER_WEIGHTS.get(format_type, RECITER_WEIGHTS["full_surah_long"])
    reciters = list(weights.keys())
    probs = list(weights.values())
    return random.choices(reciters, weights=probs)[0]


def pick_surah(format_type: str, reciter_key: str) -> int:
    """
    Select an appropriate Surah based on priority tier, format,
    weekly repetition guardrails, and performance-based downweights.
    """
    from database.models import get_setting
    import json
    
    # Legacy optimization weights were derived from unverified/default metrics.
    downweights = {}

    if "short" in format_type:
        from database.jobs import get_next_shorts_selection
        return get_next_shorts_selection()['surah']
            
    # For long-forms, select from S-Tier or A-Tier
    tiers = S_TIER_SURAHS + A_TIER_SURAHS
    random.shuffle(tiers)
    
    candidates = []
    for surah in tiers:
        if not is_combo_repeated_recently(surah, reciter_key, days=7):
            w = downweights.get(f"{surah}:{reciter_key}", 1.0)
            candidates.append((surah, w))
            
    if candidates:
        surahs = [c[0] for c in candidates]
        weights = [c[1] for c in candidates]
        return random.choices(surahs, weights=weights)[0]
            
    # Absolute fallback
    return random.choice(S_TIER_SURAHS)


# ---------------------------------------------------------------------------
# Module 4: Title Generator & vidIQ Keyword Scorer
# ---------------------------------------------------------------------------

def score_title_vidiq(title: str) -> int:
    """
    Simulate vidIQ SEO optimization scoring (0-100).
    Scores based on length limits and key high-CTR keywords.
    """
    score = 50
    # Length check (Optimal is 45-75 chars)
    title_len = len(title)
    if 45 <= title_len <= 75:
        score += 20
    elif title_len > 90:
        score -= 15
        
    # High volume keyword boosts
    keywords = [
        "Beautiful Quran Recitation", "Quran Recitation", "Surah", "Full", 
        "Beautiful", "Sleep", "Heart Soothing", "Mishary", "Alafasy", "Sudais"
    ]
    for kw in keywords:
        if kw.lower() in title.lower():
            score += 5
            
    # Emojis boost CTR
    if any(char in title for char in ["🕊️", "✨", "🤍", "🌙", "💫", "⭐"]):
        score += 10
        
    return min(score, 100)


def generate_engine_title(
    mode: str, 
    surah: int, 
    reciter_key: str, 
    surah_end: Optional[int] = None,
    *, coverage_complete: bool = False,
    start_ayah: Optional[int] = None,
    end_ayah: Optional[int] = None,
) -> str:
    """
    Generate video title matching the 4-mode blueprint template.
    Uses verified coverage. The local keyword score is advisory, not vidIQ data.
    """
    name_ar = SURAH_NAMES_AR[surah - 1]
    name_en = SURAH_NAMES_EN[surah - 1]
    
    reciter_info = RECITERS.get(reciter_key, {})
    rec_ar = reciter_info.get("name_ar", reciter_key).replace("الشيخ ", "")
    rec_en = reciter_info.get("name_en", reciter_key)
    
    title = ""
    for attempt in range(5):
        if mode == "arabic_short_core":
            title = f"سورة {name_ar} - {rec_ar} | تلاوة خاشعة 🤍"
        elif mode == "arabic_short_gulf":
            title = f"سورة {name_ar} - {rec_ar} | تلاوة هادئة للنوم 🌙"
        elif mode == "bilingual_long":
            end_label = f" to {SURAH_NAMES_EN[surah_end-1]}" if surah_end and surah_end != surah else ""
            full_label = " كاملة" if coverage_complete else ""
            title = f"سورة {name_ar}{full_label} | Surah {name_en}{end_label} - Quran Recitation"
        elif mode == "english_seo_long":
            end_label = f" to {SURAH_NAMES_EN[surah_end-1]}" if surah_end and surah_end != surah else ""
            full_label = " Full" if coverage_complete else ""
            title = f"Surah {name_en}{end_label}{full_label} - {rec_en} | Quran Recitation"
        else:
            title = f"Surah {name_en} - {rec_en} | Beautiful Recitation 🤍"

        # Force check length limit
        if len(title) > 100:
            title = title[:97] + "..."
            
        score = score_title_vidiq(title)
        if score >= 80:
            logger.info(f"Generated title passes vidIQ filter: '{title}' (Score: {score}/100)")
            return title
            
    # Final robust fallback
    full_label = " Full" if coverage_complete else ""
    verse_label = f" {start_ayah}-{end_ayah}" if start_ayah is not None and end_ayah is not None else ""
    return f"Surah {name_en}{full_label}{verse_label} - {rec_en} | Quran Recitation"[:100]


# ---------------------------------------------------------------------------
# Module 5: Thumbnail Customizer
# ---------------------------------------------------------------------------

def get_thumbnail_template_for_format(format_type: str, *, persist: bool = True, read_history: bool = True) -> str:
    """
    Determine the thumbnail template, enforcing the blueprint guardrail:
    - Rotate templates evenly.
    - Never publish 2 of the same template consecutively.
    """
    from database.models import get_setting, set_setting
    
    # Check if format has a hard template requirement
    hard_template = None
    if format_type == "sleep_long":
        hard_template = "Kaaba Night"
    elif format_type == "full_surah_long":
        hard_template = "Open Quran"
    elif format_type == "weekly_compilation":
        hard_template = "Mosque Gold"
        
    last_template = get_setting("last_thumbnail_template", "") if read_history else ""
    templates = ["Reciter Showcase", "Mosque Gold", "Open Quran", "Kaaba Night"]
    
    if hard_template:
        selected = hard_template
        if selected == last_template:
            logger.warning(f"Consecutive thumbnail template conflict: hard requirement '{selected}' matches last template. Proceeding due to content constraints.")
    else:
        # For Shorts / fallback formats, rotate to the next template in the list
        if last_template in templates:
            last_idx = templates.index(last_template)
            next_idx = (last_idx + 1) % len(templates)
            selected = templates[next_idx]
        else:
            selected = random.choice(templates)
            
    # Persist choice for the next execution
    if persist:
        set_setting("last_thumbnail_template", selected)
    return selected


# ---------------------------------------------------------------------------
# Suppression Guardrail (Module 6)
# ---------------------------------------------------------------------------

def is_publishing_suppressed() -> bool:
    """Honor the explicit operator suppression switch."""
    suppress = os.getenv("SUPPRESS_DURING_RAMADAN_LAST_10", "false").lower() == "true"
    if suppress:
        logger.warning("Publishing suppression is enabled by configuration")
        return True
    return False


# ---------------------------------------------------------------------------
# Orchestrated Execution Engine
# ---------------------------------------------------------------------------

def execute_scheduled_slot(slot_name: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Select a slot without side effects in dry-run; serialize actual publication."""
    if is_publishing_suppressed() and not dry_run:
        return {"status": "suppressed", "message": "Publishing suppression is enabled."}
    if not dry_run:
        from youtube.auth import check_authentication_status
        status = check_authentication_status()
        if status["status"] == "not_authenticated":
            return {"status": "failed", "error": "YouTube not authenticated: " + status.get("message", "")}
    now = get_mecca_time()
    slot_name = slot_name or get_current_slot(now)
    if not slot_name:
        return {"status": "skipped", "message": "No active publishing window."}
    if slot_name not in {"morning_short", "evening_short", "friday_long", "saturday_sleep"}:
        return {"status": "failed", "error": "Unknown publishing slot."}
    if slot_name == "saturday_sleep":
        return {"status": "skipped", "message": "Sleep format is unavailable until a reviewed complete format is implemented."}
    format_type = get_slot_format(slot_name)
    if dry_run:
        # No settings reads: even opening a store can initialize it on a fresh checkout.
        surah, reciter = 1, SHORTS_RECITERS[0] if "short" in format_type else DEFAULT_RECITER
        template = get_thumbnail_template_for_format(format_type, persist=False, read_history=False)
        return {"status": "dry_run", "slot": slot_name, "format": format_type,
                "surah": surah, "reciter": reciter,
                "title": generate_engine_title("arabic_short_core", surah, reciter),
                "thumbnail_template": template, "bg_prompt": THUMBNAIL_PROMPTS[template],
                "message": "Illustrative plan only; persisted selection is evaluated during an actual job."}
    from core.runtime_safety import exclusive_lock, LockTimeoutError
    from config.settings import DATABASE_PATH
    try:
        with exclusive_lock(DATABASE_PATH.parent / "publishing.lock", timeout=0):
            return _execute_selected_slot(slot_name, format_type, now)
    except LockTimeoutError:
        return {"status": "skipped", "message": "Another publishing job is active."}
    except Exception as exc:
        logger.error("Growth job failed ({})", type(exc).__name__)
        return {"status": "failed", "error": str(exc)}


def _execute_selected_slot(slot_name, format_type, now):
    from database.models import get_setting, set_setting
    from database.jobs import reserve_job, mark_job, finalize_published_job, get_next_shorts_selection
    from notifications.publishing_policy import require_automatic_approval
    from youtube.uploader import upload_video, upload_thumbnail
    from core.utils import load_media_manifest, require_manifest_coverage
    import json

    # Fail before expensive rendering if review/account policy is not configured.
    required = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_APPROVER_ID", "YOUTUBE_EXPECTED_CHANNEL_ID")
    if any(not os.getenv(key, "").strip() for key in required):
        return {"status": "failed", "error": "Automatic publication requires reviewer and expected account configuration."}
    from database.models import init_database
    init_database()
    rotation = "short" in format_type
    if rotation:
        selection = get_next_shorts_selection()
        surah, start_ayah, end_ayah, reciter = (selection[key] for key in
                                              ('surah','start_ayah','end_ayah','reciter_key'))
    else:
        reciter = pick_reciter(format_type)
        surah = pick_surah(format_type, reciter)
        start_ayah, end_ayah = 1, VERSE_COUNTS[surah]
    job = reserve_job(f"growth:{now.date().isoformat()}:{slot_name}", surah=surah,
                      start_ayah=start_ayah, end_ayah=end_ayah, reciter_key=reciter,
                      shorts_rotation=rotation, cycle=selection['cycle'] if rotation else None,
                      surah_end=surah if "short" not in format_type else None)
    if job.get("finalized") or job.get("status") not in {"reserved", "pending"}:
        return {"status": "skipped", "message": "This occurrence already has a job; reconcile it before retrying.", "job_id": job["id"]}
    # The persisted reservation owns the content, including after interruption.
    surah, start_ayah, end_ayah, reciter = job["surah"], job["start_ayah"], job["end_ayah"], job["reciter_key"]
    if rotation:
        from core.shorts_policy import require_shorts_reciter
        require_shorts_reciter(reciter)
    completed_receipt = None
    try:
        template = get_thumbnail_template_for_format(format_type, persist=False)
        thumbnail = None
        if "short" in format_type:
            video_path, actual_start, actual_end = generate_reel(surah=surah, start_ayah=start_ayah,
                                                               end_ayah=end_ayah, reciter_key=reciter)
            if actual_start != start_ayah:
                raise ValueError("Generated Shorts must begin at the reserved verse")
            title = generate_engine_title("arabic_short_core", surah, reciter,
                                          start_ayah=actual_start, end_ayah=actual_end)
            metadata = {"title": title,
                        "description": f"Surah {SURAH_NAMES_EN[surah-1]}, verses {actual_start}-{actual_end}. "
                                       f"Reciter: {RECITERS[reciter]['name_en']}.\n#Quran #Shorts",
                        "tags": ["Quran", "Shorts", SURAH_NAMES_EN[surah-1], RECITERS[reciter]["name_en"]]}
            history = dict(surah=surah, start_ayah=actual_start, end_ayah=actual_end,
                           reciter_key=reciter, video_path=str(video_path))
        else:
            compiled = generate_longform(surah_start=surah, surah_end=surah, reciter_key=reciter,
                                         loop_count=1, thumbnail_template=template,
                                         custom_bg_prompt=THUMBNAIL_PROMPTS[template])
            video_path = Path(compiled["output_path"])
            actual_start, actual_end = 1, VERSE_COUNTS[surah]
            title = compiled.get("recommended_title") or compiled.get("title")
            if not title:
                raise ValueError("Verified longform metadata has no title")
            metadata = {"title": title, "description": compiled["description"], "tags": compiled["tags"]}
            thumbnail = compiled.get("thumbnail_path")
            history = dict(kind="longform", title=title, surah_start=surah, surah_end=surah,
                           ayah_start=actual_start, ayah_end=actual_end, reciter_key=reciter,
                           num_clips=VERSE_COUNTS[surah], source_clip_ids=[],
                           duration_seconds=compiled["duration_seconds"], video_path=str(video_path))
        manifest = load_media_manifest(video_path)
        if manifest.get("coverage_complete") is not True:
            raise ValueError("Verified complete media coverage is required before publication")
        require_manifest_coverage(manifest, surah_start=surah, start_ayah=actual_start,
                                  surah_end=surah, end_ayah=actual_end, reciter_key=reciter)
        mark_job(job["id"], "generated", video_path=str(video_path), start_ayah=actual_start, end_ayah=actual_end,
                 manifest=manifest, metadata_json=json.dumps(metadata, ensure_ascii=False))
        approval = require_automatic_approval(video_path, metadata, job_id=job["id"],
                                              manifest=manifest, privacy_status="public", thumbnail_path=thumbnail)
        receipt = upload_video(video_path, metadata, privacy_status="public", automatic=True,
                               job_id=job["id"], approval=approval, thumbnail_path=thumbnail)
        if receipt.get("status") != "published":
            raise ValueError("Upload is not confirmed published; reconcile the saved receipt")
        finalize_published_job(job["id"], history, receipt)
        completed_receipt = receipt
        set_setting("last_thumbnail_template", template)
        # Custom thumbnail publication uses the exact reviewed bytes.
        if thumbnail and approval.get("thumbnail_sha256") and Path(thumbnail).is_file():
            from core.asset_provenance import checksum
            if checksum(thumbnail) != approval["thumbnail_sha256"]:
                raise ValueError("Thumbnail changed after review")
            upload_thumbnail(receipt["video_id"], Path(thumbnail), automatic=True, approval=approval)
        # Cross-posting needs a separately approved account/privacy/package.
        if os.getenv("ENABLE_TIKTOK_AUTOPUBLISH", "false").lower() == "true" and "short" in format_type:
            from tiktok.uploader import generate_tiktok_metadata, upload_to_tiktok
            caption = generate_tiktok_metadata(SURAH_NAMES_AR[surah-1], SURAH_NAMES_EN[surah-1],
                                               surah, actual_start, actual_end, RECITERS[reciter]["name_ar"])
            caption.update(title=metadata["title"], description=caption["caption"], tags=[])
            tt_approval = require_automatic_approval(video_path, caption, job_id=job["id"],
                                                     platform="tiktok", manifest=manifest, privacy_status="PUBLIC_TO_EVERYONE")
            tt_result = upload_to_tiktok(video_path, caption, automatic=True, job_id=job["id"],
                                        approval=tt_approval, privacy_status="PUBLIC_TO_EVERYONE")
            if tt_result.get("status") not in {"published", "processed"}:
                return {"status": "partial", "video_id": receipt["video_id"], "error": "TikTok is not confirmed complete; reconcile receipt."}
        return {"status": "success", "url": receipt["url"], "video_id": receipt["video_id"], "title": title}
    except Exception as exc:
        if completed_receipt is not None:
            mark_job(job["id"], "published", error_message="Post-publication step failed: " + str(exc))
            return {"status": "partial", "video_id": completed_receipt["video_id"],
                    "url": completed_receipt["url"], "error": str(exc),
                    "message": "YouTube publication is complete; reconcile the remaining step without reposting."}
        mark_job(job["id"], "failed", error_message=str(exc))
        raise


# ---------------------------------------------------------------------------
# Performance Feedback Loop & self-optimization (Module 7/Analytics)
# ---------------------------------------------------------------------------

def ingest_video_analytics(
    video_id: str,
    views: int,
    likes: int,
    comments: int,
    retention_rate: float,
    ctr: float,
    surah: int,
    reciter_key: str,
    video_type: str,
    *, metrics_source: str = "manual", private_metrics_verified: bool = False,
) -> Dict[str, Any]:
    """
    Ingest performance metrics for an uploaded video into the analytics database.
    """
    from database.models import get_db_session, VideoAnalytics

    if not video_id or not isinstance(video_id, str) or len(video_id) > 50:
        raise ValueError("A valid video ID is required")
    for name, value in [("views", views), ("likes", likes), ("comments", comments)]:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    for name, value in [("retention_rate", retention_rate), ("ctr", ctr)]:
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError(f"{name} must be unknown or a finite rate between zero and one")
    if surah not in VERSE_COUNTS or video_type not in {"short", "long"}:
        raise ValueError("Invalid content identity")

    # LongformHistory.reciter_key is nullable but VideoAnalytics.reciter_key is
    # not, so an older compilation with no reciter recorded would otherwise
    # raise IntegrityError and take the rest of its batch down with it.
    if not (reciter_key or "").strip():
        reciter_key = UNKNOWN_RECITER_KEY

    session = get_db_session()
    try:
        # Check if record already exists
        record = session.query(VideoAnalytics).filter_by(video_id=video_id).first()
        engagement_rate = ((likes + comments) / views) if views > 0 else 0.0
        
        if record:
            record.views = views
            record.likes = likes
            record.comments = comments
            record.retention_rate = retention_rate
            record.ctr = ctr
            record.engagement_rate = engagement_rate
            record.metrics_source = metrics_source
            record.observed_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            record.private_metrics_verified = private_metrics_verified
        else:
            record = VideoAnalytics(
                video_id=video_id,
                views=views,
                likes=likes,
                comments=comments,
                retention_rate=retention_rate,
                ctr=ctr,
                engagement_rate=engagement_rate,
                surah=surah,
                reciter_key=reciter_key,
                video_type=video_type,
                metrics_source=metrics_source,
                observed_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                private_metrics_verified=private_metrics_verified,
            )
            session.add(record)
        session.commit()
        logger.info(f"Ingested metrics for video {video_id}: views={views}, engagement={engagement_rate:.1%}")
        return {
            "status": "success",
            "video_id": video_id,
            "views": views,
            "engagement_rate": engagement_rate
        }
    finally:
        session.close()


def run_feedback_loop_analysis() -> Dict[str, Any]:
    """Read-only review signals. Uncalibrated metrics never change publishing decisions."""
    from database.models import get_db_session, VideoAnalytics
    session = get_db_session()
    try:
        rows = session.query(VideoAnalytics).order_by(VideoAnalytics.created_at.desc()).limit(50).all()
        if not rows:
            return {"status": "no_data", "actions_applied": [], "warnings_triggered": []}
        signals = []
        for row in rows:
            if row.views < 1000:
                continue
            signals.append({"video_id": row.video_id, "views": row.views,
                            "likes_comments_per_view": row.engagement_rate,
                            "retention": row.retention_rate if getattr(row, "private_metrics_verified", False) is True else None,
                            "ctr": row.ctr if getattr(row, "private_metrics_verified", False) is True else None})
        return {"status": "success", "mode": "advisory", "actions_applied": [],
                "warnings_triggered": [], "signals": signals,
                "message": "No automatic weight changes; age/exposure and measured private metrics require review."}
    finally:
        session.close()


def trigger_ab_test_experiment(variable_type: str) -> Dict[str, Any]:
    if variable_type not in {"reciter", "ayah_length", "thumbnail_style"}:
        raise ValueError("Invalid experiment variable")
    return {"status": "unavailable", "message": "Experiments require reviewed real variants and matched exposure; no synthetic IDs are created."}


def evaluate_active_ab_tests() -> List[Dict[str, Any]]:
    logger.warning("Automatic experiment promotion is unavailable pending real variant/exposure contracts.")
    return []


def auto_ingest_youtube_public_metrics() -> Dict[str, Any]:
    """
    Query the YouTube Data API for public metrics (views, likes, comments)
    of all uploaded videos in our history, and ingest them.
    """
    from database.models import get_db_session, ReelHistory, LongformHistory
    from youtube.auth import get_authenticated_service
    
    session = get_db_session()
    ingested_count = 0
    errors = []
    
    try:
        # Get recently uploaded Shorts
        reels = session.query(ReelHistory).filter(
            ReelHistory.youtube_id.isnot(None),
            ReelHistory.status == "uploaded"
        ).all()
        
        longforms = session.query(LongformHistory).filter(
            LongformHistory.youtube_id.isnot(None),
            LongformHistory.status == "uploaded"
        ).all()
        
        # Build map of id -> metadata
        video_map = {}
        for r in reels:
            video_map[r.youtube_id] = {
                "surah": r.surah,
                "reciter_key": r.reciter_key,
                "video_type": "short"
            }
        for l in longforms:
            video_map[l.youtube_id] = {
                "surah": l.surah_start,
                "reciter_key": l.reciter_key,
                "video_type": "long"
            }
            
        video_ids = list(video_map.keys())
        if not video_ids:
            return {"status": "no_videos", "message": "No uploaded videos found in history."}
            
        try:
            service = get_authenticated_service(interactive=False)
        except Exception as e:
            logger.error(f"Failed to authenticate YouTube service for stats: {e}")
            return {"status": "auth_error", "message": str(e)}
            
        # Chunk requests up to 50 video IDs
        chunk_size = 50
        for i in range(0, len(video_ids), chunk_size):
            chunk = video_ids[i:i + chunk_size]
            logger.info(f"Querying statistics for {len(chunk)} videos from YouTube API...")
            
            try:
                request = service.videos().list(
                    part="statistics",
                    id=",".join(chunk)
                )
                response = request.execute()
                
                for item in response.get("items", []):
                    vid_id = item["id"]
                    stats = item.get("statistics", {})
                    
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    
                    meta = video_map[vid_id]
                    
                    # Preserve private retention / CTR from database if they already exist
                    from database.models import VideoAnalytics
                    existing_analytics = session.query(VideoAnalytics).filter_by(video_id=vid_id).first()
                    private_verified = bool(existing_analytics and existing_analytics.private_metrics_verified)
                    retention = existing_analytics.retention_rate if private_verified else None
                    ctr = existing_analytics.ctr if private_verified else None
                    
                    # Per-video, so one unusable row cannot discard the
                    # statistics for the other 49 videos in this chunk.
                    try:
                        result = ingest_video_analytics(
                            video_id=vid_id,
                            views=views,
                            likes=likes,
                            comments=comments,
                            retention_rate=retention,
                            ctr=ctr,
                            surah=meta["surah"],
                            reciter_key=meta["reciter_key"],
                            video_type=meta["video_type"],
                            metrics_source="youtube_public", private_metrics_verified=private_verified,
                        )
                        if result.get("status") == "success":
                            ingested_count += 1
                        else:
                            errors.append(f"{vid_id}: ingestion did not succeed")
                    except Exception as e:
                        logger.error(f"Could not ingest metrics for {vid_id}: {e}")
                        errors.append(f"{vid_id}: {e}")
            except Exception as e:
                logger.error(f"Error querying statistics for chunk: {e}")
                errors.append(str(e))
                
        return {
            "status": "partial" if errors and ingested_count else "failed" if errors else "success",
            "ingested_count": ingested_count,
            "errors": errors
        }
    finally:
        session.close()


