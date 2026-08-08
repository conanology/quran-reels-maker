"""Tests for core.karaoke_renderer."""
from pathlib import Path

import pytest

from config.settings import FONT_PATH
from core.karaoke_renderer import (
    KaraokeRenderError,
    KaraokeStyle,
    _build_html,
    render_word_states,
)

WORDS = ["قُلْ", "هُوَ", "ٱللَّهُ", "أَحَدٌ"]


@pytest.fixture
def style():
    return KaraokeStyle(font_path=Path(FONT_PATH), width=480, height=854)


class TestBuildHtml:
    def test_each_word_becomes_its_own_span(self, style):
        html = _build_html(WORDS, style)

        for i, word in enumerate(WORDS):
            assert f'id="w{i}"' in html
            assert word in html

    def test_font_is_embedded_so_rendering_does_not_depend_on_system_fonts(
        self, style
    ):
        html = _build_html(WORDS, style)

        assert "data:font/ttf;base64," in html

    def test_direction_is_rtl(self, style):
        assert "direction: rtl" in _build_html(WORDS, style)

    def test_words_are_not_reshaped(self, style):
        """Chromium shapes the text; pre-reshaping would double-apply it"""
        html = _build_html(WORDS, style)

        # Presentation Forms would mean something already reshaped the text.
        assert not any("ﹰ" <= ch <= "﻿" for ch in html)


class TestRenderWordStates:
    def test_rejects_empty_verse(self, style, tmp_path):
        with pytest.raises(KaraokeRenderError, match="no words"):
            render_word_states([], tmp_path, style)

    def test_rejects_missing_font(self, tmp_path):
        style = KaraokeStyle(font_path=tmp_path / "nope.ttf")

        with pytest.raises(KaraokeRenderError, match="font not found"):
            render_word_states(WORDS, tmp_path, style)

    @pytest.mark.slow
    def test_renders_one_transparent_image_per_word(self, style, tmp_path):
        from PIL import Image

        paths = render_word_states(WORDS, tmp_path, style)

        assert len(paths) == len(WORDS)
        for path in paths:
            image = Image.open(path).convert("RGBA")
            assert image.size == (style.width, style.height)
            low, high = image.getchannel("A").getextrema()
            assert low == 0, "background should be transparent"
            assert high == 255, "glyphs should be opaque"

    @pytest.mark.slow
    def test_highlight_moves_between_states(self, style, tmp_path):
        """Consecutive states must differ, or the highlight is not advancing"""
        import numpy as np
        from PIL import Image

        paths = render_word_states(WORDS, tmp_path, style)
        frames = [np.array(Image.open(p).convert("RGB")).astype(int) for p in paths]

        for a, b in zip(frames, frames[1:]):
            assert np.abs(a - b).sum() > 0
