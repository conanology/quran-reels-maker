"""
Background - Background loading, Ken Burns effect, and color grading
"""
import random
from pathlib import Path

import numpy as np
from PIL import Image
from loguru import logger

from moviepy.editor import VideoFileClip, CompositeVideoClip, ColorClip
import moviepy.video.fx.all as vfx

from config.settings import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    BACKGROUNDS_DIR,
)
from core.style_config import StyleConfig, DEFAULT_STYLE


class BackgroundError(Exception):
    pass


def pick_random_background() -> Path:
    """
    Select a random background video from the backgrounds directory.

    Returns:
        Path to the selected background video

    Raises:
        BackgroundError: If no background videos are found
    """
    backgrounds_path = Path(BACKGROUNDS_DIR)

    video_extensions = [".mp4", ".mov", ".avi", ".mkv", ".webm"]
    videos = [
        f
        for f in backgrounds_path.iterdir()
        if f.suffix.lower() in video_extensions
    ]

    if not videos:
        raise BackgroundError(
            f"No background videos found in {backgrounds_path}. "
            "Please add some .mp4 files to the assets/backgrounds folder."
        )

    selected = random.choice(videos)
    logger.debug(f"Selected background: {selected.name}")
    return selected


def apply_ken_burns_effect(clip, zoom_ratio: float = 1.08):
    """
    Apply a subtle Ken Burns (slow zoom) effect to a video clip.

    Args:
        clip: Video clip to apply effect to
        zoom_ratio: How much to zoom (1.0 = no zoom, 1.1 = 10% zoom)

    Returns:
        Video clip with Ken Burns effect applied
    """
    duration = clip.duration
    w, h = clip.size

    def zoom_effect(get_frame, t):
        progress = t / duration
        current_zoom = 1 + (zoom_ratio - 1) * progress

        frame = get_frame(t)

        new_w = int(w / current_zoom)
        new_h = int(h / current_zoom)

        x1 = (w - new_w) // 2
        y1 = (h - new_h) // 2
        x2 = x1 + new_w
        y2 = y1 + new_h

        img = Image.fromarray(frame)
        cropped = img.crop((x1, y1, x2, y2))
        resized = cropped.resize((w, h), Image.LANCZOS)

        return np.array(resized)

    return clip.fl(zoom_effect, apply_to=["mask"])


def load_and_grade_background(
    path: Path,
    total_duration: float,
    style: StyleConfig = DEFAULT_STYLE,
    enable_ken_burns: bool = True,
) -> CompositeVideoClip:
    """
    Load a background video, resize/crop to 9:16, apply color grading,
    and optionally apply Ken Burns effect.

    Args:
        path: Path to the background video file
        total_duration: Duration to loop the background to
        style: StyleConfig with grading parameters
        enable_ken_burns: Whether to apply Ken Burns zoom

    Returns:
        Graded CompositeVideoClip ready for compositing
    """
    bg_clip = VideoFileClip(str(path))

    # Loop to cover full duration
    bg_clip = bg_clip.fx(vfx.loop, duration=total_duration)
    bg_clip = bg_clip.subclip(0, total_duration)

    # Aspect ratio fitting
    target_aspect = style.video_width / style.video_height
    source_aspect = bg_clip.w / bg_clip.h

    if source_aspect > target_aspect:
        bg_clip = bg_clip.resize(height=style.video_height)
        x_center = (bg_clip.w - style.video_width) // 2
        bg_clip = bg_clip.crop(x1=x_center, x2=x_center + style.video_width)
    else:
        bg_clip = bg_clip.resize(width=style.video_width)
        if bg_clip.h > style.video_height:
            y_center = (bg_clip.h - style.video_height) // 2
            bg_clip = bg_clip.crop(y1=y_center, y2=y_center + style.video_height)

    if bg_clip.size != (style.video_width, style.video_height):
        bg_clip = bg_clip.resize(newsize=(style.video_width, style.video_height))

    # Darken
    bg_clip = bg_clip.fx(vfx.colorx, style.background_brightness)

    # Blue tint overlay
    if style.background_tint_opacity > 0:
        dark_overlay = (
            ColorClip(
                size=(style.video_width, style.video_height),
                color=style.background_tint,
            )
            .set_opacity(style.background_tint_opacity)
            .set_duration(total_duration)
        )
        bg_with_grading = CompositeVideoClip(
            [bg_clip, dark_overlay],
            size=(style.video_width, style.video_height),
        )
    else:
        bg_with_grading = bg_clip

    # Ken Burns
    if enable_ken_burns:
        try:
            bg_with_grading = apply_ken_burns_effect(
                bg_with_grading, zoom_ratio=style.ken_burns_zoom
            )
            logger.debug("Applied Ken Burns zoom effect to background")
        except Exception as e:
            logger.warning(
                f"Ken Burns effect failed, using static background: {e}"
            )

    return bg_with_grading
