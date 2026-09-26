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
import tempfile
import time
import hashlib
from bisect import bisect_right
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
from core.utils import close_media_resources, file_sha256, verify_media_streams, write_media_manifest
from core.runtime_safety import exclusive_lock, atomic_write_json
from core.asset_provenance import get_asset_provenance

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
    compute_page_boundaries,
    split_translation_by_pages,
)


def download_ai_background(translation: str) -> Optional[Path]:
    """Generate and download a themed AI background image from Pollinations.ai."""
    import time
    import requests
    import urllib.parse
    from core.ai_brain import generate_visual_prompt
    if os.getenv("ENABLE_AI_BACKGROUNDS", os.getenv("ALLOW_AI_BACKGROUNDS", "false")).lower() != "true":
        return None
    
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
    descriptor, filename = tempfile.mkstemp(prefix="ai_bg_", suffix=".part", dir=download_dir)
    os.close(descriptor)
    partial_path = Path(filename)
    output_path = partial_path.with_suffix(".jpg")
    
    logger.info(f"Downloading themed AI background from Pollinations: {output_path.name}")
    try:
        deadline = time.monotonic() + 120
        with requests.get(url, stream=True, timeout=(10, 30)) as response, partial_path.open("wb") as destination:
            response.raise_for_status()
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 12 * 1024 * 1024 or time.monotonic() > deadline:
                    raise ValueError("Generated background exceeded image size/time bound")
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        with Image.open(partial_path) as generated:
            width, height = generated.size
            if width <= 0 or height <= 0 or width * height > 30_000_000 or generated.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Generated background is not a supported bounded image")
            generated.verify()
        os.replace(partial_path, output_path)
        atomic_write_json(Path(str(output_path) + ".source.json"), {
            "provider": "Pollinations", "generated": True, "requested_model": "flux",
            "prompt_sha256": hashlib.sha256(visual_prompt.encode("utf-8")).hexdigest(),
            "width": width, "height": height, "sha256": file_sha256(output_path),
            "license_review_required": True, "content_review_required": True,
        })
        return output_path
    except Exception as e:
        logger.error(f"Failed to download AI background: {e}")
        output_path.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)
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
        raise VideoGeneratorError(f"Could not measure ayah audio: {audio_path.name}") from e


def _build_karaoke_clips(timing, display_duration, style, output_dir, prefix):
    """
    One lazy clip holding each highlighted word until the next word begins.

    Scheduling on the next word's start rather than this word's end avoids the
    gaps that would otherwise appear between words, where no text would show.
    """
    from moviepy.editor import VideoClip
    import numpy as np

    from core.karaoke_renderer import KaraokeStyle, render_word_states

    karaoke_style = KaraokeStyle(
        font_path=Path(style.font_path),
        font_size=style.page_font_size,
        width=style.video_width,
        height=style.video_height,
    )
    paths = render_word_states(timing.words, output_dir, karaoke_style, prefix=prefix)
    timing.validate_for_audio(display_duration)
    starts = [value / 1000 for value in timing.starts_ms]
    # Keep only the current full-frame state in memory, rather than one RGB and
    # floating alpha array per word. PNG states remain in this job's directory.
    cache = {"index": None, "rgba": None}
    def rgba_at(t):
        index = max(0, bisect_right(starts, t) - 1)
        if cache["index"] != index:
            with Image.open(paths[index]) as image:
                cache["rgba"] = np.array(image.convert("RGBA"))
            cache["index"] = index
        return cache["rgba"]
    clip = VideoClip(lambda t: rgba_at(t)[:, :, :3], duration=display_duration)
    mask = VideoClip(lambda t: rgba_at(t)[:, :, 3].astype(np.float32) / 255, duration=display_duration, ismask=True)
    return [clip.set_mask(mask)]


def generate_reel(
    surah: int,
    start_ayah: int,
    end_ayah: int,
    reciter_key: str = DEFAULT_RECITER,
    output_path: Optional[Path] = None,
    style: StyleConfig = DEFAULT_STYLE,
) -> Tuple[Path, int, int]:
    """Render into a private job directory and close every source on failure."""
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    resources = []
    with tempfile.TemporaryDirectory(prefix="reel_", dir=VIDEOS_DIR) as name:
        try:
            return _generate_reel(surah, start_ayah, end_ayah, reciter_key, output_path, style, Path(name), resources)
        finally:
            close_media_resources(resources)


def _generate_reel(
    surah, start_ayah, end_ayah, reciter_key, output_path, style, job_dir, resources
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

    if reciter_key not in RECITERS:
        raise VideoGeneratorError(f"Unknown reciter: {reciter_key}")
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    karaoke_dir = job_dir / "karaoke"

    # === STEP 1: Download audio and calculate timings ===
    ayah_data = []
    current_time = 0.1
    current_ayah = start_ayah
    max_ayah = VERSE_COUNTS.get(surah, end_ayah)

    # Fetch requested ayahs (stop early if we'd exceed max duration)
    while current_ayah <= end_ayah:
        data = fetch_single_ayah(
            surah, current_ayah, reciter_key, audio_dir,
            get_audio_duration_moviepy, current_time, style.ayah_padding,
        )
        projected_duration = data["segment_end"] + 0.5
        # Stop adding ayahs if this one would push us over the max
        if not ayah_data and projected_duration > max_content_duration:
            raise VideoGeneratorError(
                f"Complete ayah {surah}:{current_ayah} requires {projected_duration:.1f}s; "
                f"it exceeds the {max_content_duration:.0f}s reel target. Generate longform instead."
            )
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
            surah, current_ayah, reciter_key, audio_dir,
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

    logger.info(f"Final verses: {start_ayah}-{end_ayah} ({len(ayah_data)} ayahs)")
    logger.info(f"Total video duration: {total_duration:.1f}s")

    # === STEP 3: Background ===
    full_translation = " ".join(item.get("translation") or "" for item in ayah_data).strip()
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
    resources.append(bg_with_grading)
    bg_with_grading = bg_with_grading.fadein(style.video_fade).fadeout(style.video_fade)

    # === STEP 4: Text overlays ===
    text_clips = []

    for data in ayah_data:
        display_duration = data["end_time"] - data["start_time"]

        # Arabic text: highlight each word as it is recited when real per-word
        # timings exist, otherwise show the whole ayah for its duration.
        timing = data["word_timing"]

        karaoke_clips = []
        if timing:
            karaoke_clips = _build_karaoke_clips(
                timing,
                display_duration,
                style,
                karaoke_dir,
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
    resources.extend(text_clips)

    # === STEP 5: Audio track ===
    audio_clips = []
    logger.info(f"Building audio track with {len(ayah_data)} ayahs...")

    for i, data in enumerate(ayah_data):
        audio_clip = AudioFileClip(str(data["audio_path"]))
        resources.append(audio_clip)
        max_duration = data["audio_duration"]
        if audio_clip.duration > max_duration:
            logger.warning(
                f"Ayah {data['ayah']}: Trimming audio from "
                f"{audio_clip.duration:.2f}s to {max_duration:.2f}s"
            )
            audio_clip = audio_clip.subclip(0, max_duration)

        audio_clip = audio_clip.set_start(data["start_time"])

        logger.debug(
            f"Audio clip {i+1}: ayah={data['ayah']}, "
            f"start={data['start_time']:.2f}s, dur={audio_clip.duration:.2f}s"
        )
        audio_clips.append(audio_clip)

    combined_audio = CompositeAudioClip(audio_clips)
    resources.append(combined_audio)
    logger.info(f"Combined audio duration: {combined_audio.duration:.2f}s")

    # Ambient sound
    from core.audio_processor import get_ambient_sound, AMBIENT_ENABLED
    if AMBIENT_ENABLED:
        ambient_path = get_ambient_sound(total_duration, output_dir=audio_dir)
        if ambient_path:
            ambient_clip = AudioFileClip(str(ambient_path)).set_duration(total_duration)
            resources.append(ambient_clip)
            combined_audio = CompositeAudioClip([combined_audio, ambient_clip])
            resources.append(combined_audio)

    # === STEP 6: Composite final video ===
    logger.info("Compositing video with enhanced overlays...")

    final_video = CompositeVideoClip(
        [bg_with_grading] + text_clips,
        size=(style.video_width, style.video_height),
    )
    resources.append(final_video)
    final_video = final_video.set_duration(total_duration)
    final_video.fps = VIDEO_FPS
    # Audio is attached after any intro is composed, on the same timeline.

    # === STEP 7: Intro frame ===
    if ENABLE_INTRO_FRAME:
        intro = create_intro_frame(
            surah_num=surah, surah_name_ar=surah_name, surah_name_en=surah_name_en,
            verse_start=start_ayah, verse_end=end_ayah, duration=INTRO_DURATION, style=style,
        )
        final_video = concatenate_videoclips([intro, final_video], method="compose")
        resources.extend([intro, final_video])
        combined_audio = CompositeAudioClip([combined_audio.set_start(INTRO_DURATION)])
        resources.append(combined_audio)
        total_duration += INTRO_DURATION
        logger.info(f"Added {INTRO_DURATION}s intro frame")
    combined_audio = combined_audio.set_duration(total_duration)
    final_video = final_video.set_audio(combined_audio)
    resources.append(final_video)

    # === STEP 8: Export ===
    if output_path is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        verse_range = (
            f"{start_ayah}" if start_ayah == end_ayah
            else f"{start_ayah}-{end_ayah}"
        )
        filename = f"QuranReel_{surah}_{surah_name}_{verse_range}_{timestamp}.mp4"
        output_path = VIDEOS_DIR / filename

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Exporting video to {output_path}")
    with exclusive_lock(Path(str(output_path) + ".lock")):
        if output_path.exists():
            raise FileExistsError(f"Refusing to overwrite an existing reel: {output_path.name}")
        final_video.write_videofile(
            str(output_path), fps=VIDEO_FPS, codec=VIDEO_CODEC, audio=True,
            temp_audiofile=str(audio_dir / "combined.m4a"), audio_codec=AUDIO_CODEC,
            audio_bitrate=AUDIO_BITRATE, verbose=False, logger=None,
            ffmpeg_params=["-movflags", "+faststart"],
        )
        streams = verify_media_streams(output_path, total_duration, style.video_width, style.video_height)
        write_media_manifest(output_path, {
            "format": "shorts", "reciter_key": reciter_key,
            "coverage": [{"surah": surah, "start_ayah": start_ayah, "end_ayah": end_ayah}],
            "verses": [{"surah": surah, "ayah": item["ayah"], "reciter_key": reciter_key,
                        "text": item["text"], "recording_url": item["recording_url"],
                        "source": item["audio_source"], "audio_sha256": file_sha256(item["audio_path"]),
                        "text_source": item["text_source"], "timing_source": item["timing_source"],
                        "audio_duration": item["audio_duration"]} for item in ayah_data],
            "loop_count": 1, "intro_duration": INTRO_DURATION if ENABLE_INTRO_FRAME else 0,
            "duration_seconds": total_duration, "streams": streams,
            "background": get_asset_provenance(background_path), "domain_review_required": True,
        })

    logger.success(f"Reel generated successfully: {output_path}")
    return output_path, start_ayah, end_ayah


def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds."""
    with VideoFileClip(str(video_path)) as clip:
        return clip.duration
