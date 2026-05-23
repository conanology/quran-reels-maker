"""
Verification Test Script for the DailyQuran Growth Engine (AI Decision Brain & Analytics)
"""
import sys
import os
import datetime
import pytz
import json
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
    execute_scheduled_slot,
    ingest_video_analytics,
    run_feedback_loop_analysis,
    trigger_ab_test_experiment,
    evaluate_active_ab_tests
)
from database.models import (
    get_db_session,
    ReelHistory,
    LongformHistory,
    VideoAnalytics,
    ABTest,
    get_setting,
    set_setting,
    init_database
)

def test_mecca_timezone():
    logger.info("Testing Mecca Timezone (UTC+3) offset...")
    mecca_time = get_mecca_time()
    
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
    
    test_surah = 999
    test_reciter = "test_reciter_key"
    
    try:
        assert not is_combo_repeated_recently(test_surah, test_reciter, days=7)
        
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
        
        assert is_combo_repeated_recently(test_surah, test_reciter, days=7)
        
        session.delete(reel)
        session.commit()
        
        assert not is_combo_repeated_recently(test_surah, test_reciter, days=7)
        logger.success("Weekly Repetition Guardrail test passed.")
        
    finally:
        session.close()

def test_vidiq_scoring_and_titles():
    logger.info("Testing vidIQ SEO scoring & Title modes...")
    
    good_title = "Surah Al-Mulk Full - Mishary Alafasy | Beautiful Quran Recitation for Sleep 🌙"
    score = score_title_vidiq(good_title)
    logger.info(f"Title: '{good_title}' scored {score}/100")
    assert score >= 80, f"Expected good title score >= 80, got {score}"
    
    bad_title = "Al-Mulk"
    score_bad = score_title_vidiq(bad_title)
    logger.info(f"Title: '{bad_title}' scored {score_bad}/100")
    assert score_bad < 70, f"Expected bad title score < 70, got {score_bad}"
    
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

def test_feedback_loop_performance_analytics():
    logger.info("Testing Performance Feedback Loop & Analytics rules...")
    session = get_db_session()
    
    # Reset settings for clean testing
    set_setting("growth_engine_downweights", "{}")
    set_setting("growth_engine_forced_combos", "[]")
    set_setting("longform_clip_duration", "15")
    set_setting("request_ab_test_thumbnail", "false")
    
    # Clean old test analytics
    session.query(VideoAnalytics).delete()
    session.commit()
    
    try:
        # Ingest mock metrics
        # 1. Underperforming Short: engagement = 15/100 = 15% (<30%)
        ingest_video_analytics(
            video_id="v_short_low", views=100, likes=10, comments=5,
            retention_rate=0.5, ctr=0.08, surah=112, reciter_key="husary", video_type="short"
        )
        # 2. Outperforming Short: engagement = 65/100 = 65% (>60%)
        ingest_video_analytics(
            video_id="v_short_high", views=100, likes=50, comments=15,
            retention_rate=0.8, ctr=0.12, surah=108, reciter_key="alafasy", video_type="short"
        )
        # 3. Underperforming Longform: retention = 35% (<40%)
        ingest_video_analytics(
            video_id="v_long_low", views=200, likes=20, comments=2,
            retention_rate=0.35, ctr=0.06, surah=67, reciter_key="maher_muaiqly", video_type="long"
        )
        # 4. Weak CTR Video: CTR = 3% (<4%)
        ingest_video_analytics(
            video_id="v_weak_ctr", views=500, likes=40, comments=5,
            retention_rate=0.5, ctr=0.03, surah=36, reciter_key="sudais", video_type="short"
        )
        
        # Run Feedback Loop analysis
        logger.info("Running feedback loop auto-analysis...")
        res = run_feedback_loop_analysis()
        logger.info(f"Feedback Loop Actions: {json.dumps(res['actions_applied'], indent=2)}")
        
        # Verify weight reductions
        downweights = res["updated_downweights"]
        assert "112:husary" in downweights
        assert downweights["112:husary"] < 1.0, f"Husary combo should be downweighted, got {downweights['112:husary']}"
        
        # Verify forced combos duplication queue
        forced_combos = res["queued_forced_combos"]
        assert any(c["surah"] == 108 and c["reciter_key"] == "alafasy" for c in forced_combos), "Alafasy combo should be queued for duplication"
        
        # Verify longform clip duration adjustments
        assert get_setting("longform_clip_duration") == "6", "Expected clip duration override to 6s"
        
        # Verify A/B test trigger flags
        assert get_setting("request_ab_test_thumbnail") == "true", "Expected A/B test flag set to true"
        
        logger.success("Performance Feedback Loop rules tests passed.")
        
    finally:
        session.query(VideoAnalytics).delete()
        session.commit()
        session.close()

def test_ab_test_controlled_experiments():
    logger.info("Testing A/B Test Controlled Experiments...")
    session = get_db_session()
    
    # Clean old tests
    session.query(ABTest).delete()
    session.query(VideoAnalytics).delete()
    session.commit()
    
    try:
        # Trigger A/B Test
        res = trigger_ab_test_experiment("reciter")
        exp_name = res["experiment_name"]
        video_id_a = res["video_id_a"]
        video_id_b = res["video_id_b"]
        
        # Ingest metrics where B outperforms A
        # A: 1000 views, 10% engagement (100 likes) -> score = 1000 * 1.1 = 1100
        # B: 1500 views, 20% engagement (300 likes) -> score = 1500 * 1.2 = 1800 -> Winner!
        ingest_video_analytics(
            video_id=video_id_a, views=1000, likes=90, comments=10,
            retention_rate=0.5, ctr=0.08, surah=67, reciter_key="sudais", video_type="short"
        )
        ingest_video_analytics(
            video_id=video_id_b, views=1500, likes=280, comments=20,
            retention_rate=0.6, ctr=0.09, surah=67, reciter_key="alafasy", video_type="short"
        )
        
        # Evaluate active A/B tests
        results = evaluate_active_ab_tests()
        logger.info(f"A/B test evaluation result: {json.dumps(results, indent=2)}")
        
        assert len(results) == 1
        assert results[0]["winner_video_id"] == video_id_b
        
        # Verify winner reciter became default setting
        assert get_setting("default_reciter") == "alafasy", "Winner reciter should become default setting"
        
        logger.success("A/B Test Controlled Experiments tests passed.")
        
    finally:
        session.query(ABTest).delete()
        session.query(VideoAnalytics).delete()
        session.commit()
        session.close()

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
        test_feedback_loop_performance_analytics()
        print("-" * 50)
        test_ab_test_controlled_experiments()
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
