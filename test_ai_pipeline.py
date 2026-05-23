"""
Verification Script - Test AI Background & Metadata Generation end-to-end.
"""
import os
import sys
from pathlib import Path
from loguru import logger

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent))

# Load .env variables
from dotenv import load_dotenv
load_dotenv()

from config.settings import OPENROUTER_API_KEY, OPENROUTER_MODEL
from core.ai_brain import generate_visual_prompt, generate_video_metadata
from core.quran_api import get_ayah_translation, get_surah_name
from core.video_generator import generate_reel
from youtube.uploader import generate_metadata

def test_openrouter():
    logger.info("=== Testing OpenRouter Integration ===")
    logger.info(f"Model configured: {OPENROUTER_MODEL}")
    
    # Test verse: Surah 112 (Al-Ikhlas) Ayah 1
    translation = get_ayah_translation(112, 1)
    logger.info(f"Test translation: \"{translation}\"")
    
    # 1. Test prompt generation
    prompt = generate_visual_prompt(translation)
    if prompt:
        logger.success(f"Successfully generated visual prompt: \"{prompt}\"")
    else:
        logger.error("Failed to generate visual prompt.")
        return False
        
    # 2. Test metadata generation
    metadata = generate_video_metadata(
        surah_name="Al-Ikhlas",
        start_ayah=1,
        end_ayah=4,
        reciter_name="Mishary Alafasy",
        translation=translation
    )
    if metadata:
        logger.success("Successfully generated video metadata:")
        logger.info(f"Title: {metadata.get('title')}")
        logger.info(f"Description:\n{metadata.get('description')}")
        logger.info(f"Tags: {metadata.get('tags')}")
    else:
        logger.error("Failed to generate video metadata.")
        return False
        
    return True

def test_video_generation():
    logger.info("=== Testing Video Generation with AI Background ===")
    
    # Generate video for Surah 112, Ayahs 1 to 4
    output_path = Path("outputs/videos/test_ai_reel.mp4")
    if output_path.exists():
        output_path.unlink()
        
    try:
        video_path, start, end = generate_reel(
            surah=112,
            start_ayah=1,
            end_ayah=4,
            reciter_key="alafasy",
            output_path=output_path
        )
        
        if video_path.exists():
            logger.success(f"Successfully generated video at: {video_path}")
            logger.info(f"Video size: {video_path.stat().st_size / (1024*1024):.2f} MB")
            return True
        else:
            logger.error("Video file does not exist after generation.")
            return False
    except Exception as e:
        logger.exception(f"Video generation failed: {e}")
        return False

def test_youtube_metadata():
    logger.info("=== Testing YouTube Metadata Integration ===")
    meta = generate_metadata(
        surah=112,
        start_ayah=1,
        end_ayah=4,
        reciter_key="alafasy",
        full_text="قُلْ هُوَ اللَّهُ أَحَدٌ"
    )
    logger.success("Successfully generated YouTube metadata package:")
    logger.info(f"Title: {meta.get('title')}")
    logger.info(f"Tags count: {len(meta.get('tags', []))}")
    return True

if __name__ == "__main__":
    logger.info("Starting verification tests...")
    
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY is not set in .env. Cannot proceed with tests.")
        sys.exit(1)
        
    or_success = test_openrouter()
    if not or_success:
        logger.error("OpenRouter test failed. Aborting further tests.")
        sys.exit(1)
        
    yt_success = test_youtube_metadata()
    if not yt_success:
        logger.error("YouTube metadata test failed. Aborting further tests.")
        sys.exit(1)
        
    vid_success = test_video_generation()
    if vid_success:
        logger.success("🎉 ALL TESTS PASSED SUCCESSFULLY! The dynamic AI pipeline is fully functional!")
    else:
        logger.error("Video generation test failed.")
        sys.exit(1)
