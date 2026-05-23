"""
Longform Video Generator - Render complete 16:9 long-form Quran videos from scratch.

Uses the same audio sources (everyayah.com / Quran.com V4 API) and text rendering
as the Shorts pipeline, but outputs 16:9 format with cinematic B-roll background,
spanning an entire surah or surah group (8-60 minutes).

Pipeline per ayah segment:
1. Download recitation audio from everyayah.com
2. Fetch Arabic text + translation from Quran API
3. Render ayah segment via FFmpeg:
   - Cinematic B-roll background (looped, 1920x1080)
   - Arabic text overlay (centered)
   - Ayah number (top-right)
   - Reciter name (bottom-third pill)
   - Surah label (top-center)
4. Concatenate all segments with fade transitions
5. Output final MP4 with chapter metadata
"""
import os
import subprocess
import json
import shutil
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple

from loguru import logger
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from config.settings import (
    LONGFORM_WIDTH,
    LONGFORM_HEIGHT,
    LONGFORM_FPS,
    LONGFORM_TRANSITION_DEFAULT,
    LONGFORM_TEMP_DIR,
    LONGFORM_OUTPUT_DIR,
    LONGFORM_MAX_DURATION,
    DETECTED_ENCODER,
    NVENC_PARAMS,
    FONTS_DIR,
    AUDIO_DIR,
    VERSE_COUNTS,
    SURAH_NAMES_AR,
    SURAH_NAMES_EN,
    RECITERS,
    DEFAULT_RECITER,
    RECITER_MAPPING_V4,
    FONT_SIZE_CONFIG,
)
from core.ayah_fetcher import fetch_single_ayah
from core.audio_processor import get_audio_duration, cleanup_audio_files


# Font path for Arabic text overlay
FONT_PATH = FONTS_DIR / "amiri" / "Amiri-Bold.ttf"


def _get_audio_duration_pydub(audio_path: Path) -> float:
    """Duration function compatible with fetch_single_ayah's callback signature."""
    return get_audio_duration(audio_path)


def _ffprobe_duration(video_path: str) -> float:
    """Get video/audio duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"ffprobe error for {video_path}: {e}")
        return 0.0


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _escape_ffmpeg_path(path: str) -> str:
    """Escape path for FFmpeg drawtext on Windows."""
    return path.replace("\\", "/").replace(":", "\\:")


def _build_encoder_args() -> List[str]:
    """Build encoder-specific FFmpeg arguments."""
    args = ["-c:v", DETECTED_ENCODER]
    if DETECTED_ENCODER == "h264_nvenc":
        args.extend(NVENC_PARAMS)
    else:
        args.extend(["-crf", "20", "-preset", "medium"])
    return args


def to_arabic_digits(num: int) -> str:
    """Map Western digits to Eastern Arabic digits."""
    mapping = {'0':'٠','1':'١','2':'٢','3':'٣','4':'٤','5':'٥','6':'٦','7':'٧','8':'٨','9':'٩'}
    return "".join(mapping.get(c, c) for c in str(num))


def _clean_arabic(text: str) -> str:
    """Strip small Uthmani marks that may render incorrectly in some fonts."""
    # Uthmani-specific marks (U+06D6–U+06ED)
    import re
    uthmani_strip_re = re.compile("[\u06D6-\u06ED]")
    return uthmani_strip_re.sub("", text)


def _load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font with fallbacks."""
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)
    try:
        return ImageFont.truetype("Arial", size)
    except OSError:
        return ImageFont.load_default()


def _generate_text_overlay(
    width: int,
    height: int,
    arabic_text: str,
    ayah_num: int,
    surah_name_ar: str,
    reciter_name_ar: str,
    output_path: str,
) -> None:
    """
    Generate a transparent PNG overlay containing the Arabic verse,
    ayah number ornament, Surah title, and reciter name.
    """
    # 1. Initialize transparent image
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 2. Reshaper helper and native RTL detection
    from PIL import features
    has_raqm = features.check("raqm")
    
    # Define text rendering kwargs for Arabic text
    text_kwargs = {}
    if has_raqm:
        text_kwargs["direction"] = "rtl"
        text_kwargs["language"] = "ar"

    reshaper = arabic_reshaper.ArabicReshaper(configuration={
        'delete_harakat': False,
        'delete_tatweel': False,
    })

    def prepare_line(line: str) -> str:
        if has_raqm:
            return line
        reshaped = reshaper.reshape(line)
        return get_display(reshaped)

    # 3. Clean main text by stripping trailing brackets (e.g. ﴿٥﴾)
    cleaned_text = re.sub(r'\s*﴿[^﴾]*﴾\s*$', '', arabic_text)
    cleaned_text = _clean_arabic(cleaned_text).strip()

    words = cleaned_text.split()

    # 4. Helper function to wrap text dynamically using ImageDraw.textbbox
    def wrap_text(words: List[str], font: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
        lines = []
        current_line_words = []
        for word in words:
            test_line_words = current_line_words + [word]
            test_line = " ".join(test_line_words)
            disp = prepare_line(test_line)
            bbox = draw.textbbox((0, 0), disp, font=font, stroke_width=3, **text_kwargs)
            w = bbox[2] - bbox[0]
            if w <= max_w or not current_line_words:
                current_line_words = test_line_words
            else:
                lines.append(" ".join(current_line_words))
                current_line_words = [word]
        if current_line_words:
            lines.append(" ".join(current_line_words))
        return lines

    # 5. Iterative wrap and scale algorithm
    max_w = 1200
    max_h = 450
    max_lines = 4

    font_size = 72
    min_font_size = 36
    final_lines = []
    final_line_sizes = []
    font_ayah = None

    while font_size >= min_font_size:
        font_ayah = _load_font(FONT_PATH, font_size)
        wrapped_lines = wrap_text(words, font_ayah, max_w)
        
        line_sizes = []
        for line in wrapped_lines:
            disp = prepare_line(line)
            bbox = draw.textbbox((0, 0), disp, font=font_ayah, stroke_width=3, **text_kwargs)
            line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))
            
        total_text_h = sum(h for w, h in line_sizes) + int(font_size * 0.25) * (len(wrapped_lines) - 1)
        
        if total_text_h <= max_h and len(wrapped_lines) <= max_lines:
            final_lines = wrapped_lines
            final_line_sizes = line_sizes
            break
            
        if font_size == min_font_size:
            final_lines = wrapped_lines
            final_line_sizes = line_sizes
            break
            
        font_size -= 4

    # 6. Render main Arabic text lines (centered vertically and horizontally)
    total_text_h = sum(h for w, h in final_line_sizes) + int(font_size * 0.25) * (len(final_lines) - 1)
    y_cursor = (height - total_text_h) // 2

    for i, line in enumerate(final_lines):
        disp = prepare_line(line)
        line_w, line_h = final_line_sizes[i]
        x = (width - line_w) // 2

        draw.text(
            (x, y_cursor),
            disp,
            font=font_ayah,
            fill=(255, 255, 255, 255),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 178),
            **text_kwargs,
        )
        y_cursor += line_h + int(font_size * 0.25)

    # 7. Render Surah name at top-center
    font_surah = _load_font(FONT_PATH, 36)
    surah_text = prepare_line(_clean_arabic(f"سورة {surah_name_ar}"))
    bbox_surah = draw.textbbox((0, 0), surah_text, font=font_surah, stroke_width=2, **text_kwargs)
    sw = bbox_surah[2] - bbox_surah[0]
    draw.text(
        ((width - sw) // 2, 40),
        surah_text,
        font=font_surah,
        fill=(255, 255, 255, 230),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 128),
        **text_kwargs,
    )

    # 8. Render Ayah number at top-right
    font_num = _load_font(FONT_PATH, 44)
    ayah_num_str = f"﴿ {to_arabic_digits(ayah_num)} ﴾"
    num_text = prepare_line(ayah_num_str)
    bbox_num = draw.textbbox((0, 0), num_text, font=font_num, stroke_width=2, **text_kwargs)
    nw = bbox_num[2] - bbox_num[0]
    draw.text(
        (width - nw - 60, 60),
        num_text,
        font=font_num,
        fill=(212, 175, 55, 255),  # Gold
        stroke_width=2,
        stroke_fill=(0, 0, 0, 153),
        **text_kwargs,
    )

    # 9. Render Reciter name at bottom-third
    font_reciter = _load_font(FONT_PATH, 46)
    reciter_text = prepare_line(reciter_name_ar)
    bbox_rec = draw.textbbox((0, 0), reciter_text, font=font_reciter, stroke_width=3, **text_kwargs)
    rw = bbox_rec[2] - bbox_rec[0]
    draw.text(
        ((width - rw) // 2, height - 120),
        reciter_text,
        font=font_reciter,
        fill=(255, 255, 255, 255),
        stroke_width=3,
        stroke_fill=(0, 0, 0, 204),
        **text_kwargs,
    )

    # Save overlay image
    img.save(output_path)


def _render_ayah_segment(
    audio_path: str,
    arabic_text: str,
    ayah_num: int,
    surah_name_ar: str,
    reciter_name_ar: str,
    background_path: str,
    output_path: str,
    audio_duration: float,
    fade_in: float = 0.3,
    fade_out: float = 0.3,
    padding_after: float = 0.5,
    color_grade: Optional[Dict] = None,
    overlay_opacity: float = 0.35,
    ken_burns: Optional[Dict] = None,
) -> float:
    """
    Render a single ayah segment as a 16:9 video clip.

    Creates a video of duration = audio_duration + padding_after with:
    - Cinematic B-roll background (looped, zoomed/panned via Ken Burns)
    - Transparent PNG overlay with:
      - Arabic text wrapped and centered
      - Correctly oriented ornate bracket and ayah number (top-right)
      - Surah name (top-center)
      - Reciter name (bottom-third)

    Returns:
        Total segment duration (audio + padding).
    """
    total_duration = audio_duration + padding_after

    # Generate transparent PNG overlay
    text_dir = Path(output_path).parent
    overlay_png_path = str(text_dir / f"_overlay_{ayah_num}.png")

    _generate_text_overlay(
        width=LONGFORM_WIDTH,
        height=LONGFORM_HEIGHT,
        arabic_text=arabic_text,
        ayah_num=ayah_num,
        surah_name_ar=surah_name_ar,
        reciter_name_ar=reciter_name_ar,
        output_path=overlay_png_path,
    )

    # Color grading filter
    color_filter = ""
    if color_grade:
        rs = color_grade.get("rs", 0)
        gs = color_grade.get("gs", 0)
        bs = color_grade.get("bs", 0)
        color_filter = f",colorbalance=rs={rs}:gs={gs}:bs={bs}"

    # Ken Burns zoom/pan filter
    zoom_filter = ""
    if ken_burns:
        zoom_start = ken_burns.get("zoom_start", 1.0)
        zoom_end = ken_burns.get("zoom_end", 1.05)
        pan_x = ken_burns.get("pan_x", "center")
        pan_y = ken_burns.get("pan_y", "center")
        total_frames = int(total_duration * LONGFORM_FPS)
        
        # Interpolation expression for zoom
        z_expr = f"{zoom_start}+({zoom_end}-{zoom_start})*(on/{total_frames})"
        
        if pan_x == "left":
            x_expr = "0"
        elif pan_x == "right":
            x_expr = "iw-iw/zoom"
        else:
            x_expr = "(iw-iw/zoom)/2"
            
        if pan_y == "up":
            y_expr = "0"
        elif pan_y == "down":
            y_expr = "ih-ih/zoom"
        else:
            y_expr = "(ih-ih/zoom)/2"
            
        zoom_filter = f",zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s=1920x1080:fps={LONGFORM_FPS}"

    # Build filter complex
    filter_complex = (
        # Background: scale to cover 1920x1080, crop center, apply color grade and zoompan
        f"[0:v]scale=1920:-1,crop=1920:1080:(in_w-1920)/2:(in_h-1080)/2{color_filter}{zoom_filter}[bg_raw]; "
        # Dark overlay
        f"color=black@{overlay_opacity}:s=1920x1080:d={total_duration}[dark]; "
        f"[bg_raw][dark]overlay=0:0[bg]; "
        # Overlay the transparent PNG text overlay (input 2)
        f"[bg][2:v]overlay=0:0[v_raw]; "
        # Audio fade in/out on the video stream (gentle)
        f"[v_raw]fade=t=in:st=0:d={fade_in},"
        f"fade=t=out:st={total_duration - fade_out}:d={fade_out}[v]; "
        # Audio: pad silence for padding_after, then fade
        f"[1:a]apad=pad_dur={padding_after},"
        f"afade=t=in:st=0:d={min(fade_in, 0.1)},"
        f"afade=t=out:st={audio_duration - 0.1}:d={min(fade_out, 0.2)}[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        # Input 0: background B-roll (looped)
        "-stream_loop", "-1", "-i", background_path,
        # Input 1: ayah audio
        "-i", audio_path,
        # Input 2: transparent text overlay PNG
        "-i", overlay_png_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        *_build_encoder_args(),
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-r", str(LONGFORM_FPS),
        "-ar", "44100", "-ac", "2",
        "-t", str(total_duration),
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup temp overlay PNG
    try:
        os.remove(overlay_png_path)
    except Exception:
        pass

    if result.returncode != 0:
        logger.error(f"FFmpeg segment render error:\n{result.stderr[-3000:]}")
        raise RuntimeError(f"FFmpeg failed rendering ayah {ayah_num}")

    return total_duration



def generate_longform(
    surah_start: int,
    surah_end: int,
    reciter_key: str = DEFAULT_RECITER,
    background_path: Optional[str] = None,
    output_filename: Optional[str] = None,
    compilation_styles: Optional[List[Dict]] = None,
    ayah_padding: float = 0.6,
    transition_duration: float = LONGFORM_TRANSITION_DEFAULT,
    progress_callback: Optional[Callable] = None,
    ayah_start: Optional[int] = None,
    ayah_end: Optional[int] = None,
    loop_count: int = 1,
) -> Dict[str, Any]:
    """
    Generate a complete long-form 16:9 Quran video from scratch.

    Fetches audio from everyayah.com, renders Arabic text overlays on a
    cinematic B-roll background, and concatenates all ayahs into a single
    video with chapter timestamps.

    Args:
        surah_start: First surah number (1-114)
        surah_end: Last surah number (inclusive)
        reciter_key: Key from RECITERS dict
        background_path: Path to cinematic B-roll video
        output_filename: Output filename (auto-generated if None)
        compilation_styles: Per-segment visual styles
        ayah_padding: Silence gap between ayahs (seconds)
        transition_duration: Fade duration between surah sections
        progress_callback: fn(current_ayah, total_ayahs, message)
        ayah_start: Optional starting ayah (1-based, only for single-surah compilation)
        ayah_end: Optional ending ayah (inclusive, only for single-surah compilation)

    Returns:
        Dict with output_path, duration, chapters, description, title, etc.
    """
    # Validate
    for s in range(surah_start, surah_end + 1):
        if s not in VERSE_COUNTS:
            raise ValueError(f"Invalid surah number: {s}")

    reciter_info = RECITERS.get(reciter_key, {})
    reciter_name_ar = reciter_info.get("name_ar", reciter_key)
    reciter_name_en = reciter_info.get("name_en", reciter_key)

    # Calculate total ayahs for progress
    if surah_start == surah_end and (ayah_start is not None or ayah_end is not None):
        start_a = ayah_start or 1
        end_a = ayah_end or VERSE_COUNTS[surah_start]
        total_ayahs = max(0, end_a - start_a + 1)
    else:
        total_ayahs = sum(VERSE_COUNTS[s] for s in range(surah_start, surah_end + 1))

    logger.info(
        f"Generating long-form video: Surahs {surah_start}-{surah_end} "
        f"({total_ayahs} ayahs) with reciter {reciter_name_ar}"
    )
    logger.info(f"Encoder: {DETECTED_ENCODER}")

    # Prepare temp directory
    shutil.rmtree(str(LONGFORM_TEMP_DIR), ignore_errors=True)
    LONGFORM_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Audio temp directory
    audio_temp = LONGFORM_TEMP_DIR / "audio"
    audio_temp.mkdir(exist_ok=True)

    # If no background provided, try to get one
    if not background_path:
        try:
            from longform.background_renderer import get_cinematic_background
            bg = get_cinematic_background(min_duration=30)
            if bg:
                background_path = str(bg)
                logger.info(f"Using cinematic background: {bg.name}")
        except Exception as e:
            logger.warning(f"Could not get cinematic background: {e}")

    if not background_path:
        raise RuntimeError(
            "No background video available. Please add a video to "
            "outputs/longform/backgrounds/ or set PEXELS_API_KEY."
        )

    # Process all ayahs
    processed_segments = []
    rendered_info = []  # list of (surah_num, seg_duration)
    accumulated_time = 0.0
    current_ayah_idx = 0
    style_idx = 0

    for surah_num in range(surah_start, surah_end + 1):
        surah_name_ar = SURAH_NAMES_AR[surah_num - 1]
        surah_name_en = SURAH_NAMES_EN[surah_num - 1]
        
        # Calculate start and end ayah for this surah
        if surah_num == surah_start and ayah_start is not None:
            start_a = ayah_start
        else:
            start_a = 1
            
        if surah_num == surah_end and ayah_end is not None:
            end_a = ayah_end
        else:
            end_a = VERSE_COUNTS[surah_num]

        logger.info(f"=== Surah {surah_num}: {surah_name_ar} (Ayahs {start_a}-{end_a}) ===")

        for ayah_num in range(start_a, end_a + 1):
            current_ayah_idx += 1

            if progress_callback:
                progress_callback(
                    current_ayah_idx, total_ayahs,
                    f"Rendering {surah_name_ar} ayah {ayah_num}/{end_a}"
                )

            # Fetch audio + text for this ayah
            try:
                ayah_data = fetch_single_ayah(
                    surah=surah_num,
                    ayah=ayah_num,
                    reciter_key=reciter_key,
                    audio_dir=audio_temp,
                    get_duration_fn=_get_audio_duration_pydub,
                    current_time=0,  # relative time within segment
                    ayah_padding=0,  # we handle padding ourselves
                )
            except Exception as e:
                logger.error(f"Failed to fetch ayah {surah_num}:{ayah_num}: {e}")
                continue

            # Get segment style
            style = {}
            if compilation_styles and style_idx < len(compilation_styles):
                style = compilation_styles[style_idx]
            style_idx += 1

            # Determine fade durations
            is_first_ayah = (current_ayah_idx == 1)
            is_last_ayah = (current_ayah_idx == total_ayahs)
            is_surah_start = (ayah_num == start_a)
            is_surah_end = (ayah_num == end_a)

            fade_in = transition_duration if (is_first_ayah or is_surah_start) else 0.15
            fade_out = transition_duration if (is_last_ayah or is_surah_end) else 0.15
            seg_padding = 1.5 if is_surah_end else ayah_padding

            # Render segment
            seg_output = LONGFORM_TEMP_DIR / f"seg_{current_ayah_idx:05d}.mp4"

            try:
                seg_duration = _render_ayah_segment(
                    audio_path=str(ayah_data["audio_path"]),
                    arabic_text=ayah_data["text"],
                    ayah_num=ayah_num,
                    surah_name_ar=surah_name_ar,
                    reciter_name_ar=reciter_name_ar,
                    background_path=background_path,
                    output_path=str(seg_output),
                    audio_duration=ayah_data["audio_duration"],
                    fade_in=fade_in,
                    fade_out=fade_out,
                    padding_after=seg_padding,
                    color_grade=style.get("color_grade"),
                    overlay_opacity=style.get("overlay_opacity", 0.35),
                    ken_burns=style.get("ken_burns"),
                )

                processed_segments.append(str(seg_output))
                rendered_info.append((surah_num, seg_duration))
                accumulated_time += seg_duration

                logger.debug(
                    f"  Ayah {ayah_num}: {ayah_data['audio_duration']:.1f}s audio, "
                    f"{seg_duration:.1f}s segment (total: {accumulated_time:.0f}s)"
                )

            except Exception as e:
                logger.error(f"Failed to render ayah {surah_num}:{ayah_num}: {e}")
                continue

            # Safety: check if we're hitting the max duration
            if accumulated_time > LONGFORM_MAX_DURATION:
                logger.warning(
                    f"Reached max duration ({LONGFORM_MAX_DURATION}s). "
                    f"Stopping at {surah_num}:{ayah_num}."
                )
                break

        if accumulated_time > LONGFORM_MAX_DURATION:
            break

    if not processed_segments:
        raise RuntimeError("No segments were rendered successfully")

    # Build chapters and compute final accumulated time based on loop_count
    chapters = []
    accumulated_time = 0.0
    for r in range(1, loop_count + 1):
        added_surahs = set()
        for surah_num, seg_duration in rendered_info:
            if surah_num not in added_surahs:
                added_surahs.add(surah_num)
                surah_name_ar = SURAH_NAMES_AR[surah_num - 1]
                surah_name_en = SURAH_NAMES_EN[surah_num - 1]
                
                # Determine start/end ayahs for this surah
                if surah_num == surah_start and ayah_start is not None:
                    start_a = ayah_start
                else:
                    start_a = 1
                if surah_num == surah_end and ayah_end is not None:
                    end_a = ayah_end
                else:
                    end_a = VERSE_COUNTS[surah_num]
                    
                suffix = f" (Repetition {r})" if loop_count > 1 else ""
                if surah_start == surah_end and (ayah_start is not None or ayah_end is not None):
                    chapter_title = f"سورة {surah_name_ar} (الآيات {start_a}-{end_a}){suffix} - {surah_name_en} (Ayahs {start_a}-{end_a}) ({reciter_name_ar})"
                else:
                    chapter_title = f"سورة {surah_name_ar}{suffix} - {surah_name_en} ({reciter_name_ar})"
                    
                chapters.append({
                    "timestamp": format_timestamp(accumulated_time),
                    "seconds": accumulated_time,
                    "title": chapter_title,
                })
            accumulated_time += seg_duration

    # Concatenate all segments
    logger.info(f"Concatenating {len(processed_segments) * loop_count} segments (looped {loop_count} times)...")

    if progress_callback:
        progress_callback(total_ayahs, total_ayahs, "Concatenating final video...")

    concat_file = LONGFORM_TEMP_DIR / "concat_list.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for _ in range(loop_count):
            for path in processed_segments:
                escaped = path.replace("\\", "/")
                f.write(f"file '{escaped}'\n")

    # Generate output filename
    if output_filename is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        loop_str = f"_loop{loop_count}" if loop_count > 1 else ""
        if surah_start == surah_end:
            name_en = SURAH_NAMES_EN[surah_start - 1]
            start_a = ayah_start or 1
            end_a = ayah_end or VERSE_COUNTS[surah_start]
            if start_a == 1 and end_a == VERSE_COUNTS[surah_start]:
                output_filename = f"Longform_{surah_start}_{name_en}{loop_str}_{reciter_key}_{ts}.mp4"
            else:
                output_filename = f"Longform_{surah_start}_{name_en}_{start_a}-{end_a}{loop_str}_{reciter_key}_{ts}.mp4"
        else:
            output_filename = f"Longform_{surah_start}-{surah_end}{loop_str}_{reciter_key}_{ts}.mp4"

    final_output = LONGFORM_OUTPUT_DIR / output_filename

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_output),
    ]

    result = subprocess.run(concat_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg concat error:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"FFmpeg concat failed (exit code {result.returncode})")

    # Build metadata
    description = _build_description(
        surah_start, surah_end, reciter_name_ar, reciter_name_en,
        chapters, accumulated_time, ayah_start, ayah_end
    )

    title_suffix = f" | Repeated {loop_count}x" if loop_count > 1 else ""
    if surah_start == surah_end:
        name_ar = SURAH_NAMES_AR[surah_start - 1]
        name_en = SURAH_NAMES_EN[surah_start - 1]
        start_a = ayah_start or 1
        end_a = ayah_end or VERSE_COUNTS[surah_start]
        is_full = (start_a == 1 and end_a == VERSE_COUNTS[surah_start])
        if is_full:
            recommended_title = (
                f"سورة {name_ar} كاملة{title_suffix} | {name_en} Full | "
                f"{reciter_name_ar} | Beautiful Quran Recitation"
            )
        else:
            recommended_title = (
                f"سورة {name_ar} (الآيات {start_a}-{end_a}){title_suffix} | Surah {name_en} (Ayahs {start_a}-{end_a}) | "
                f"{reciter_name_ar} | Beautiful Quran Recitation"
            )
    else:
        start_ar = SURAH_NAMES_AR[surah_start - 1]
        end_ar = SURAH_NAMES_AR[surah_end - 1]
        start_en = SURAH_NAMES_EN[surah_start - 1]
        end_en = SURAH_NAMES_EN[surah_end - 1]
        recommended_title = (
            f"سورة {start_ar} إلى سورة {end_ar}{title_suffix} | "
            f"{start_en} to {end_en} | {reciter_name_ar} | Beautiful Quran Recitation"
        )

    metadata = {
        "output_path": str(final_output),
        "surah_start": surah_start,
        "surah_end": surah_end,
        "ayah_start": ayah_start,
        "ayah_end": ayah_end,
        "reciter_key": reciter_key,
        "reciter_name_ar": reciter_name_ar,
        "num_segments": len(processed_segments) * loop_count,
        "duration_seconds": int(accumulated_time),
        "duration_formatted": format_timestamp(accumulated_time),
        "chapters": chapters,
        "description": description,
        "recommended_title": recommended_title,
        "tags": _build_tags(surah_start, surah_end, reciter_name_ar, reciter_name_en),
    }

    # Save metadata JSON
    meta_path = str(final_output) + ".json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Cleanup temp files (keep audio cache for potential re-renders)
    for seg in processed_segments:
        try:
            os.remove(seg)
        except Exception:
            pass
    try:
        os.remove(str(concat_file))
    except Exception:
        pass

    logger.success(
        f"✅ Long-form video complete: {final_output.name} "
        f"({format_timestamp(accumulated_time)}, {len(processed_segments)} ayahs)"
    )

    return metadata


def _build_description(
    surah_start: int,
    surah_end: int,
    reciter_ar: str,
    reciter_en: str,
    chapters: List[Dict],
    total_duration: float,
    ayah_start: Optional[int] = None,
    ayah_end: Optional[int] = None,
) -> str:
    """Build SEO-optimized YouTube description."""
    if surah_start == surah_end:
        name_ar = SURAH_NAMES_AR[surah_start - 1]
        name_en = SURAH_NAMES_EN[surah_start - 1]
        start_a = ayah_start or 1
        end_a = ayah_end or VERSE_COUNTS[surah_start]
        is_full = (start_a == 1 and end_a == VERSE_COUNTS[surah_start])
        if is_full:
            header = f"📖 سورة {name_ar} كاملة - {name_en} Full Recitation"
        else:
            header = f"📖 سورة {name_ar} (الآيات {start_a}-{end_a}) - {name_en} (Ayahs {start_a}-{end_a}) Recitation"
    else:
        start_ar = SURAH_NAMES_AR[surah_start - 1]
        end_ar = SURAH_NAMES_AR[surah_end - 1]
        header = f"📖 سورة {start_ar} إلى سورة {end_ar} - Beautiful Quran Recitations"

    lines = [
        header,
        f"🎙️ Reciter: {reciter_ar} ({reciter_en})",
        f"⏱️ Duration: {format_timestamp(total_duration)}",
        "",
        "═══════════════════════════════",
        "📌 Timestamps / Chapters:",
        "═══════════════════════════════",
    ]

    for ch in chapters:
        lines.append(f"{ch['timestamp']} {ch['title']}")

    lines.extend([
        "",
        "═══════════════════════════════",
        "",
        "#Quran #القرآن_الكريم #QuranRecitation #تلاوة_القرآن #Islam",
        "#تلاوة_خاشعة #قرآن_كريم #QuranFull #QuranListening #Islamic",
        f"#{reciter_en.replace(' ', '')} #QuranBeautiful",
        "",
        "📌 Subscribe for daily Quran Shorts and weekly full-surah recitations!",
        "",
        "⚠️ For educational and spiritual purposes.",
        "All recitations belong to their respective reciters.",
    ])

    return "\n".join(lines)


def _build_tags(
    surah_start: int,
    surah_end: int,
    reciter_ar: str,
    reciter_en: str,
) -> List[str]:
    """Build YouTube tags list."""
    tags = [
        "Quran", "القرآن الكريم", "Islam", "إسلام",
        "Quran Recitation", "تلاوة القرآن",
        "Quran Full", "تلاوة كاملة",
        reciter_ar, reciter_en,
        "Islamic", "QuranListening",
        "تلاوة خاشعة", "قرآن كريم",
    ]

    for s in range(surah_start, min(surah_end + 1, surah_start + 5)):
        tags.append(f"Surah {SURAH_NAMES_EN[s - 1]}")
        tags.append(f"سورة {SURAH_NAMES_AR[s - 1]}")

    return tags
