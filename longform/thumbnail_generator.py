"""
Longform Thumbnail Generator - Create highly premium, high-CTR YouTube thumbnails for Quran long-form videos.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from config.settings import FONTS_DIR, SURAH_NAMES_AR, SURAH_NAMES_EN

FONT_PATH = FONTS_DIR / "amiri" / "Amiri-Bold.ttf"

def draw_text_with_stroke(
    draw: ImageDraw.ImageDraw,
    position: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color: tuple,
    stroke_color: tuple = (0, 0, 0, 255),
    stroke_width: int = 4,
    **kwargs
) -> None:
    """Draw text with a strong outline/stroke for maximum legibility on thumbnails."""
    draw.text(
        position,
        text,
        font=font,
        fill=text_color,
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
        **kwargs
    )

def generate_longform_thumbnail(
    surah_start: int,
    surah_end: int,
    reciter_name_ar: str,
    reciter_name_en: str,
    bg_image_path: Path,
    output_path: Path,
    custom_title_en: Optional[str] = None
) -> Path:
    """
    Generate a professional, high-CTR YouTube thumbnail (1280x720).
    
    Layout:
    - Elegant gold frame inset.
    - Large centered gold Arabic Surah name.
    - Large white English Surah name.
    - Subtitle "FULL RECITATION" or custom theme.
    - Reciter name at the bottom in gold/white.
    """
    logger.info(f"Generating longform thumbnail from background: {bg_image_path.name}")
    
    # 1. Load background image and resize/crop to exactly 1280x720 (16:9)
    try:
        bg = Image.open(bg_image_path).convert("RGBA")
        bg = bg.resize((1280, 720), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.error(f"Failed to load background image for thumbnail: {e}")
        # Create a fallback dark gradient image
        bg = Image.new("RGBA", (1280, 720), (20, 24, 33, 255))

    # 2. Create drawing overlays
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Draw semi-transparent dark overlay (tint)
    draw.rectangle([(0, 0), bg.size], fill=(0, 0, 0, 115))  # ~45% black tint
    
    # Draw elegant gold frame inset by 25px
    inset = 25
    gold_color = (212, 175, 55, 220)  # Premium gold
    draw.rectangle(
        [(inset, inset), (1280 - inset, 720 - inset)],
        outline=gold_color,
        width=3
    )

    # 3. Load Fonts
    # We want distinct typography:
    # - Arabic title: Cairo-Bold or Zain-Bold (very modern/premium) or fallback Amiri-Bold
    # - English title: Dubai-Bold or Amiri-Bold (serif matches translation style nicely)
    # - Subtitle & Reciter: Dubai-Bold or Zain-Bold
    font_large_ar = None
    font_large_en = None
    font_medium = None
    font_small = None
    
    font_ar_path = FONTS_DIR / "amiri" / "Amiri-Bold.ttf"

    font_en_path = FONTS_DIR / "dubai" / "Dubai-Bold.ttf"
    if not font_en_path.exists():
        font_en_path = FONTS_DIR / "amiri" / "Amiri-Bold.ttf"

    try:
        font_large_ar = ImageFont.truetype(str(font_ar_path), 96)
        font_large_en = ImageFont.truetype(str(font_en_path), 76)
        font_medium = ImageFont.truetype(str(font_en_path), 36)
        font_small = ImageFont.truetype(str(font_en_path), 28)
    except Exception as e:
        logger.warning(f"Could not load custom fonts, using default fallbacks: {e}")
        try:
            font_large_ar = ImageFont.truetype("Arial", 90)
            font_large_en = ImageFont.truetype("Arial", 70)
            font_medium = ImageFont.truetype("Arial", 32)
            font_small = ImageFont.truetype("Arial", 26)
        except OSError:
            font_large_ar = font_large_en = font_medium = font_small = ImageFont.load_default()

    # 4. Prepare Arabic Surah Title text
    if surah_start == surah_end:
        ar_title = f"سُورَة {SURAH_NAMES_AR[surah_start - 1]}"
    else:
        ar_title = f"سُورَة {SURAH_NAMES_AR[surah_start - 1]} - {SURAH_NAMES_AR[surah_end - 1]}"
        
    # Apply Arabic Reshaping & Bidi
    reshaper = arabic_reshaper.ArabicReshaper(configuration={
        'delete_harakat': False,
        'delete_tatweel': False,
    })
    reshaped_ar = reshaper.reshape(ar_title)
    ar_display = get_display(reshaped_ar)

    # 5. Prepare English Surah Title text
    if custom_title_en:
        en_display = custom_title_en.upper()
    else:
        if surah_start == surah_end:
            en_display = f"SURAH {SURAH_NAMES_EN[surah_start - 1].upper()}"
        else:
            en_display = f"SURAH {SURAH_NAMES_EN[surah_start - 1].upper()} TO {SURAH_NAMES_EN[surah_end - 1].upper()}"

    # 6. Prepare Reciter Name & Subtitle
    reciter_display = f"Recited by {reciter_name_en}"
    subtitle_display = "BEAUTIFUL & HEART SOOTHING RECITATION"

    # 7. Render Text Layers (all centered horizontally)
    # Optimized visual spacing:
    # - Arabic title (Cairo/Zain): y=110, size=96, premium gold color
    # - English title (Dubai-Bold): y=250, size=76, white
    # - Subtitle: y=420, size=36, gold/yellow, smaller tracking (represented by smaller font if needed, font_medium)
    # - Reciter name: y=530, size=28 (font_small), clean light gray
    
    # Render Arabic Title (Gold)
    bbox_ar = draw.textbbox((0, 0), ar_display, font=font_large_ar)
    ar_w = bbox_ar[2] - bbox_ar[0]
    draw_text_with_stroke(
        draw,
        ((1280 - ar_w) // 2, 110),
        ar_display,
        font=font_large_ar,
        text_color=(212, 175, 55, 255),
        stroke_color=(0, 0, 0, 255),
        stroke_width=5
    )

    # Render English Title (White)
    bbox_en = draw.textbbox((0, 0), en_display, font=font_large_en)
    en_w = bbox_en[2] - bbox_en[0]
    draw_text_with_stroke(
        draw,
        ((1280 - en_w) // 2, 250),
        en_display,
        font=font_large_en,
        text_color=(255, 255, 255, 255),
        stroke_color=(0, 0, 0, 255),
        stroke_width=5
    )

    # Render Subtitle (Gold/Yellow)
    bbox_sub = draw.textbbox((0, 0), subtitle_display, font=font_medium)
    sub_w = bbox_sub[2] - bbox_sub[0]
    draw_text_with_stroke(
        draw,
        ((1280 - sub_w) // 2, 420),
        subtitle_display,
        font=font_medium,
        text_color=(255, 215, 0, 255),  # Bright gold/yellow
        stroke_color=(0, 0, 0, 255),
        stroke_width=4
    )

    # Render Reciter Name (White/Light Gray)
    bbox_rec = draw.textbbox((0, 0), reciter_display, font=font_small)
    rec_w = bbox_rec[2] - bbox_rec[0]
    draw_text_with_stroke(
        draw,
        ((1280 - rec_w) // 2, 530),
        reciter_display,
        font=font_small,
        text_color=(235, 235, 235, 255),
        stroke_color=(0, 0, 0, 255),
        stroke_width=3
    )

    # Combine background and overlay
    final_img = Image.alpha_composite(bg, overlay).convert("RGB")
    
    # Save to disk
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_img.save(output_path, "JPEG", quality=95)
    logger.success(f"Successfully generated YouTube thumbnail at: {output_path.name}")
    
    return output_path
