"""
Style Configuration - Centralized visual parameters for Quran Reels
"""
from dataclasses import dataclass, field
from typing import Tuple

from config.settings import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    FONT_PATH,
    FONT_COLOR,
    TEXT_MAX_WIDTH,
    FONT_SIZE_CONFIG,
    AYAH_PADDING_SECONDS,
    BACKGROUND_BRIGHTNESS,
    TEXT_FADE_IN_SECONDS,
    TEXT_FADE_OUT_SECONDS,
    VIDEO_FADE_SECONDS,
)


@dataclass
class StyleConfig:
    # Video dimensions
    video_width: int = VIDEO_WIDTH
    video_height: int = VIDEO_HEIGHT

    # Arabic text
    font_path: str = FONT_PATH
    font_color: str = FONT_COLOR
    text_max_width: int = TEXT_MAX_WIDTH
    font_size_config: dict = field(default_factory=lambda: FONT_SIZE_CONFIG)
    page_size: int = 12
    page_font_size: int = 72
    page_words_per_line: int = 5

    # Translation
    translation_font_size: int = 36
    translation_color: str = "#D0D8E0"
    translation_y_ratio: float = 0.68

    # Ayah number
    ayah_number_font_size: int = 48
    ayah_number_color: str = "#D4AF37"

    # Surah label
    surah_label_font_size: int = 38
    surah_label_bg_opacity: float = 0.45

    # Stroke (text outline)
    stroke_color: str = "black"
    stroke_width: int = 2

    # Shadow
    shadow_color: str = "#000000"
    shadow_offset: Tuple[int, int] = (2, 2)
    shadow_opacity: float = 0.7

    # Crossfade between pages
    page_crossfade_duration: float = 0.5

    # Background grading
    background_brightness: float = 0.38
    background_tint: Tuple[int, int, int] = (5, 12, 25)
    background_tint_opacity: float = 0.40
    ken_burns_zoom: float = 1.06

    # Timing
    ayah_padding: float = AYAH_PADDING_SECONDS
    text_fade_in: float = TEXT_FADE_IN_SECONDS
    text_fade_out: float = TEXT_FADE_OUT_SECONDS
    video_fade: float = VIDEO_FADE_SECONDS

    # Intro frame
    intro_bismillah_color: str = "#D4AF37"
    intro_bismillah_size: int = 52
    intro_surah_ar_size: int = 88
    intro_surah_en_size: int = 44
    intro_verse_range_size: int = 34


# Default instance
DEFAULT_STYLE = StyleConfig()
