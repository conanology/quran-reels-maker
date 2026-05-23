"""
Verification Test Script for the DailyQuran Growth Engine (AI Decision Brain)
"""
import sys
import os
import datetime
import pytz
from loguru import logger

# Ensure current directory is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from core.growth_engine import (
    get_mecca_time,
    get_current_slot,
    get_slot_format,
    is_combo_repeated_recently,
    pick_reciter,
    pick_surah,
    score_title_vidiq,
    generate_engine_title,
    get_thumbnail_template_for_format,
    execute_scheduled_slot
)
from database.models import get_db_session, ReelHistory, LongformHistory, init_database

def test_mecca_timezone():
    logger.info("Testing Mecca Timezone (UTC+3) offset...")
    mecca_time = get_mecca_time()
    utc_time = datetime.datetime.now(pytz.utc)
    
    # Calculate difference in hours
    diff = mecca_time.utcoffset().total_seconds() / 3600
    assert diff == 3.0, f"Expected offset UTC+3, got UTC+{diff}"
    logger.success("Mecca Timezone test passed.")

def test_slot_calculations():
    logger.info("Testing Slot Calculations...")
    mecca_tz = pytz.timezone("Asia/Riyadh")
    
    # Friday 9:00 PM (hour=21) -> friday_long
    friday_dt = mecca_tz.localize(datetime.datetime(2026, 5, 29, 21, 0, 0))
    assert get_current_slot(friday_dt) == "friday_long", f"Expected friday_long for {friday_dt}"
    
    # Saturday 10:00 PM (hour=22) -> saturday_sleep
    saturday_dt = mecca_tz.localize(datetime.datetime(2026, 5, 30, 22, 0, 0))
    assert get_current_slot(saturday_dt) == "saturday_sleep", f"Expected saturday_sleep for {saturday_dt}"
    
    # Daily 5:00 AM (hour=5) -> morning_short
    morning_dt = mecca_tz.localize(datetime.datetime(2026, 5, 27, 5, 30, 0))
    assert get_current_slot(morning_dt) == "morning_short", f"Expected morning_short for {morning_dt}"
    
    # Daily 8:00 PM (hour=20) -> evening_short
    evening_dt = mecca_tz.localize(datetime.datetime(2026, 5, 27, 20, 0, 0))
    assert get_current_slot(evening_dt) == "evening_short", f"Expected evening_short for {evening_dt}"
    
    logger.success("Slot Calculations test passed.")

def test_weekly_repetition_guardrails():
    logger.info("Testing Weekly Repetition Guardrails...")
    session = get_db_session()
    
    # Clean up any test records we might insert
    test_surah = 999
    test_reciter = "test_reciter_key"
    
    try:
        # Check initial state (should not be repeated)
        assert not is_combo_repeated_recently(test_surah, test_reciter, days=7)
        
        # Insert a recent reel record
        reel = ReelHistory(
            surah=test_surah,
            start_ayah=1,
            end_ayah=3,
            reciter_key=test_reciter,
            status="uploaded",
            created_at=datetime.datetime.utcnow()
        )
        session.add(reel)
        session.commit()
        
        # Now it should be detected as repeated
        assert is_combo_repeated_recently(test_surah, test_reciter, days=7)
        
        # Clean up
        session.delete(reel)
        session.commit()
        
        # Verify it's cleared
        assert not is_combo_repeated_recently(test_surah, test_reciter, days=7)
        logger.success("Weekly Repetition Guardrail test passed.")
        
    finally:
        session.close()

def test_vidiq_scoring_and_titles():
    logger.info("Testing vidIQ SEO scoring & Title modes...")
    
    # Standard Title
    good_title = "Surah Al-Mulk Full - Mishary Alafasy | Beautiful Quran Recitation for Sleep 🌙"
    score = score_title_vidiq(good_title)
    logger.info(f"Title: '{good_title}' scored {score}/100")
    assert score >= 80, f"Expected good title score >= 80, got {score}"
    
    # Bad Title (too short, no keywords, no emojis)
    bad_title = "Al-Mulk"
    score_bad = score_title_vidiq(bad_title)
    logger.info(f"Title: '{bad_title}' scored {score_bad}/100")
    assert score_bad < 70, f"Expected bad title score < 70, got {score_bad}"
    
    # Check all modes of Title generator
    modes = ["arabic_short_core", "arabic_short_gulf", "bilingual_long", "english_seo_long"]
    for mode in modes:
        title = generate_engine_title(mode, surah=67, reciter_key="alafasy")
        logger.info(f"Mode '{mode}' Title: '{title}' (Score: {score_title_vidiq(title)})")
        assert score_title_vidiq(title) >= 80, f"Generated title for mode '{mode}' did not score >= 80"
        
    logger.success("vidIQ SEO Title generator tests passed.")

def test_thumbnail_templates():
    logger.info("Testing Thumbnail template mapping...")
    assert get_thumbnail_template_for_format("sleep_long") == "Kaaba Night"
    assert get_thumbnail_template_for_format("full_surah_long") == "Open Quran"
    assert get_thumbnail_template_for_format("weekly_compilation") == "Mosque Gold"
    assert get_thumbnail_template_for_format("standard_short") == "Reciter Showcase"
    logger.success("Thumbnail template mapping tests passed.")

def test_dry_run_slots():
    logger.info("Testing Dry-Run execution across scheduled slots...")
    slots = ["morning_short", "evening_short", "friday_long", "saturday_sleep"]
    
    for slot in slots:
        logger.info(f"Testing slot dry run: '{slot}'...")
        res = execute_scheduled_slot(slot_name=slot, dry_run=True)
        assert res["status"] == "dry_run"
        assert res["slot"] == slot
        assert "format" in res
        assert "surah" in res
        assert "reciter" in res
        assert "title" in res
        assert "thumbnail_template" in res
        assert "bg_prompt" in res
        logger.info(f"Slot dry run '{slot}' output: Format={res['format']}, Title='{res['title']}'")
        
    logger.success("Dry-Run execution tests passed.")

def run_all_tests():
    init_database()
    logger.info("Starting DailyQuran Growth Engine Verification Tests...")
    print("="*60)
    
    try:
        test_mecca_timezone()
        print("-" * 50)
        test_slot_calculations()
        print("-" * 50)
        test_weekly_repetition_guardrails()
        print("-" * 50)
        test_vidiq_scoring_and_titles()
        print("-" * 50)
        test_thumbnail_templates()
        print("-" * 50)
        test_dry_run_slots()
        print("="*60)
        logger.success("ALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")
    except AssertionError as e:
        logger.error(f"TEST ASSERTION FAILURE: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"TEST EXECUTION ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_all_tests()
