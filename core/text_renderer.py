"""
Text Renderer - PIL-based text rendering with stroke, shadow, and page crossfade.

Replaces per-word TextClip subprocess calls with cached PIL renders
composed through a single VideoClip make_frame callback.
"""
import os
import re
import math
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from loguru import logger

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _reshaper = arabic_reshaper.ArabicReshaper(configuration={
        'delete_harakat': False,
        'delete_tatweel': False,
    })
    _HAS_BIDI = True
except ImportError:
    _HAS_BIDI = False

from moviepy.editor import VideoClip, CompositeVideoClip, TextClip, ColorClip

from config.settings import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    FONT_PATH,
    FONT_COLOR,
    TEXT_MAX_WIDTH,
    FONT_SIZE_CONFIG,
)
from core.style_config import StyleConfig, DEFAULT_STYLE


# ---------------------------------------------------------------------------
# Uthmani mark stripping
# ---------------------------------------------------------------------------

# Uthmani-specific marks (U+06D6–U+06ED) that may render as squares in
# common fonts like Dubai.  Standard Arabic diacritics (U+064B–U+0652)
# are intentionally preserved.
_UTHMANI_STRIP_RE = re.compile("[\u06D6-\u06ED]")


def _clean_arabic(text: str) -> str:
    """Strip Uthmani-specific small marks that the current font may not support."""
    return _UTHMANI_STRIP_RE.sub("", text)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert '#RRGGBB' or named color to (R,G,B) tuple."""
    if hex_color.startswith("#"):
        h = hex_color.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    color_map = {
        "white": (255, 255, 255),
        "black": (0, 0, 0),
        "gold": (255, 215, 0),
    }
    return color_map.get(hex_color.lower(), (255, 255, 255))


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, falling back to default."""
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    try:
        return ImageFont.truetype("Arial", size)
    except OSError:
        return ImageFont.load_default()


def wrap_text(text: str, words_per_line: int) -> str:
    """Wrap text into multiple lines based on word count per line."""
    words = text.split()
    lines = [
        " ".join(words[i : i + words_per_line])
        for i in range(0, len(words), words_per_line)
    ]
    return "\n".join(lines)


def get_font_settings(word_count: int) -> Tuple[int, int]:
    """Get (font_size, words_per_line) based on text length."""
    for config in FONT_SIZE_CONFIG.values():
        if word_count >= config["min_words"]:
            return config["font_size"], config["words_per_line"]
    return 35, 6


# ---------------------------------------------------------------------------
# PIL Text Renderer
# ---------------------------------------------------------------------------

class PILTextRenderer:
    """
    Render Arabic text to RGBA numpy arrays using Pillow.
    Uses native harfbuzz/raqm shaping for proper Arabic letter joining
    and RTL layout. Supports stroke outline and drop shadow.
    Caches rendered frames by text string.
    """

    def __init__(self, style: StyleConfig = DEFAULT_STYLE):
        self.style = style
        self._cache: Dict[str, np.ndarray] = {}
        # Check for native RTL support (Pillow 10+ with libraqm)
        from PIL import features
        self._has_raqm = features.check("raqm")
        if self._has_raqm:
            logger.debug("Using native Pillow raqm/harfbuzz for Arabic shaping")
        elif _HAS_BIDI:
            logger.info("Using arabic-reshaper + python-bidi fallback for Arabic shaping")
        else:
            logger.warning(
                "Neither raqm nor arabic-reshaper available. "
                "Arabic text will NOT render correctly."
            )

    def render_text(
        self,
        text: str,
        font_size: int,
        color: str = "white",
        max_width: int = TEXT_MAX_WIDTH,
        words_per_line: int = 5,
        align: str = "center",
        is_arabic: bool = True,
    ) -> np.ndarray:
        """
        Render text with stroke and shadow to an RGBA numpy array.
        Uses native PIL direction='rtl' for Arabic text (preserves diacritics).
        """
        # Strip Uthmani marks that may render as squares
        if is_arabic:
            text = _clean_arabic(text)

        cache_key = f"{text}|{font_size}|{color}|{max_width}|{words_per_line}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        style = self.style

        # Wrap text by word count
        wrapped = wrap_text(text, words_per_line)
        display_text = wrapped

        font = _load_font(style.font_path, font_size)
        text_color = _hex_to_rgb(color)
        stroke_color = _hex_to_rgb(style.stroke_color)
        shadow_color_rgb = _hex_to_rgb(style.shadow_color)

        # Build extra kwargs for Arabic text
        text_kwargs: Dict[str, Any] = {}
        if is_arabic and self._has_raqm:
            text_kwargs["direction"] = "rtl"
            text_kwargs["language"] = "ar"
        elif is_arabic and _HAS_BIDI:
            # Fallback: reshape + bidi reorder per line so Pillow renders correct glyphs
            reshaped_lines = []
            for line in display_text.split("\n"):
                reshaped = _reshaper.reshape(line)
                reshaped_lines.append(get_display(reshaped))
            display_text = "\n".join(reshaped_lines)

        # Measure text size with stroke
        dummy_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        dummy_draw = ImageDraw.Draw(dummy_img)

        # For multiline RTL, render each line separately and measure
        lines = display_text.split("\n")
        line_sizes = []
        for line in lines:
            bbox = dummy_draw.textbbox(
                (0, 0), line, font=font,
                stroke_width=style.stroke_width,
                **text_kwargs,
            )
            line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

        text_w = max(w for w, h in line_sizes)
        line_height = max(h for w, h in line_sizes) if line_sizes else font_size
        text_h = line_height * len(lines) + int(font_size * 0.2) * (len(lines) - 1)

        # Add padding for shadow
        sx, sy = style.shadow_offset
        pad = max(abs(sx), abs(sy)) + style.stroke_width + 4
        img_w = int(text_w + pad * 2)
        img_h = int(text_h + pad * 2)

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw each line, centered horizontally
        y_cursor = pad
        for i, line in enumerate(lines):
            lw, lh = line_sizes[i]
            # Center each line within img_w
            lx = (img_w - lw) // 2
            ly = y_cursor

            # Draw shadow
            if style.shadow_opacity > 0:
                shadow_alpha = int(255 * style.shadow_opacity)
                shadow_rgba = shadow_color_rgb + (shadow_alpha,)
                shadow_img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
                shadow_draw = ImageDraw.Draw(shadow_img)
                shadow_draw.text(
                    (lx + sx, ly + sy), line, font=font,
                    fill=shadow_rgba, stroke_width=0,
                    **text_kwargs,
                )
                img = Image.alpha_composite(img, shadow_img)
                draw = ImageDraw.Draw(img)

            # Draw main text with stroke
            draw.text(
                (lx, ly), line, font=font,
                fill=text_color + (255,),
                stroke_width=style.stroke_width,
                stroke_fill=stroke_color + (255,),
                **text_kwargs,
            )

            y_cursor += line_height + int(font_size * 0.2)

        result = np.array(img)
        self._cache[cache_key] = result
        return result

    def clear_cache(self):
        self._cache.clear()


# Module-level renderer instance
_renderer: Optional[PILTextRenderer] = None


def _get_renderer(style: StyleConfig = DEFAULT_STYLE) -> PILTextRenderer:
    global _renderer
    if _renderer is None:
        _renderer = PILTextRenderer(style)
    return _renderer


# ---------------------------------------------------------------------------
# Page Boundary Computation
# ---------------------------------------------------------------------------

def compute_page_boundaries(
    sorted_segments: List[Dict[str, Any]],
    word_count: int,
    total_duration: float,
    page_size: int = 12,
) -> List[Dict[str, Any]]:
    """
    Compute page transition boundaries from word segments.

    Args:
        sorted_segments: Timing segments sorted by start_ms
        word_count: Total number of words
        total_duration: Total duration of the ayah audio
        page_size: Words per page

    Returns:
        List of dicts: {page_index, start_time, end_time,
                        word_start_idx, word_end_idx}
    """
    if not sorted_segments:
        return []

    num_pages = max(1, math.ceil(word_count / page_size))
    pages: List[Dict[str, Any]] = []

    for p in range(num_pages):
        w_start = p * page_size
        w_end = min((p + 1) * page_size - 1, word_count - 1)

        # Find timing for this page
        # Start time = start of first word in this page
        start_time = total_duration  # fallback
        end_time = 0.0

        for seg in sorted_segments:
            idx = seg["word_index"] - 1  # segments are 1-based
            if w_start <= idx <= w_end:
                seg_start = seg["start_ms"] / 1000.0
                seg_end = seg["end_ms"] / 1000.0
                start_time = min(start_time, seg_start)
                end_time = max(end_time, seg_end)

        # Last page extends to total_duration
        if p == num_pages - 1:
            end_time = total_duration

        # First page starts at 0
        if p == 0:
            start_time = 0.0

        pages.append(
            {
                "page_index": p,
                "start_time": start_time,
                "end_time": end_time,
                "word_start_idx": w_start,
                "word_end_idx": w_end,
            }
        )

    return pages


# ---------------------------------------------------------------------------
# Translation Splitting
# ---------------------------------------------------------------------------

def split_translation_by_pages(
    translation: str,
    page_boundaries: List[Dict[str, Any]],
    total_word_count: int,
) -> List[str]:
    """
    Split an English translation proportionally across pages.

    Args:
        translation: Full English translation string
        page_boundaries: Output of compute_page_boundaries
        total_word_count: Total Arabic word count

    Returns:
        List of translation segments (one per page)
    """
    if not translation or not page_boundaries:
        return [translation or ""] * max(1, len(page_boundaries))

    words = translation.split()
    n_trans_words = len(words)
    n_pages = len(page_boundaries)

    if n_pages <= 1:
        return [translation]

    segments: List[str] = []
    consumed = 0

    for i, pb in enumerate(page_boundaries):
        page_arabic_words = pb["word_end_idx"] - pb["word_start_idx"] + 1
        ratio = page_arabic_words / max(total_word_count, 1)
        count = max(1, round(ratio * n_trans_words))

        if i == n_pages - 1:
            # Last page gets remainder
            seg_words = words[consumed:]
        else:
            seg_words = words[consumed : consumed + count]

        # Try to split at clause boundaries (comma, semicolon)
        seg_text = " ".join(seg_words)
        segments.append(seg_text)
        consumed += len(seg_words)

    # Fill any empty trailing segments
    while len(segments) < n_pages:
        segments.append("")

    return segments


# ---------------------------------------------------------------------------
# MoviePy Clip Helpers (stroke + shadow via PIL)
# ---------------------------------------------------------------------------

def _make_centered_frame(
    rgba_array: np.ndarray,
    video_w: int,
    video_h: int,
    y_position: Optional[float] = None,
) -> np.ndarray:
    """
    Place an RGBA text render centered on a transparent canvas.
    If the text is wider than the video, it is scaled down to fit
    with a margin.

    Args:
        rgba_array: RGBA numpy array of rendered text
        video_w: Video width
        video_h: Video height
        y_position: Vertical position ratio (0-1). None = center.

    Returns:
        RGBA numpy array of (video_h, video_w, 4)
    """
    th, tw = rgba_array.shape[:2]

    # Scale down if text is wider than video (with 40px margin each side)
    max_w = video_w - 80
    if tw > max_w and tw > 0:
        scale = max_w / tw
        new_w = int(tw * scale)
        new_h = int(th * scale)
        pil_img = Image.fromarray(rgba_array)
        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
        rgba_array = np.array(pil_img)
        th, tw = rgba_array.shape[:2]

    canvas = np.zeros((video_h, video_w, 4), dtype=np.uint8)

    # Center horizontally
    x_off = max(0, (video_w - tw) // 2)
    # Vertical: center or at specified ratio
    if y_position is not None:
        y_off = max(0, int(video_h * y_position) - th // 2)
    else:
        y_off = max(0, (video_h - th) // 2)

    # Clamp to canvas bounds
    paste_w = min(tw, video_w - x_off)
    paste_h = min(th, video_h - y_off)

    canvas[y_off : y_off + paste_h, x_off : x_off + paste_w] = rgba_array[
        :paste_h, :paste_w
    ]
    return canvas


def create_pil_text_clip(
    text: str,
    duration: float,
    font_size: int,
    color: str = "white",
    words_per_line: int = 5,
    y_position: Optional[float] = None,
    is_arabic: bool = True,
    style: StyleConfig = DEFAULT_STYLE,
) -> VideoClip:
    """
    Create a VideoClip from PIL-rendered text with stroke and shadow.

    Args:
        text: Text to render
        duration: Clip duration
        font_size: Font size
        color: Text color
        words_per_line: Words per line
        y_position: Vertical position ratio (None = center)
        is_arabic: Apply Arabic reshaping
        style: StyleConfig

    Returns:
        VideoClip with transparent background
    """
    renderer = _get_renderer(style)
    rgba = renderer.render_text(
        text,
        font_size=font_size,
        color=color,
        max_width=style.text_max_width,
        words_per_line=words_per_line,
        is_arabic=is_arabic,
    )

    frame = _make_centered_frame(
        rgba, style.video_width, style.video_height, y_position
    )

    # Pre-compute RGB and alpha mask
    rgb = frame[:, :, :3]
    alpha = frame[:, :, 3:].astype(np.float32) / 255.0

    def make_frame(t):
        return rgb

    clip = VideoClip(make_frame, duration=duration)
    clip = clip.set_position((0, 0))

    # Create mask from alpha channel
    def make_mask(t):
        return alpha[:, :, 0]

    from moviepy.editor import VideoClip as _VC
    mask_clip = _VC(make_mask, duration=duration, ismask=True)
    clip = clip.set_mask(mask_clip)

    return clip


# ---------------------------------------------------------------------------
# High-Level Text Clip Factories (replace old TextClip-based functions)
# ---------------------------------------------------------------------------

def create_text_clip(
    arabic_text: str,
    duration: float,
    style: StyleConfig = DEFAULT_STYLE,
) -> VideoClip:
    """Create a text overlay clip for Arabic Quran text (static, full ayah)."""
    words = arabic_text.split()
    word_count = len(words)
    font_size, words_per_line = get_font_settings(word_count)

    return create_pil_text_clip(
        arabic_text,
        duration=duration,
        font_size=font_size,
        color=style.font_color,
        words_per_line=words_per_line,
        y_position=None,  # centered
        is_arabic=True,
        style=style,
    )


def create_translation_clip(
    translation_text: str,
    duration: float,
    style: StyleConfig = DEFAULT_STYLE,
) -> Optional[VideoClip]:
    """Create a translation overlay positioned below center."""
    if not translation_text:
        return None

    # Wrap long translations into 2 lines
    words = translation_text.split()
    if len(words) > 12:
        mid = len(words) // 2
        translation_text = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
        wpl = max(6, mid)
    else:
        wpl = len(words)  # single line

    return create_pil_text_clip(
        translation_text,
        duration=duration,
        font_size=style.translation_font_size,
        color=style.translation_color,
        words_per_line=wpl,
        y_position=style.translation_y_ratio,
        is_arabic=False,
        style=style,
    )


def create_ayah_number_clip(
    ayah_num: int,
    duration: float,
    style: StyleConfig = DEFAULT_STYLE,
) -> Optional[VideoClip]:
    """Create an ornamental ayah number display (gold, top-right area)."""
    ayah_text = f"﴿ {ayah_num} ﴾"

    renderer = _get_renderer(style)
    rgba = renderer.render_text(
        ayah_text,
        font_size=style.ayah_number_font_size,
        color=style.ayah_number_color,
        max_width=300,
        words_per_line=10,
        is_arabic=True,
    )

    # Position at top-right
    th, tw = rgba.shape[:2]
    canvas = np.zeros(
        (style.video_height, style.video_width, 4), dtype=np.uint8
    )
    x_off = style.video_width - tw - 40
    y_off = 80
    x_off = max(0, x_off)
    paste_w = min(tw, style.video_width - x_off)
    paste_h = min(th, style.video_height - y_off)
    canvas[y_off : y_off + paste_h, x_off : x_off + paste_w] = rgba[
        :paste_h, :paste_w
    ]

    rgb = canvas[:, :, :3]
    alpha = canvas[:, :, 3].astype(np.float32) / 255.0

    def make_frame(t):
        return rgb

    clip = VideoClip(make_frame, duration=duration)

    def make_mask(t):
        return alpha

    mask_clip = VideoClip(make_mask, duration=duration, ismask=True)
    clip = clip.set_mask(mask_clip)
    return clip


def create_surah_label(
    surah_name: str,
    duration: float,
    style: StyleConfig = DEFAULT_STYLE,
) -> Optional[VideoClip]:
    """Create a persistent surah label as a centered pill at the bottom."""
    label_text = _clean_arabic(f"سورة {surah_name}")

    font = _load_font(style.font_path, style.surah_label_font_size)
    text_color = _hex_to_rgb("white")

    # Build text kwargs for Arabic
    text_kwargs: Dict[str, Any] = {}
    renderer = _get_renderer(style)
    if renderer._has_raqm:
        text_kwargs["direction"] = "rtl"
        text_kwargs["language"] = "ar"
    elif _HAS_BIDI:
        label_text = get_display(_reshaper.reshape(label_text))

    # Measure text (no stroke on label)
    label_stroke = 1
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = dummy.textbbox(
        (0, 0), label_text, font=font, stroke_width=label_stroke, **text_kwargs,
    )
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Pill dimensions
    pad_x, pad_y = 40, 16
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    corner_radius = pill_h // 2

    # Build canvas
    canvas = Image.new(
        "RGBA", (style.video_width, style.video_height), (0, 0, 0, 0)
    )
    draw = ImageDraw.Draw(canvas)

    # Position pill at bottom-center with 30px margin
    margin_bottom = 30
    pill_x = (style.video_width - pill_w) // 2
    pill_y = style.video_height - pill_h - margin_bottom

    # Draw rounded-rectangle pill background
    bg_alpha = int(255 * style.surah_label_bg_opacity)
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=corner_radius,
        fill=(0, 0, 0, bg_alpha),
    )

    # Draw text centered inside pill
    tx = pill_x + (pill_w - text_w) // 2
    ty = pill_y + (pill_h - text_h) // 2
    draw.text(
        (tx, ty), label_text, font=font,
        fill=text_color + (255,),
        stroke_width=label_stroke,
        stroke_fill=(0, 0, 0, 255),
        **text_kwargs,
    )

    canvas_np = np.array(canvas)
    rgb = canvas_np[:, :, :3]
    alpha_ch = canvas_np[:, :, 3].astype(np.float32) / 255.0

    def make_frame(t):
        return rgb

    clip = VideoClip(make_frame, duration=duration)

    def make_mask(t):
        return alpha_ch

    mask_clip = VideoClip(make_mask, duration=duration, ismask=True)
    clip = clip.set_mask(mask_clip)
    return clip


def create_intro_frame(
    surah_num: int,
    surah_name_ar: str,
    surah_name_en: str,
    verse_start: int,
    verse_end: int,
    duration: float = 3.0,
    style: StyleConfig = DEFAULT_STYLE,
) -> CompositeVideoClip:
    """Create an elegant intro frame (title card) for the reel."""
    bg = ColorClip(
        size=(style.video_width, style.video_height), color=(15, 15, 25)
    ).set_duration(duration)

    clips = [bg]

    try:
        # Bismillah (except Surah 9)
        if surah_num != 9:
            bismillah = create_pil_text_clip(
                "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
                duration=duration,
                font_size=style.intro_bismillah_size,
                color=style.intro_bismillah_color,
                words_per_line=10,
                y_position=0.25,
                is_arabic=True,
                style=style,
            )
            clips.append(bismillah.fadein(0.5).fadeout(0.5))

        # Surah name Arabic
        surah_ar = create_pil_text_clip(
            f"سورة {surah_name_ar}",
            duration=duration,
            font_size=style.intro_surah_ar_size,
            color="white",
            words_per_line=10,
            y_position=0.40,
            is_arabic=True,
            style=style,
        )
        clips.append(surah_ar.fadein(0.5).fadeout(0.5))

        # Surah name English
        surah_en = create_pil_text_clip(
            f"Surah {surah_name_en} ({surah_num})",
            duration=duration,
            font_size=style.intro_surah_en_size,
            color="#AAAAAA",
            words_per_line=20,
            y_position=0.52,
            is_arabic=False,
            style=style,
        )
        clips.append(surah_en.fadein(0.5).fadeout(0.5))

        # Verse range
        verses = create_pil_text_clip(
            f"Verses {verse_start} - {verse_end}",
            duration=duration,
            font_size=style.intro_verse_range_size,
            color="#888888",
            words_per_line=20,
            y_position=0.62,
            is_arabic=False,
            style=style,
        )
        clips.append(verses.fadein(0.5).fadeout(0.5))

        # Decorative gold line
        line = ColorClip(size=(300, 2), color=(212, 175, 55))
        line = (
            line.set_duration(duration)
            .set_position(("center", int(style.video_height * 0.70)))
        )
        clips.append(line.fadein(0.8).fadeout(0.5))

    except Exception as e:
        logger.warning(f"Could not create full intro frame: {e}")

    intro = CompositeVideoClip(
        clips, size=(style.video_width, style.video_height)
    )
    return intro.set_duration(duration)


# ---------------------------------------------------------------------------
# Accumulating Text with Paged Crossfade (PIL-based)
# ---------------------------------------------------------------------------

def create_accumulating_text_lines(
    segments: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    total_duration: float,
    style: StyleConfig = DEFAULT_STYLE,
) -> Optional[VideoClip]:
    """
    Create a video clip where Arabic words appear sequentially in pages
    with crossfade transitions between pages.

    Uses PIL rendering (cached) and a single make_frame callback.

    Args:
        segments: Timing segments [{'word_index': 1, 'start_ms': ..., 'end_ms': ...}]
        words: Word text list [{'position': 1, 'text': '...'}]
        total_duration: Total clip duration
        style: StyleConfig

    Returns:
        VideoClip with accumulating text, or None on failure
    """
    try:
        renderer = _get_renderer(style)
        sorted_segments = sorted(segments, key=lambda x: x["start_ms"])

        page_size = style.page_size
        page_font_size = style.page_font_size
        page_wpl = style.page_words_per_line
        crossfade_dur = style.page_crossfade_duration

        word_map = {w["position"]: w["text"] for w in words}

        # Pre-build all text states: list of (time_start, time_end, page_index, text_string)
        states: List[Tuple[float, float, int, str]] = []
        current_words: List[str] = []

        for i, seg in enumerate(sorted_segments):
            word_idx = seg["word_index"]
            text = word_map.get(word_idx, "")
            if not text:
                continue

            current_words.append(text)
            current_word_count = len(current_words)
            page_index = (current_word_count - 1) // page_size

            page_start_idx = page_index * page_size
            active_page_words = current_words[page_start_idx:]

            start_s = seg["start_ms"] / 1000.0
            if i < len(sorted_segments) - 1:
                end_s = sorted_segments[i + 1]["start_ms"] / 1000.0
            else:
                end_s = total_duration

            if end_s - start_s < 0.05:
                end_s = start_s + 0.05

            full_string = " ".join(active_page_words)

            states.append((start_s, end_s, page_index, full_string))

        if not states:
            full_text = " ".join([w.get("text", "") for w in words])
            return create_text_clip(full_text, total_duration, style)

        # Pre-render all unique text states
        rendered_frames: Dict[str, np.ndarray] = {}
        for _, _, _, text_str in states:
            if text_str not in rendered_frames:
                rgba = renderer.render_text(
                    text_str,
                    font_size=page_font_size,
                    color=style.font_color,
                    max_width=style.text_max_width,
                    words_per_line=page_wpl,
                    is_arabic=True,
                )
                rendered_frames[text_str] = _make_centered_frame(
                    rgba, style.video_width, style.video_height, y_position=None
                )

        # Also render an empty frame
        empty_frame = np.zeros(
            (style.video_height, style.video_width, 4), dtype=np.uint8
        )

        # Detect page transitions
        page_transitions: List[float] = []  # times where page changes
        for i in range(1, len(states)):
            if states[i][2] != states[i - 1][2]:
                page_transitions.append(states[i][0])

        def _get_state_at(t: float) -> np.ndarray:
            """Get the RGBA frame for time t."""
            # Find the active state
            result = empty_frame
            for start_s, end_s, _, text_str in states:
                if start_s <= t < end_s:
                    result = rendered_frames[text_str]
                    break
            else:
                # If past all states, use the last one
                if states and t >= states[-1][0]:
                    result = rendered_frames[states[-1][3]]
            return result

        def make_frame(t):
            frame_rgba = _get_state_at(t)

            # Check if we're in a crossfade window
            for trans_t in page_transitions:
                if trans_t - crossfade_dur / 2 <= t <= trans_t + crossfade_dur / 2:
                    # Find outgoing (just before transition) and incoming (at transition)
                    out_frame = empty_frame
                    in_frame = empty_frame

                    for start_s, end_s, pi, text_str in states:
                        if start_s <= trans_t - 0.01 < end_s:
                            out_frame = rendered_frames[text_str]
                        if start_s <= trans_t + 0.01 < end_s:
                            in_frame = rendered_frames[text_str]

                    # Compute blend factor
                    blend = (t - (trans_t - crossfade_dur / 2)) / crossfade_dur
                    blend = max(0.0, min(1.0, blend))

                    # Alpha blend
                    blended = (
                        out_frame.astype(np.float32) * (1 - blend)
                        + in_frame.astype(np.float32) * blend
                    ).astype(np.uint8)
                    return blended[:, :, :3]

            return frame_rgba[:, :, :3]

        clip = VideoClip(make_frame, duration=total_duration)

        # Mask
        def make_mask(t):
            frame_rgba = _get_state_at(t)

            for trans_t in page_transitions:
                if trans_t - crossfade_dur / 2 <= t <= trans_t + crossfade_dur / 2:
                    out_frame = empty_frame
                    in_frame = empty_frame
                    for start_s, end_s, pi, text_str in states:
                        if start_s <= trans_t - 0.01 < end_s:
                            out_frame = rendered_frames[text_str]
                        if start_s <= trans_t + 0.01 < end_s:
                            in_frame = rendered_frames[text_str]

                    blend = (t - (trans_t - crossfade_dur / 2)) / crossfade_dur
                    blend = max(0.0, min(1.0, blend))

                    blended_alpha = (
                        out_frame[:, :, 3].astype(np.float32) * (1 - blend)
                        + in_frame[:, :, 3].astype(np.float32) * blend
                    )
                    return blended_alpha / 255.0

            return frame_rgba[:, :, 3].astype(np.float32) / 255.0

        mask_clip = VideoClip(make_mask, duration=total_duration, ismask=True)
        clip = clip.set_mask(mask_clip)

        return clip

    except Exception as e:
        logger.error(f"Failed to create accumulating text: {e}")
        try:
            full_text = " ".join([w.get("text", "") for w in words])
            return create_text_clip(full_text, total_duration, style)
        except Exception:
            return None
