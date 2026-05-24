"""
Verification Script - Test dynamic longform background, metadata, and thumbnail generation.
"""
import os
import sys
import json
from pathlib import Path
from loguru import logger

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent))

# Load .env variables
from dotenv import load_dotenv
load_dotenv()

from config.settings import OPENROUTER_API_KEY, LONGFORM_OUTPUT_DIR
from longform.compiler import generate_longform

def test_longform_pipeline():
    logger.info("=== Testing Longform Pipeline (AI Background + Metadata + Thumbnail) ===")
    
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not set in .env. Falling back to default metadata / Pexels, but dynamic features will be skipped.")
    else:
        logger.info("OPENROUTER_API_KEY is configured. AI metadata and background should generate.")

    try:
        # Run compiler for Surah 112 (Al-Ikhlas) with loop_count=1
        logger.info("Running generate_longform for Surah 112...")
        metadata = generate_longform(
            surah_start=112,
            surah_end=112,
            reciter_key="alafasy",
            loop_count=1
        )
        
        # Verify output dictionary
        if not metadata:
            logger.error("generate_longform returned empty metadata.")
            return False

        logger.success("generate_longform execution completed.")
        
        output_path_str = metadata.get("output_path")
        if not output_path_str:
            logger.error("Metadata is missing 'output_path'.")
            return False

        output_path = Path(output_path_str)
        if not output_path.exists():
            logger.error(f"Generated video file does not exist at: {output_path}")
            return False
            
        logger.success(f"Video file generated successfully: {output_path}")
        logger.info(f"Video size: {output_path.stat().st_size / (1024*1024):.2f} MB")

        # Verify JSON metadata file
        meta_json_path = output_path.with_suffix(".mp4.json")
        if not meta_json_path.exists():
            # Sometimes it's final_output + ".json", which means it's .mp4.json
            logger.error(f"Metadata JSON file does not exist at: {meta_json_path}")
            return False
        
        logger.success(f"Metadata JSON file exists: {meta_json_path}")
        with open(meta_json_path, "r", encoding="utf-8") as f:
            meta_data = json.load(f)
            logger.info(f"Parsed Title: {meta_data.get('recommended_title')}")
            logger.info(f"Parsed Thumbnail Path: {meta_data.get('thumbnail_path')}")
            logger.info(f"Description snippet:\n{meta_data.get('description')[:300]}...")
            logger.info(f"Tags: {meta_data.get('tags')}")

        # Verify Thumbnail file
        thumbnail_path_str = meta_data.get("thumbnail_path")
        if not thumbnail_path_str:
            logger.error("Thumbnail path was not stored in metadata JSON.")
            return False
            
        thumbnail_path = Path(thumbnail_path_str)
        if not thumbnail_path.exists():
            logger.error(f"Thumbnail image file does not exist at: {thumbnail_path}")
            return False
            
        logger.success(f"Thumbnail image generated successfully: {thumbnail_path}")
        logger.info(f"Thumbnail size: {thumbnail_path.stat().st_size / 1024:.2f} KB")

        logger.info("=== Visualizing generated thumbnail structure ===")
        # Basic check that the image is a valid JPG
        from PIL import Image
        try:
            with Image.open(thumbnail_path) as img:
                logger.info(f"Thumbnail dimensions: {img.size} (Expected: 1280x720)")
                logger.info(f"Thumbnail format: {img.format}")
                if img.size == (1280, 720):
                    logger.success("Thumbnail size check passed!")
                else:
                    logger.error(f"Thumbnail size is incorrect: {img.size}")
                    return False
        except Exception as e:
            logger.error(f"Failed to load generated thumbnail image: {e}")
            return False

        logger.success("🎉 Longform automated thumbnail and metadata pipeline is FULLY FUNCTIONAL!")
        return True

    except Exception as e:
        logger.exception(f"Longform pipeline test failed with exception: {e}")
        return False

if __name__ == "__main__":
    success = test_longform_pipeline()
    sys.exit(0 if success else 1)
