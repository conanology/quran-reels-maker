"""
Renders the Arabic verse once per recited word, highlighting the current one.

Chromium does the shaping and RTL layout, so each word's position is exact by
construction. Measuring word offsets inside a shaped Arabic line is unreliable
because shaping is contextual, which would drift the highlight off the word.
It also renders tashkeel identically on Windows and Linux, unlike the PIL path,
which silently degrades wherever FriBiDi is missing.
"""
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from loguru import logger

from config.settings import VIDEO_HEIGHT, VIDEO_WIDTH


class KaraokeRenderError(Exception):
    pass


@dataclass
class KaraokeStyle:
    """Type and colour for the verse layer."""

    font_path: Path
    font_size: int = 96
    line_height: float = 2.4  # Quranic marks need far more room than Latin
    active_color: str = "#F0C86A"
    inactive_color: str = "rgba(255, 255, 255, 0.55)"
    max_width_ratio: float = 0.82
    width: int = VIDEO_WIDTH
    height: int = VIDEO_HEIGHT
    surah_label: Optional[str] = None
    extra_css: str = field(default="")


_HTML = """<!doctype html>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'VerseFont';
    src: url(data:font/ttf;base64,{font_b64}) format('truetype');
  }}
  html, body {{ margin: 0; padding: 0; background: transparent; }}
  body {{
    width: {width}px; height: {height}px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'VerseFont', serif;
    direction: rtl;
  }}
  #verse {{
    max-width: {max_width}px;
    text-align: center;
    font-size: {font_size}px;
    line-height: {line_height};
    color: {inactive};
    text-shadow: 0 0 34px rgba(0,0,0,0.65), 0 5px 14px rgba(0,0,0,0.55);
  }}
  .w {{ transition: none; }}
  .w.active {{ color: {active}; }}
  {extra_css}
</style>
<div id="verse">{spans}</div>
"""


def _build_html(words: List[str], style: KaraokeStyle) -> str:
    font_b64 = base64.b64encode(style.font_path.read_bytes()).decode()
    spans = " ".join(
        f'<span class="w" id="w{i}">{word}</span>' for i, word in enumerate(words)
    )
    return _HTML.format(
        font_b64=font_b64,
        width=style.width,
        height=style.height,
        max_width=int(style.width * style.max_width_ratio),
        font_size=style.font_size,
        line_height=style.line_height,
        inactive=style.inactive_color,
        active=style.active_color,
        extra_css=style.extra_css,
        spans=spans,
    )


def render_word_states(
    words: List[str],
    output_dir: Path,
    style: KaraokeStyle,
    prefix: str = "state",
) -> List[Path]:
    """
    One transparent PNG per word, with that word highlighted.

    A single page is reused and the highlight is moved with a class toggle, so
    the cost is one screenshot per word rather than a browser launch per word.
    """
    if not words:
        raise KaraokeRenderError("cannot render a verse with no words")
    if not style.font_path.exists():
        raise KaraokeRenderError(f"font not found: {style.font_path}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise KaraokeRenderError(f"playwright is required: {e}") from e

    output_dir.mkdir(parents=True, exist_ok=True)
    html = _build_html(words, style)
    html_path = output_dir / f"{prefix}.html"
    html_path.write_text(html, encoding="utf-8")

    paths: List[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": style.width, "height": style.height}
            )
            page.goto(html_path.as_uri())
            page.wait_for_selector("#verse")

            for index in range(len(words)):
                page.evaluate(
                    """(i) => {
                        document.querySelectorAll('.w.active')
                            .forEach(el => el.classList.remove('active'));
                        const el = document.getElementById('w' + i);
                        if (el) el.classList.add('active');
                    }""",
                    index,
                )
                out = output_dir / f"{prefix}_{index:03d}.png"
                page.screenshot(path=str(out), omit_background=True)
                paths.append(out)
        finally:
            browser.close()

    logger.debug(f"Rendered {len(paths)} karaoke states to {output_dir}")
    return paths
