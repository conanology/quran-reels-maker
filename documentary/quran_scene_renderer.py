"""
Render exact Qur'an verse overlays for documentary scenes using local text rendering.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from moviepy.editor import ColorClip, CompositeVideoClip
import moviepy.video.fx.all as vfx

from core.style_config import DEFAULT_STYLE
from core.text_renderer import (
    create_pil_text_clip,
    create_translation_clip,
)
from documentary.config import DOCUMENTARY_VIDEO_WIDTH, DOCUMENTARY_VIDEO_HEIGHT
from documentary.quran_scene_resolver import QuranVersePayload


def _documentary_text_style():
    # Reuse the Arabic-capable renderer style but tune for 16:9 documentary frames.
    return replace(
        DEFAULT_STYLE,
        video_width=DOCUMENTARY_VIDEO_WIDTH,
        video_height=DOCUMENTARY_VIDEO_HEIGHT,
        text_max_width=int(DOCUMENTARY_VIDEO_WIDTH * 0.84),
        translation_font_size=40,
        translation_y_ratio=0.73,
        stroke_width=3,
        shadow_offset=(3, 3),
        shadow_opacity=0.75,
        surah_label_font_size=34,
        surah_label_bg_opacity=0.40,
    )


def build_quran_scene_overlay(
    *,
    payload: QuranVersePayload,
    duration: float,
    start_time: float = 0.0,
    include_translation: bool = True,
) -> Optional[CompositeVideoClip]:
    """Create a timed overlay composite for a Qur'an verse scene.

    The overlay is intended to sit on top of a visual background clip. It dims the
    frame slightly and renders exact Arabic text + optional translation + citation.
    """
    if duration <= 0.4:
        return None

    style = _documentary_text_style()
    clips = []

    # Dim overlay for readability while preserving background motion.
    dim = (
        ColorClip((DOCUMENTARY_VIDEO_WIDTH, DOCUMENTARY_VIDEO_HEIGHT), color=(8, 10, 16))
        .set_opacity(0.20)
        .set_duration(duration)
    )
    clips.append(dim)

    # Arabic text block centered slightly above midline for a reverent look.
    arabic = create_pil_text_clip(
        payload.arabic_text,
        duration=duration,
        font_size=72,
        color="white",
        words_per_line=6,
        y_position=0.40,
        is_arabic=True,
        style=style,
    )
    arabic = arabic.fx(vfx.fadein, 0.35).fx(vfx.fadeout, 0.35)
    clips.append(arabic)

    # Translation below Arabic block (optional).
    if include_translation and payload.translation_text:
        tr = create_translation_clip(payload.translation_text, duration=duration, style=style)
        if tr is not None:
            tr = tr.fx(vfx.fadein, 0.45).fx(vfx.fadeout, 0.35)
            clips.append(tr)

    # Arabic citation near bottom (exact text, locally rendered)
    citation_ar = create_pil_text_clip(
        payload.citation_ar,
        duration=duration,
        font_size=26,
        color="#E7C77A",
        words_per_line=18,
        y_position=0.86,
        is_arabic=True,
        style=style,
    ).fx(vfx.fadein, 0.45).fx(vfx.fadeout, 0.35)
    clips.append(citation_ar)

    # English citation line near top for auditability/readability.
    citation = create_pil_text_clip(
        payload.citation_en,
        duration=duration,
        font_size=28,
        color="#FFD166",
        words_per_line=20,
        y_position=0.12,
        is_arabic=False,
        style=style,
    ).fx(vfx.fadein, 0.45).fx(vfx.fadeout, 0.35)
    clips.append(citation)

    comp = CompositeVideoClip(clips, size=(DOCUMENTARY_VIDEO_WIDTH, DOCUMENTARY_VIDEO_HEIGHT)).set_duration(duration)
    if start_time:
        comp = comp.set_start(start_time)
    return comp
