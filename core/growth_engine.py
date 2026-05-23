"""
DailyQuran Growth Engine - AI Decision Brain for automated content generation and publishing.
Implements the 6 Core Modules of the Master Blueprint.
"""
import os
import random
import datetime
import re
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

# Module 3: Reciter Matrix
RECITER_WEIGHTS = {
    # format: {reciter_key: weight}
    "standard_short": {
        "alafasy": 0.20,
        "maher_muaiqly": 0.20,
        "sudais": 0.15,
        "shaatree": 0.15,
        "husary": 0.15,
        "abdul_basit_murattal": 0.15
    },
    "gulf_short": {
        "maher_muaiqly": 0.50,
        "sudais": 0.30,
        "alafasy": 0.20
    },
    "english_short": {
        "shaatree": 0.40,
        "alafasy": 0.40,
        "maher_muaiqly": 0.20
    },
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
    if weekday == 4 and 20 <= hour <= 23:
        return "friday_long"
        
    # Saturday bi-weekly sleep
    if weekday == 5 and 21 <= hour <= 23:
        return "saturday_sleep"
        
    # Daily morning short (Fajr time peak)
    if 4 <= hour <= 7:
        return "morning_short"
        
    # Daily evening short (Maghrib/Isha peak)
    if 19 <= hour <= 22:
        return "evening_short"
        
    return None


def get_slot_format(slot: str) -> str:
    """Map a slot name to its target blueprint video format."""
    if slot == "morning_short":
        return "standard_short"
    elif slot == "evening_short":
        # Randomly choose between Gulf Bait, English tagged, or standard
        return random.choices(
            ["standard_short", "gulf_short", "english_short"], 
            weights=[0.50, 0.30, 0.20]
        )[0]
    elif slot == "friday_long":
        # Alternates weekly between compilation and full surah
        return random.choice(["weekly_compilation", "full_surah_long"])
    elif slot == "saturday_sleep":
        return "sleep_long"
    return "standard_short"


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
        ).first()
        if recent_reel:
            return True
            
        # Check Longform
        recent_long = session.query(LongformHistory).filter(
            LongformHistory.surah_start == surah,
            LongformHistory.reciter_key == reciter_key,
            LongformHistory.created_at >= cutoff
        ).first()
        if recent_long:
            return True
            
        return False
    finally:
        session.close()


def pick_reciter(format_type: str) -> str:
    """Select a reciter key based on format CPM weights."""
    weights = RECITER_WEIGHTS.get(format_type, RECITER_WEIGHTS["standard_short"])
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
    
    downweights = {}
    try:
        downweights = json.loads(get_setting("growth_engine_downweights", "{}"))
    except Exception:
        pass

    if "short" in format_type:
        # Volume play: proceed sequentially through current progress
        session = get_db_session()
        try:
            progress = session.query(VerseProgress).first()
            if progress:
                surah = progress.current_surah
                # Ensure guardrail check
                key = f"{surah}:{reciter_key}"
                is_repeated = is_combo_repeated_recently(surah, reciter_key, days=7)
                is_downweighted = downweights.get(key, 1.0) < 0.5
                
                if is_repeated or is_downweighted:
                    # Pick a random short surah from last 20 surahs to avoid duplicate/underperformer
                    surah = random.randint(100, 114)
                return surah
            return random.randint(90, 114)
        finally:
            session.close()
            
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
    surah_end: Optional[int] = None
) -> str:
    """
    Generate video title matching the 4-mode blueprint template.
    Guarantees a vidIQ-equivalent score >= 80/100.
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
            end_label = f" to {SURAH_NAMES_EN[surah_end-1]}" if surah_end and surah_end != surah else " Full"
            title = f"سورة {name_ar} كاملة | Surah {name_en}{end_label} - Beautiful Recitation 🕊️"
        elif mode == "english_seo_long":
            end_label = f" to {SURAH_NAMES_EN[surah_end-1]}" if surah_end and surah_end != surah else " Full"
            title = f"Surah {name_en}{end_label} - {rec_en} | Beautiful Quran Recitation for Sleep 🌙"
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
    return f"Surah {name_en} Full - {rec_en} | Beautiful Quran Recitation 🕊️"


# ---------------------------------------------------------------------------
# Module 5: Thumbnail Customizer
# ---------------------------------------------------------------------------

def get_thumbnail_template_for_format(format_type: str) -> str:
    """Map the video format to the correct blueprint thumbnail template."""
    if format_type == "sleep_long":
        return "Kaaba Night"
    elif format_type == "full_surah_long":
        return "Open Quran"
    elif format_type == "weekly_compilation":
        return "Mosque Gold"
    return "Reciter Showcase"


# ---------------------------------------------------------------------------
# Suppression Guardrail (Module 6)
# ---------------------------------------------------------------------------

def is_publishing_suppressed() -> bool:
    """
    Smart trigger: Auto-suppress or delay scheduling during high-velocity periods
    such as the last 10 days of Ramadan to avoid algorithm saturation.
    """
    # For simulation, can be controlled via environment variable or calendar check
    suppress = os.getenv("SUPPRESS_DURING_RAMADAN_LAST_10", "false").lower() == "true"
    if suppress:
        # Checks if current date is during last 10 days of Ramadan
        # (Ramadan dates shift yearly, would check Islamic calendar API/library in production)
        logger.warning("Auto-suppression active (Ramadan Peak Period). High competition detected.")
        return True
    return False


# ---------------------------------------------------------------------------
# Orchestrated Execution Engine
# ---------------------------------------------------------------------------

def execute_scheduled_slot(slot_name: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """
    Orchestrate the entire DailyQuran Growth Engine slot run.
    1. Check timezone and slot.
    2. Select format, surah, and reciter.
    3. Generate video (Short or Longform).
    4. Generate scored titles and optimized thumbnails.
    5. Post to YouTube channel.
    """
    logger.info("🎬 Initializing DailyQuran Growth Engine Orchestration...")
    
    # Check suppression guardrail
    if is_publishing_suppressed() and not dry_run:
        logger.info("Publishing is suppressed. Skipping compilation/posting.")
        return {"status": "suppressed", "message": "High-velocity period suppression active."}
        
    mecca_time = get_mecca_time()
    logger.info(f"Mecca Time (UTC+3): {mecca_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Determine slot
    if not slot_name:
        slot_name = get_current_slot(mecca_time)
        if not slot_name:
            logger.info("No active Mecca timezone slot detected. Defaulting to 'evening_short' template.")
            slot_name = "evening_short"
            
    format_type = get_slot_format(slot_name)
    logger.info(f"Slot Selected: '{slot_name}' -> Format: '{format_type}'")
    
    # 2. Select Reciter & Surah (checking for queued outperforming combos from the feedback loop first)
    from database.models import get_setting, set_setting
    import json
    
    forced_combo_used = False
    reciter_key = None
    surah = None
    
    if "short" in format_type:
        forced_combos_str = get_setting("growth_engine_forced_combos", "[]")
        try:
            forced_combos = json.loads(forced_combos_str)
            if forced_combos:
                next_combo = forced_combos.pop(0)
                surah = next_combo["surah"]
                reciter_key = next_combo["reciter_key"]
                set_setting("growth_engine_forced_combos", json.dumps(forced_combos))
                forced_combo_used = True
                logger.info(f"🚀 Outperforming combo detected from feedback loop! Duplicating Surah {surah} + Reciter {reciter_key} for views optimization.")
        except Exception as e:
            logger.warning(f"Failed to process forced combos: {e}")
            
    if not forced_combo_used:
        reciter_key = pick_reciter(format_type)
        surah = pick_surah(format_type, reciter_key)
        
    logger.info(f"AI Decision: Surah {surah} ({SURAH_NAMES_EN[surah-1]}), Reciter: {reciter_key}")
    
    # 3. Handle Generation & Metadata
    title_mode = "arabic_short_core"
    if "long" in format_type or "compilation" in format_type:
        title_mode = "english_seo_long" if format_type == "sleep_long" else "bilingual_long"
    elif format_type == "gulf_short":
        title_mode = "arabic_short_gulf"
        
    title = generate_engine_title(title_mode, surah, reciter_key)
    thumb_template = get_thumbnail_template_for_format(format_type)
    bg_visual_prompt = THUMBNAIL_PROMPTS[thumb_template]
    
    logger.info(f"Metadata Mode: '{title_mode}' | Scored Title: '{title}'")
    logger.info(f"Thumbnail Layout: '{thumb_template}' | Background Prompt: '{bg_visual_prompt}'")
    
    if dry_run:
        logger.success("🎯 DRY RUN SUCCESSFUL. Complete growth engine decision matrix generated.")
        return {
            "status": "dry_run",
            "slot": slot_name,
            "format": format_type,
            "surah": surah,
            "reciter": reciter_key,
            "title": title,
            "thumbnail_template": thumb_template,
            "bg_prompt": bg_visual_prompt
        }
        
    # Execute actual build & upload
    try:
        from youtube.uploader import upload_video, upload_thumbnail
        from core.verse_scheduler import advance_progress, record_reel_history
        from longform.scheduler import record_compilation, update_compilation_youtube
        
        video_path = None
        thumbnail_path = None
        metadata = {}
        
        if "short" in format_type:
            # Generate Shorts
            logger.info("Executing Short generation pipeline...")
            start_ayah = 1
            # Retrieve current progress ayah
            session = get_db_session()
            try:
                progress = session.query(VerseProgress).first()
                if progress and progress.current_surah == surah:
                    start_ayah = progress.current_ayah
            finally:
                session.close()
                
            # Render Short (e.g. 3 verses)
            end_ayah = min(start_ayah + 2, VERSE_COUNTS[surah])
            
            logger.info(f"Rendering Short: Surah {surah} Ayahs {start_ayah}-{end_ayah}...")
            video_path, act_start, act_end = generate_reel(
                surah=surah,
                start_ayah=start_ayah,
                end_ayah=end_ayah,
                reciter_key=reciter_key
            )
            
            # Form metadata description
            description = (
                f"Beautiful Quran recitation of Surah {SURAH_NAMES_EN[surah-1]} "
                f"verses {act_start}-{act_end}. Recited by {RECITERS[reciter_key]['name_en']}.\n\n"
                f"#Quran #Shorts #DailyQuran"
            )
            metadata = {
                "recommended_title": title,
                "description": description,
                "tags": ["Quran", "Shorts", SURAH_NAMES_EN[surah-1], RECITERS[reciter_key]["name_en"]]
            }
            
            # Post Video
            logger.info("Posting Short to YouTube...")
            upload_result = upload_video(
                video_path,
                {
                    "title": title,
                    "description": description,
                    "tags": metadata["tags"]
                },
                privacy_status="public"
            )
            
            # Record in progress database
            record_reel_history(
                surah=surah,
                start_ayah=act_start,
                end_ayah=act_end,
                reciter_key=reciter_key,
                video_path=str(video_path),
                youtube_id=upload_result["video_id"]
            )
            advance_progress(surah, act_end)
            
        else:
            # Generate Longform (compilation, full surah, or sleep video)
            logger.info("Executing Long-form compilation pipeline...")
            # For testing compile a single Surah or smaller loop to keep rendering reasonable
            # Compile Al-Kawthar (Surah 108) as a test if it's full surah, otherwise standard compile
            comp_surah = surah
            logger.info(f"Compiling long-form for Surah {comp_surah}...")
            
            # Call generate_longform which automatically creates video + scored title + thumbnail
            metadata = generate_longform(
                surah_start=comp_surah,
                surah_end=comp_surah,
                reciter_key=reciter_key,
                loop_count=1,
                thumbnail_template=thumb_template,
                custom_bg_prompt=bg_visual_prompt
            )
            
            video_path = Path(metadata["output_path"])
            thumbnail_path_str = metadata.get("thumbnail_path")
            
            # Post Video
            logger.info("Posting Long-form to YouTube...")
            upload_result = upload_video(
                video_path,
                {
                    "title": title, # Use vidIQ scored title
                    "description": metadata["description"],
                    "tags": metadata["tags"]
                },
                privacy_status="public"
            )
            
            # Set Custom Thumbnail
            if thumbnail_path_str:
                thumbnail_path = Path(thumbnail_path_str)
                if thumbnail_path.exists():
                    upload_thumbnail(upload_result["video_id"], thumbnail_path)
            
            # Record compilation
            history_id = record_compilation(
                title=title,
                surah_start=comp_surah,
                surah_end=comp_surah,
                num_clips=VERSE_COUNTS[comp_surah],
                source_clip_ids=[],
                duration_seconds=metadata["duration_seconds"],
                video_path=str(video_path),
                ayah_start=1,
                ayah_end=VERSE_COUNTS[comp_surah],
                reciter_key=reciter_key
            )
            update_compilation_youtube(history_id, upload_result["video_id"])
            
        logger.success(f"🎉 Slot execution complete! Posted successfully: {upload_result['url']}")
        return {
            "status": "success",
            "url": upload_result["url"],
            "video_id": upload_result["video_id"],
            "title": title
        }
        
    except Exception as e:
        logger.exception(f"Failed executing growth engine slot: {e}")
        return {"status": "failed", "error": str(e)}


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
    video_type: str
) -> Dict[str, Any]:
    """
    Ingest performance metrics for an uploaded video into the analytics database.
    """
    from database.models import get_db_session, VideoAnalytics
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
                video_type=video_type
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
    """
    Analyze recent video performance and update selection weights, durations,
    and trigger A/B tests or warnings matching the blueprint optimization rules.
    """
    from database.models import get_db_session, VideoAnalytics, get_setting, set_setting
    import json
    
    session = get_db_session()
    actions = []
    warnings = []
    
    try:
        # Retrieve all recent analytics records
        analytics = session.query(VideoAnalytics).order_by(VideoAnalytics.created_at.desc()).limit(50).all()
        if not analytics:
            return {"status": "no_data", "message": "No video analytics data available for feedback loop."}
            
        # Load current downweights and forced combos
        downweights_str = get_setting("growth_engine_downweights", "{}")
        try:
            downweights = json.loads(downweights_str)
        except Exception:
            downweights = {}
            
        forced_combos_str = get_setting("growth_engine_forced_combos", "[]")
        try:
            forced_combos = json.loads(forced_combos_str)
        except Exception:
            forced_combos = []
            
        for record in analytics:
            key = f"{record.surah}:{record.reciter_key}"
            
            # Short-form checks
            if record.video_type == "short":
                # Metric 1: Short engagement < 30% -> Underperform -> Reduce combination weight
                if record.engagement_rate < 0.30:
                    current_weight = downweights.get(key, 1.0)
                    new_weight = max(0.1, current_weight - 0.2) # reduce weight by 20%
                    downweights[key] = new_weight
                    actions.append(f"Short {record.video_id} ({key}) engagement < 30% ({record.engagement_rate:.1%}). Reduced combo weight to {new_weight:.1f}")
                
                # Metric 2: Short engagement > 60% -> Outperform -> Duplicate combo
                elif record.engagement_rate > 0.60:
                    combo = {"surah": record.surah, "reciter_key": record.reciter_key}
                    if combo not in forced_combos:
                        forced_combos.append(combo)
                        actions.append(f"Short {record.video_id} ({key}) engagement > 60% ({record.engagement_rate:.1%}). Queued combo for duplication.")
                        
            # Long-form checks
            elif record.video_type == "long":
                # Metric 3: Long-form retention < 40% -> Underperform -> Test shorter clip rotation
                if record.retention_rate < 0.40:
                    set_setting("longform_clip_duration", "6") # Set to 6s
                    actions.append(f"Long-form {record.video_id} retention < 40% ({record.retention_rate:.1%}). Set clip rotation to 6-second clips.")
                    
            # Common checks
            # Metric 4: CTR < 4% -> Thumbnail weak -> Request A/B test
            if record.ctr < 0.04:
                set_setting("request_ab_test_thumbnail", "true")
                actions.append(f"Video {record.video_id} CTR < 4% ({record.ctr:.1%}). Thumbnail flagged for A/B testing.")
                
            # Metric 5: Comments > 20 -> Engagement winner -> Warn/Instruct
            if record.comments > 20:
                warnings.append(f"Engagement winner: Video {record.video_id} has {record.comments} comments! Pin related long-form link.")
                
        # Persist updated settings
        set_setting("growth_engine_downweights", json.dumps(downweights))
        set_setting("growth_engine_forced_combos", json.dumps(forced_combos))
        
        logger.success(f"Feedback loop completed. Applied {len(actions)} optimization actions.")
        return {
            "status": "success",
            "actions_applied": actions,
            "warnings_triggered": warnings,
            "updated_downweights": downweights,
            "queued_forced_combos": forced_combos
        }
        
    finally:
        session.close()


def trigger_ab_test_experiment(variable_type: str) -> Dict[str, Any]:
    """
    Every 7 days, trigger one controlled A/B test experiment.
    Variables: reciter, ayah_length, thumbnail_style
    """
    from database.models import get_db_session, ABTest
    import uuid
    import datetime
    
    if variable_type not in ["reciter", "ayah_length", "thumbnail_style"]:
        raise ValueError(f"Invalid A/B test variable: {variable_type}")
        
    session = get_db_session()
    try:
        video_id_a = f"ab_a_{uuid.uuid4().hex[:8]}"
        video_id_b = f"ab_b_{uuid.uuid4().hex[:8]}"
        
        experiment_name = f"exp_{variable_type}_{datetime.date.today().isoformat()}"
        
        test = ABTest(
            experiment_name=experiment_name,
            variable_type=variable_type,
            video_id_a=video_id_a,
            video_id_b=video_id_b,
            status="active"
        )
        session.add(test)
        session.commit()
        
        logger.info(f"Registered new A/B Test Experiment: '{experiment_name}' (Variable: {variable_type})")
        return {
            "status": "success",
            "experiment_name": experiment_name,
            "variable_type": variable_type,
            "video_id_a": video_id_a,
            "video_id_b": video_id_b
        }
    finally:
        session.close()


def evaluate_active_ab_tests() -> List[Dict[str, Any]]:
    """
    Check all active A/B tests, pull their metrics, select the winner, and adjust defaults.
    """
    from database.models import get_db_session, ABTest, VideoAnalytics, set_setting
    import datetime
    
    session = get_db_session()
    results = []
    
    try:
        active_tests = session.query(ABTest).filter_by(status="active").all()
        for test in active_tests:
            # Look up metrics
            metric_a = session.query(VideoAnalytics).filter_by(video_id=test.video_id_a).first()
            metric_b = session.query(VideoAnalytics).filter_by(video_id=test.video_id_b).first()
            
            # Require both metrics to evaluate
            if not metric_a or not metric_b:
                logger.debug(f"Metrics not yet available for both sides of A/B test: '{test.experiment_name}'")
                continue
                
            winner_id = None
            if test.variable_type == "thumbnail_style":
                # For thumbnails, CTR is the key metric
                winner_id = test.video_id_a if metric_a.ctr >= metric_b.ctr else test.video_id_b
                winner_ctr = max(metric_a.ctr, metric_b.ctr)
                winner_style = "Mosque Gold" if winner_id == test.video_id_a else "Open Quran"
                set_setting("default_thumbnail_template", winner_style)
                logger.success(f"A/B Test Winner: Style default updated to '{winner_style}' (CTR: {winner_ctr:.1%})")
            else:
                score_a = metric_a.views * (1.0 + metric_a.engagement_rate)
                score_b = metric_b.views * (1.0 + metric_b.engagement_rate)
                winner_id = test.video_id_a if score_a >= score_b else test.video_id_b
                
                if test.variable_type == "reciter":
                    winner_reciter = metric_a.reciter_key if winner_id == test.video_id_a else metric_b.reciter_key
                    set_setting("default_reciter", winner_reciter)
                    logger.success(f"A/B Test Winner: Default reciter updated to '{winner_reciter}'")
            
            test.winner_id = winner_id
            test.status = "completed"
            test.completed_at = datetime.datetime.utcnow()
            
            results.append({
                "experiment": test.experiment_name,
                "winner_video_id": winner_id,
                "variable_type": test.variable_type
            })
            
        if results:
            session.commit()
            
        return results
    finally:
        session.close()

