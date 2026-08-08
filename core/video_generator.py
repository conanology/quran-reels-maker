"""
Video Generator - Create Quran reel videos using MoviePy

Slim orchestrator that delegates to:
  - core.style_config   : visual constants
  - core.text_renderer  : PIL text rendering with stroke/shadow/crossfade
  - core.ayah_fetcher   : ayah data + heuristic segmentation
  - core.background     : background loading, Ken Burns, color grading
"""
import os
import datetime
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger

# PIL compatibility fix for Pillow 10+ (ANTIALIAS was renamed to LANCZOS)
from PIL import Image
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

# Configure ImageMagick for MoviePy (required for TextClip on Windows)
IMAGEMAGICK_BINARY = os.getenv(
    "IMAGEMAGICK_BINARY",
    r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
)
if os.path.exists(IMAGEMAGICK_BINARY):
    os.environ["IMAGEMAGICK_BINARY"] = IMAGEMAGICK_BINARY
    import moviepy.config as mpy_conf
    mpy_conf.IMAGEMAGICK_BINARY = IMAGEMAGICK_BINARY

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
    ColorClip,
)

from config.settings import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    VIDEO_CODEC,
    AUDIO_CODEC,
    AUDIO_BITRATE,
    VIDEOS_DIR,
    AUDIO_DIR,
    RECITERS,
    DEFAULT_RECITER,
)
from core.quran_api import get_surah_name, validate_verse_range
from core.audio_processor import cleanup_audio_files
from core.style_config import StyleConfig, DEFAULT_STYLE
from core.background import (
    BackgroundError,
    pick_random_background,
    load_and_grade_background,
)
from core.word_timings import WordTimingError, get_word_timings

# Intermediate per-word frames. Sits under the videos dir so the workflow's
# existing render cleanup removes them.
KARAOKE_DIR = VIDEOS_DIR / "karaoke"
from core.ayah_fetcher import fetch_single_ayah
from core.text_renderer import (
    create_text_clip,
    create_translation_clip,
    create_ayah_number_clip,
    create_surah_label,
    create_intro_frame,
    create_accumulating_text_lines,
    compute_page_boundaries,
    split_translation_by_pages,
)


def download_ai_background(translation: str) -> Optional[Path]:
    """Generate and download a themed AI background image from Pollinations.ai."""
    import time
    import requests
    import urllib.parse
    from core.ai_brain import generate_visual_prompt
    
    # 1. Generate prompt from translation
    visual_prompt = generate_visual_prompt(translation)
    if not visual_prompt:
        logger.warning("Could not generate visual prompt from AI brain. Falling back.")
        return None
        
    # 2. Format URL
    encoded_prompt = urllib.parse.quote(visual_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&model=flux&nologo=true"
    
    from config.settings import ASSETS_DIR
    download_dir = ASSETS_DIR / "downloaded_bg"
    download_dir.mkdir(parents=True, exist_ok=True)
    output_path = download_dir / f"ai_bg_{int(time.time())}.jpg"
    
    logger.info(f"Downloading themed AI background from Pollinations: {output_path.name}")
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            return output_path
        else:
            logger.error(f"Pollinations API error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Failed to download AI background: {e}")
        return None


class VideoGeneratorError(Exception):
    """Custom exception for video generation errors"""
    pass


def get_audio_duration_moviepy(audio_path: Path) -> float:
    """
    Get audio duration using MoviePy's AudioFileClip.
    Ensures same library for duration measurement and composition.
    """
    try:
        with AudioFileClip(str(audio_path)) as clip:
            return clip.duration
    except Exception as e:
        logger.error(f"Could not get duration for {audio_path}: {e}")
        return 5.0


def _build_karaoke_clips(timing, display_duration, style, output_dir, prefix):
    """
    One clip per recited word, each holding until the next word begins.

    Scheduling on the next word's start rather than this word's end avoids the
    gaps that would otherwise appear between words, where no text would show.
    """
    from moviepy.editor import ImageClip

    from core.karaoke_renderer import KaraokeStyle, render_word_states

    karaoke_style = KaraokeStyle(
        font_path=Path(style.font_path),
        font_size=style.page_font_size,
        width=style.video_width,
        height=style.video_height,
    )
    paths = render_word_states(timing.words, output_dir, karaoke_style, prefix=prefix)
    spans = timing.spans_seconds()

    clips = []
    for index, (path, (start, _end)) in enumerate(zip(paths, spans)):
        if start >= display_duration:
            break
        next_start = (
            spans[index + 1][0] if index + 1 < len(spans) else display_duration
        )
        duration = min(next_start, display_duration) - start
        if duration <= 0:
            continue
        clips.append(ImageClip(str(path)).set_duration(duration).set_start(start))

    return clips


def generate_reel(
    surah: int,
    start_ayah: int,
    end_ayah: int,
    reciter_key: str = DEFAULT_RECITER,
    output_path: Optional[Path] = None,
    style: StyleConfig = DEFAULT_STYLE,
) -> Tuple[Path, int, int]:
    """
    Generate a complete Quran reel video with continuous background.

    Args:
        surah: Surah number (1-114)
        start_ayah: Starting ayah number
        end_ayah: Ending ayah number (inclusive)
        reciter_key: Key from RECITERS dict
        output_path: Optional custom output path
        style: Visual style configuration

    Returns:
        Tuple of (video_path, actual_start_ayah, actual_end_ayah)
    """
    from config.settings import MIN_REEL_DURATION_SECONDS, MAX_REEL_DURATION_SECONDS, VERSE_COUNTS

    # Validate
    start_ayah, end_ayah = validate_verse_range(surah, start_ayah, end_ayah)

    surah_name = get_surah_name(surah, "ar")
    surah_name_en = get_surah_name(surah, "en")
    reciter_name = RECITERS.get(reciter_key, {}).get("name_ar", reciter_key)

    logger.info(f"Generating reel: Surah {surah_name} ({surah}), verses {start_ayah}-{end_ayah}")
    logger.info(f"Reciter: {reciter_name}")

    # Feature flags
    ENABLE_INTRO_FRAME = os.getenv("ENABLE_INTRO_FRAME", "false").lower() == "true"
    ENABLE_KEN_BURNS = os.getenv("ENABLE_KEN_BURNS", "true").lower() == "true"
    INTRO_DURATION = 3.0

    # Reserve time for intro frame if enabled
    max_content_duration = MAX_REEL_DURATION_SECONDS - (INTRO_DURATION if ENABLE_INTRO_FRAME else 0)

    cleanup_audio_files(AUDIO_DIR)

    # === STEP 1: Download audio and calculate timings ===
    ayah_data = []
    current_time = 0.1
    current_ayah = start_ayah
    max_ayah = VERSE_COUNTS.get(surah, end_ayah)

    # Fetch requested ayahs (stop early if we'd exceed max duration)
    while current_ayah <= end_ayah:
        data = fetch_single_ayah(
            surah, current_ayah, reciter_key, AUDIO_DIR,
            get_audio_duration_moviepy, current_time, style.ayah_padding,
        )
        projected_duration = data["segment_end"] + 0.5
        # Stop adding ayahs if this one would push us over the max
        if ayah_data and projected_duration > max_content_duration:
            logger.warning(
                f"Ayah {current_ayah} would push duration to {projected_duration:.1f}s "
                f"(max {max_content_duration:.0f}s). Stopping at ayah {current_ayah - 1}."
            )
            break
        ayah_data.append(data)
        logger.debug(
            f"Ayah {current_ayah}: start={current_time:.2f}s, "
            f"duration={data['audio_duration']:.2f}s"
        )
        current_time = data["segment_end"]
        current_ayah += 1

    total_duration = current_time + 0.5
    end_ayah = ayah_data[-1]["ayah"]

    # === STEP 2: Extend if below minimum duration (but never exceed max) ===
    while (total_duration < MIN_REEL_DURATION_SECONDS
           and current_ayah <= max_ayah
           and total_duration < max_content_duration):
        data = fetch_single_ayah(
            surah, current_ayah, reciter_key, AUDIO_DIR,
            get_audio_duration_moviepy, current_time, style.ayah_padding,
        )
        projected_duration = data["segment_end"] + 0.5
        # Don't add this ayah if it would exceed max duration
        if projected_duration > max_content_duration:
            logger.info(
                f"Skipping ayah {current_ayah}: would push to {projected_duration:.1f}s "
                f"(max {max_content_duration:.0f}s)"
            )
            break
        logger.info(
            f"Duration {total_duration:.1f}s < {MIN_REEL_DURATION_SECONDS}s, "
            f"adding ayah {current_ayah}..."
        )
        ayah_data.append(data)
        logger.debug(
            f"Ayah {current_ayah} (extended): start={current_time:.2f}s, "
            f"duration={data['audio_duration']:.2f}s"
        )
        current_time = data["segment_end"]
        total_duration = current_time + 0.5
        current_ayah += 1
        end_ayah = current_ayah - 1

    # Hard-cap total duration to max (safety net)
    if total_duration > max_content_duration:
        logger.warning(
            f"Capping duration from {total_duration:.1f}s to {max_content_duration:.0f}s"
        )
        total_duration = max_content_duration

    logger.info(f"Final verses: {start_ayah}-{end_ayah} ({len(ayah_data)} ayahs)")
    logger.info(f"Total video duration: {total_duration:.1f}s")

    # === STEP 3: Background ===
    full_translation = " ".join(item.get("translation", "") for item in ayah_data).strip()
    background_path = None
    
    # Real footage first. The Pollinations endpoint ignores the requested model
    # and size: it serves a 576x1024 SANA still that we then upscale 1.88x, which
    # is what produces the duplicated suns, mirrored horizons and plastic texture.
    from core.stock_footage import get_dynamic_background

    background_path = get_dynamic_background()
    if background_path:
        logger.info(f"Using dynamic background from Pexels: {background_path.name}")

    if not background_path:
        # Raises BackgroundError when the local folder is empty, which is normal
        # on a CI runner, so keep going to the generated fallback.
        try:
            background_path = pick_random_background()
            logger.info(f"Using local background: {background_path.name}")
        except Exception as e:
            logger.debug(f"No local background available: {e}")

    if not background_path and full_translation:
        try:
            background_path = download_ai_background(full_translation)
            if background_path:
                logger.warning(
                    f"Falling back to generated background: {background_path.name}"
                )
        except Exception as e:
            logger.error(f"Error during AI background generation: {e}")

    if not background_path:
        raise BackgroundError("No background available from Pexels, local, or fallback")

    bg_with_grading = load_and_grade_background(
        background_path, total_duration, style, enable_ken_burns=ENABLE_KEN_BURNS,
    )

    # === STEP 4: Text overlays ===
    text_clips = []

    for data in ayah_data:
        display_duration = data["end_time"] - data["start_time"]

        # Arabic text: highlight each word as it is recited when real per-word
        # timings exist, otherwise show the whole ayah for its duration.
        timing = None
        try:
            timing = get_word_timings(reciter_key, surah, data["ayah"])
        except WordTimingError as e:
            logger.warning(f"No usable word timings for ayah {data['ayah']}: {e}")

        karaoke_clips = []
        if timing:
            karaoke_clips = _build_karaoke_clips(
                timing,
                display_duration,
                style,
                KARAOKE_DIR,
                prefix=f"{surah}_{data['ayah']}",
            )

        if karaoke_clips:
            logger.info(
                f"Word-synced text for ayah {data['ayah']}: {len(karaoke_clips)} words"
            )
            for clip in karaoke_clips:
                clip = clip.set_start(data["start_time"] + clip.start)
                text_clips.append(clip)
        else:
            text_clip = create_text_clip(data["text"], display_duration, style=style)
            if text_clip:
                text_clip = text_clip.set_start(data["start_time"])
                text_clip = text_clip.crossfadein(style.text_fade_in).crossfadeout(
                    style.text_fade_out
                )
                text_clips.append(text_clip)

        # Ayah number
        if data["ayah"] > 0:
            ayah_num_clip = create_ayah_number_clip(data["ayah"], display_duration, style=style)
            if ayah_num_clip:
                ayah_num_clip = ayah_num_clip.set_start(data["start_time"])
                ayah_num_clip = ayah_num_clip.crossfadein(0.3).crossfadeout(0.3)
                text_clips.append(ayah_num_clip)

        # The English translation is deliberately not rendered. Arabic and
        # English word order differ, so it cannot follow the recitation, and a
        # long verse filled the frame. It lives in the video description instead.

    # Surah label
    surah_label = create_surah_label(surah_name, total_duration, style=style)
    if surah_label:
        text_clips.append(surah_label)

    # === STEP 5: Audio track ===
    audio_clips = []
    logger.info(f"Building audio track with {len(ayah_data)} ayahs...")

    for i, data in enumerate(ayah_data):
        audio_clip = AudioFileClip(str(data["audio_path"]))
        max_duration = data["audio_duration"]
        if audio_clip.duration > max_duration:
            logger.warning(
                f"Ayah {data['ayah']}: Trimming audio from "
                f"{audio_clip.duration:.2f}s to {max_duration:.2f}s"
            )
            audio_clip = audio_clip.subclip(0, max_duration)

        audio_clip = audio_clip.set_start(data["start_time"])
        audio_clip = audio_clip.audio_fadein(0.05).audio_fadeout(0.05)

        logger.debug(
            f"Audio clip {i+1}: ayah={data['ayah']}, "
            f"start={data['start_time']:.2f}s, dur={audio_clip.duration:.2f}s"
        )
        audio_clips.append(audio_clip)

    combined_audio = CompositeAudioClip(audio_clips)
    logger.info(f"Combined audio duration: {combined_audio.duration:.2f}s")

    # Ambient sound
    from core.audio_processor import get_ambient_sound, AMBIENT_ENABLED
    if AMBIENT_ENABLED:
        ambient_path = get_ambient_sound(total_duration)
        if ambient_path:
            ambient_clip = AudioFileClip(str(ambient_path)).set_duration(total_duration)
            combined_audio = CompositeAudioClip([combined_audio, ambient_clip])

    # Write combined audio to a temp file; ffmpeg will pad silence automatically
    import tempfile
    temp_audio_path = Path(tempfile.mktemp(suffix=".mp3", dir=str(AUDIO_DIR)))
    combined_audio.write_audiofile(
        str(temp_audio_path), fps=44100, codec="libmp3lame",
        bitrate=AUDIO_BITRATE, verbose=False, logger=None,
    )
    logger.info(f"Wrote temp audio: {temp_audio_path}")

    # === STEP 6: Composite final video ===
    logger.info("Compositing video with enhanced overlays...")

    final_video = CompositeVideoClip(
        [bg_with_grading] + text_clips,
        size=(VIDEO_WIDTH, VIDEO_HEIGHT),
    )
    final_video = final_video.set_duration(total_duration)
    final_video = final_video.fadein(style.video_fade).fadeout(style.video_fade)
    final_video.fps = VIDEO_FPS
    # Audio is passed directly to write_videofile via audio= parameter

    # === STEP 7: Intro frame ===
    if ENABLE_INTRO_FRAME:
        try:
            intro = create_intro_frame(
                surah_num=surah,
                surah_name_ar=surah_name,
                surah_name_en=surah_name_en,
                verse_start=start_ayah,
                verse_end=end_ayah,
                duration=INTRO_DURATION,
                style=style,
            )
            final_video = concatenate_videoclips(
                [intro, final_video], method="compose"
            )
            total_duration += INTRO_DURATION
            logger.info(f"Added {INTRO_DURATION}s intro frame")
        except Exception as e:
            logger.warning(f"Could not add intro frame, skipping: {e}")

    # === STEP 8: Export ===
    if output_path is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        verse_range = (
            f"{start_ayah}" if start_ayah == end_ayah
            else f"{start_ayah}-{end_ayah}"
        )
        filename = f"QuranReel_{surah}_{surah_name}_{verse_range}_{timestamp}.mp4"
        output_path = VIDEOS_DIR / filename

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Exporting video to {output_path}")
    final_video.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec=VIDEO_CODEC,
        audio=str(temp_audio_path),
        audio_codec=AUDIO_CODEC,
        audio_bitrate=AUDIO_BITRATE,
        verbose=False,
        logger=None,
        ffmpeg_params=["-movflags", "+faststart"],
    )

    # Cleanup
    final_video.close()
    if temp_audio_path.exists():
        temp_audio_path.unlink()
    cleanup_audio_files(AUDIO_DIR)

    logger.success(f"Reel generated successfully: {output_path}")
    return output_path, start_ayah, end_ayah


def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds."""
    with VideoFileClip(str(video_path)) as clip:
        return clip.duration
