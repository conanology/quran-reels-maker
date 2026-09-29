"""Media regression checks without production settings/cache/database imports."""
import ast
import __future__
import base64
import json
import math
import re
import html
import datetime
import hashlib
import os
import subprocess
import tempfile
import time
from contextlib import nullcontext
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

ROOT = Path(os.getenv("QRM_TEST_SOURCE_ROOT", str(Path(__file__).resolve().parents[1]))).resolve()


class Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def definitions(relative, namespace=None, names=None):
    namespace = dict(namespace or {})
    namespace.update(Path=Path, logger=Logger(), dataclass=dataclass, field=field,
                     List=List, Dict=Dict, Any=Any, Optional=Optional, Tuple=Tuple,
                     math=math, re=re, html=html, hashlib=hashlib, json=json)
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (names is None or node.name in names):
            if isinstance(node, ast.FunctionDef):
                node.decorator_list = []
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), relative, "exec",
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace


@pytest.fixture
def timings():
    return definitions("core/word_timings.py", {"RECITER_MAPPING_V4": {"alafasy": 7}})


@pytest.mark.parametrize("segments", [
    [[0, 1, -1, 500]], [[0, 1, 0, 0]], [[9, 1, 0, 500]],
    [[0, 9, 0, 500]], [[0, 500]], [[0, 1, 0.5, 500]],
    [[0, 1, True, 500]],
])
def test_rejects_malformed_timing_identity_and_bounds(timings, segments):
    with pytest.raises(timings["WordTimingError"]):
        timings["parse_segments"](segments)


def test_rejects_empty_quran_word(timings):
    timings["_fetch_verse"] = lambda *args: {"verse": {
        "verse_key": "112:1",
        "audio": {"url": "Alafasy/mp3/112001.mp3", "segments": [[0, 1, 0, 500]]},
        "words": [{"position": 1, "char_type_name": "word", "text_uthmani": ""}],
    }}
    with pytest.raises(timings["WordTimingError"]):
        timings["get_word_timings"]("alafasy", 112, 1)


def test_mapped_audio_download_uses_timing_recording(timings, tmp_path):
    timing = timings["WordTiming"](["قُلْ"], [0], [500], "timing-source.mp3")
    recorded = []
    def download(reciter, surah, ayah, directory, audio_url=None):
        recorded.append(audio_url)
        return tmp_path / "fixture.mp3"
    ns = definitions("core/ayah_fetcher.py", {
        "RECITER_MAPPING_V4": {"alafasy": 7}, "RECITERS": {"alafasy": {}},
        "get_word_timings": lambda *args: timing,
        "get_verse_audio_with_timings": lambda *args: ("other-recording.mp3", []),
        "download_and_process_ayah": download,
        "get_ayah_text": lambda *args: "قُلْ",
        "get_ayah_translation": lambda *args: None,
    })
    result = ns["fetch_single_ayah"](112, 1, "alafasy", tmp_path, lambda p: 1.0, 0, 0)
    assert recorded == ["timing-source.mp3"]
    assert result["word_timing"] is timing
    assert result["translation"] is None
    assert result["text_source"]["provider"] == "quran.com"
    assert result["timing_source"]["word_count"] == result["timing_source"]["segment_count"] == 1


def test_expected_timing_failure_cannot_download_alternate_audio(timings, tmp_path):
    def broken(*args):
        raise timings["WordTimingError"]("expected upstream timings unavailable")
    ns = definitions("core/ayah_fetcher.py", {
        "RECITER_MAPPING_V4": {"alafasy": 7}, "RECITERS": {"alafasy": {}},
        "get_word_timings": broken,
        "get_verse_audio_with_timings": lambda *args: (None, []),
        "download_and_process_ayah": lambda *args, **kwargs: tmp_path / "wrong.mp3",
        "get_ayah_text": lambda *args: "قُلْ", "get_ayah_translation": lambda *args: None,
    })
    with pytest.raises(timings["WordTimingError"]):
        ns["fetch_single_ayah"](112, 1, "alafasy", tmp_path, lambda p: 1.0, 0, 0)


def test_direct_audio_names_cannot_collide_between_reciters(tmp_path):
    def download(url, path):
        if not path.exists():
            path.write_text(url, encoding="utf-8")
        return path
    ns = definitions("core/audio_processor.py", {
        "RECITERS": {"alafasy": {}, "sudais": {}}, "hashlib": hashlib,
        "normalize_recording_url": lambda url: url, "_download_recording": download,
    }, {"download_and_process_ayah", "AudioProcessingError"})
    first = ns["download_and_process_ayah"]("alafasy", 112, 1, tmp_path, "recording-a")
    second = ns["download_and_process_ayah"]("sudais", 112, 1, tmp_path, "recording-b")
    assert first != second
    assert first.read_text(encoding="utf-8") == "recording-a"
    assert second.read_text(encoding="utf-8") == "recording-b"


def test_preserves_quran_small_marks():
    import re
    ns = definitions("core/text_renderer.py", {"_UTHMANI_STRIP_RE": re.compile("[\u06D6-\u06ED]")}, {"_clean_arabic"})
    text = "هُ\u06E5 ۖ ۞ ۩"
    assert ns["_clean_arabic"](text) == text


def test_arabic_rendering_fails_without_shaping_engine(monkeypatch):
    from PIL import features
    monkeypatch.setattr(features, "check", lambda feature: False)
    ns = definitions("core/text_renderer.py", {"DEFAULT_STYLE": object(), "TEXT_MAX_WIDTH": 100,
        "_HAS_BIDI": False}, names={"PILTextRenderer", "_clean_arabic"})
    renderer = ns["PILTextRenderer"]()
    with pytest.raises(RuntimeError, match="Arabic rendering requires"):
        renderer.render_text("قُلْ", 30)


def test_validate_timing_against_actual_recording(timings):
    timing = timings["WordTiming"](["قُلْ"], [0], [2000], "source.mp3")
    assert hasattr(timing, "validate_for_audio"), "Timings need actual-audio validation"
    with pytest.raises(timings["WordTimingError"]):
        timing.validate_for_audio(1.0)


@pytest.mark.parametrize("damage", ["verse_bounds", "text_checksum", "timing_count", "unknown_reciter"])
def test_manifest_rejects_invalid_coverage_and_source_proof(tmp_path, monkeypatch, damage):
    import sys
    settings = types.ModuleType("config.settings")
    settings.VERSE_COUNTS, settings.RECITERS = {112: 4}, {"alafasy": {}}
    monkeypatch.setitem(sys.modules, "config.settings", settings)
    video = tmp_path / "fixture.mp4"
    video.write_bytes(b"local verification fixture")
    text = "قُلْ"
    manifest = {"schema_version": 1, "verified": True, "coverage_complete": True,
        "reciter_key": "alafasy", "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "coverage": [{"surah": 112, "start_ayah": 1, "end_ayah": 1}],
        "verses": [{"surah": 112, "ayah": 1, "text": text, "reciter_key": "alafasy",
            "recording_url": "https://verses.quran.com/synthetic.mp3", "audio_sha256": "a" * 64,
            "audio_duration": 1.0,
            "text_source": {"provider": "synthetic", "verse_key": "112:1", "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
            "timing_source": {"status": "validated", "provider": "synthetic", "word_count": 1,
                "segment_count": 1, "segments_sha256": "b" * 64}}]}
    if damage == "verse_bounds":
        manifest["coverage"][0]["end_ayah"] = 5
    elif damage == "text_checksum":
        manifest["verses"][0]["text"] = "different text"
    elif damage == "timing_count":
        manifest["verses"][0]["timing_source"]["segment_count"] = 0
    else:
        manifest["reciter_key"] = "unknown"
    Path(str(video) + ".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    ns = definitions("core/utils.py", names={"file_sha256", "load_media_manifest"})
    with pytest.raises(ValueError):
        ns["load_media_manifest"](video)


def test_manifest_writer_requires_actual_stream_verification(tmp_path):
    calls = []
    def invalid_stream(*args):
        calls.append(args)
        raise ValueError("missing recitation stream")
    ns = definitions("core/utils.py", {"verify_media_streams": invalid_stream}, names={"write_media_manifest"})
    video = tmp_path / "invalid.mp4"
    with pytest.raises(ValueError, match="missing recitation stream"):
        ns["write_media_manifest"](video, {"duration_seconds": 1, "streams": {"width": 64, "height": 96}, "verified": True})
    assert calls == [(video, 1, 64, 96)]
    assert not Path(str(video) + ".manifest.json").exists()


@pytest.fixture
def reel_environment(monkeypatch, tmp_path):
    import sys
    import numpy as np
    from moviepy.editor import AudioClip, AudioFileClip, CompositeAudioClip, CompositeVideoClip, ColorClip, concatenate_videoclips
    from requests.exceptions import RequestException
    source = AudioClip(lambda t: 0.2 * np.sin(2 * np.pi * 440 * t), duration=0.4, fps=44100)
    wav = tmp_path / "recitation.wav"
    source.write_audiofile(str(wav), fps=44100, codec="pcm_s16le", logger=None)
    source.close()
    utility = definitions("core/utils.py", {"hashlib": hashlib, "json": json,
        "subprocess": subprocess, "RequestException": RequestException, "time": time})
    settings = types.ModuleType("config.settings")
    settings.MIN_REEL_DURATION_SECONDS = 0
    settings.MAX_REEL_DURATION_SECONDS = 59
    settings.VERSE_COUNTS = {112: 4}
    settings.RECITERS = {"banna": {}}
    monkeypatch.setitem(sys.modules, "config.settings", settings)
    stock = types.ModuleType("core.stock_footage")
    stock.get_dynamic_background = lambda: tmp_path / "placeholder.mp4"
    monkeypatch.setitem(sys.modules, "core.stock_footage", stock)
    audio_module = types.ModuleType("core.audio_processor")
    audio_module.AMBIENT_ENABLED = False
    audio_module.get_ambient_sound = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "core.audio_processor", audio_module)
    style = types.SimpleNamespace(ayah_padding=0.1, text_fade_in=0, text_fade_out=0, video_fade=0,
                                  video_width=64, video_height=96)
    state = {"duration": 0.4, "translation": None}
    def fetch(surah, ayah, reciter, directory, duration_fn, current, padding):
        text = "قُلْ هُوَ ٱللَّهُ أَحَدٌ"
        return {"ayah": ayah, "audio_path": wav, "audio_duration": state["duration"],
                "text": text, "translation": state["translation"],
                "text_source": {"provider": "synthetic", "verse_key": f"{surah}:{ayah}", "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                "timing_source": {"status": "not_available", "word_count": 0},
                "start_time": current, "end_time": current + state["duration"],
                "segment_end": current + state["duration"] + padding, "word_timing": None,
                "recording_url": "https://everyayah.com/synthetic.mp3", "audio_source": "synthetic"}
    ns = definitions("core/video_generator.py", dict(utility, os=os, datetime=datetime, tempfile=tempfile,
        DEFAULT_RECITER="banna", DEFAULT_STYLE=style, VIDEOS_DIR=tmp_path,
        VIDEO_WIDTH=64, VIDEO_HEIGHT=96, VIDEO_FPS=10, VIDEO_CODEC="libx264", AUDIO_CODEC="aac", AUDIO_BITRATE="96k",
        RECITERS={"banna": {"name_ar": "Synthetic"}}, validate_verse_range=lambda s, a, b: (a, b),
        get_surah_name=lambda *args: "Synthetic", fetch_single_ayah=fetch,
        load_and_grade_background=lambda p, duration, style, **kwargs: ColorClip((64, 96), (10, 20, 30), duration=duration),
        create_text_clip=lambda *args, **kwargs: None, create_ayah_number_clip=lambda *args, **kwargs: None,
        create_surah_label=lambda *args, **kwargs: None,
        create_intro_frame=lambda **kwargs: ColorClip((64, 96), (0, 0, 0), duration=kwargs["duration"]),
        AudioFileClip=AudioFileClip, CompositeAudioClip=CompositeAudioClip, CompositeVideoClip=CompositeVideoClip,
        concatenate_videoclips=concatenate_videoclips, exclusive_lock=lambda *args, **kwargs: nullcontext()))
    ns["get_asset_provenance"] = lambda *args: {"provider": "synthetic", "content_review_required": True}
    monkeypatch.setenv("ENABLE_KEN_BURNS", "false")
    return ns, state, tmp_path


def test_overlong_first_verse_stops_without_partial_output(reel_environment):
    ns, state, directory = reel_environment
    state["duration"] = 90
    with pytest.raises(ns["VideoGeneratorError"], match="Complete ayah"):
        ns["generate_reel"](112, 1, 1, output_path=directory / "must_not_exist.mp4")
    assert not (directory / "must_not_exist.mp4").exists()
    assert not list(directory.glob("reel_*"))


def test_intro_keeps_recitation_silent_until_content_and_writes_manifest(reel_environment, monkeypatch):
    from moviepy.editor import VideoFileClip
    import numpy as np
    ns, state, directory = reel_environment
    monkeypatch.setenv("ENABLE_INTRO_FRAME", "true")
    video, start, end = ns["generate_reel"](112, 1, 1, output_path=directory / "intro.mp4")
    with VideoFileClip(str(video)) as clip:
        assert clip.duration == pytest.approx(4.1, abs=0.1)
        assert np.abs(clip.audio.get_frame(1.0)).max() < 0.001
        samples = clip.audio.get_frame(np.arange(3.15, 3.25, 1 / 44100))
        assert np.sqrt(np.mean(samples ** 2)) > 0.05
    manifest = ns["load_media_manifest"](video)
    assert manifest["coverage"] == [{"surah": 112, "start_ayah": 1, "end_ayah": 1}]
    assert manifest["reciter_key"] == "banna"
    assert manifest["coverage_complete"] is True
    assert not list(directory.glob("reel_*"))
    video.write_bytes(video.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed"):
        ns["load_media_manifest"](video)


@pytest.fixture
def longform_environment(tmp_path):
    (tmp_path / "output").mkdir()
    state = {"fetch_failure": None, "render_failure": None, "duration": 1.0, "render_calls": []}
    audio = tmp_path / "synthetic_audio.mp3"
    audio.write_bytes(b"synthetic recording")
    def fetch(**kwargs):
        if kwargs["ayah"] == state["fetch_failure"]:
            raise RuntimeError("synthetic fetch failure")
        return {"audio_path": audio, "audio_duration": state["duration"], "text": "قُلْ",
                "text_source": {"provider": "synthetic", "verse_key": f"{kwargs['surah']}:{kwargs['ayah']}", "text_sha256": hashlib.sha256("قُلْ".encode("utf-8")).hexdigest()},
                "timing_source": {"status": "not_available", "word_count": 0},
                "translation": None, "recording_url": "synthetic-recording", "audio_source": "synthetic"}
    def render(**kwargs):
        state["render_calls"].append(kwargs)
        if kwargs["ayah_num"] == state["render_failure"]:
            raise RuntimeError("synthetic render failure")
        Path(kwargs["output_path"]).write_bytes(b"synthetic segment")
        return kwargs["audio_duration"] + kwargs["padding_after"]
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if "-f" in command and "concat" in command:
            Path(command[-1]).write_bytes(b"synthetic final media")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")
    ns = definitions("longform/compiler.py", {
        "os": os, "json": json, "datetime": datetime, "tempfile": tempfile, "shutil": __import__("shutil"),
        "subprocess": types.SimpleNamespace(run=run), "VERSE_COUNTS": {112: 4},
        "SURAH_NAMES_AR": ["Synthetic"] * 114, "SURAH_NAMES_EN": ["Synthetic"] * 114,
        "RECITERS": {"banna": {"name_ar": "Synthetic", "name_en": "Synthetic"}},
        "LONGFORM_TEMP_DIR": tmp_path / "jobs", "LONGFORM_OUTPUT_DIR": tmp_path / "output",
        "LONGFORM_MAX_DURATION": 3600, "LONGFORM_WIDTH": 1920, "LONGFORM_HEIGHT": 1080,
        "DETECTED_ENCODER": "libx264", "file_sha256": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "verify_media_streams": lambda *args: {}, "write_media_manifest": lambda *args: None,
        "atomic_write_json": lambda path, data: Path(path).write_text(json.dumps(data), encoding="utf-8"),
        "exclusive_lock": lambda *args: nullcontext(), "fetch_single_ayah": fetch,
        "get_asset_provenance": lambda *args: {"provider": "synthetic"},
        "generate_longform_video_metadata": lambda **kwargs: {},
    })
    ns["_render_ayah_segment"] = render
    ns["_ffprobe_duration"] = lambda *args: 30.0
    return ns, state, tmp_path, commands


@pytest.mark.parametrize("failure", ["fetch_failure", "render_failure"])
def test_longform_missing_verse_cannot_become_complete_publication(longform_environment, failure):
    ns, state, directory, commands = longform_environment
    state[failure] = 2
    with pytest.raises(RuntimeError, match="Incomplete coverage"):
        ns["generate_longform"](112, 112, "banna", background_path="synthetic.mp4")
    assert not any("concat" in command for command in commands)
    assert not list((directory / "output").glob("*.json"))


def test_longform_duration_limit_cannot_claim_complete_range(longform_environment):
    ns, state, directory, commands = longform_environment
    ns["LONGFORM_MAX_DURATION"] = 1
    with pytest.raises(RuntimeError, match="duration limit"):
        ns["generate_longform"](112, 112, "banna", background_path="synthetic.mp4")
    assert not any("concat" in command for command in commands)


def test_partial_longform_metadata_does_not_claim_full_surah(longform_environment):
    ns, state, directory, commands = longform_environment
    metadata = ns["generate_longform"](112, 112, "banna", background_path="synthetic.mp4", ayah_start=2, ayah_end=3)
    assert "Quran Full" not in metadata["tags"]
    assert "تلاوة كاملة" not in metadata["tags"]
    assert "#QuranFull" not in metadata["description"]


def test_longform_verse_join_keeps_background_and_encodes_audio_once(longform_environment):
    ns, state, directory, commands = longform_environment
    ns["generate_longform"](112, 112, "banna", background_path="synthetic.mp4",
                            ayah_start=1, ayah_end=3, output_filename="job.mp4")
    first, middle, last = state["render_calls"]
    assert first["fade_out"] == 0
    assert middle["fade_in"] == middle["fade_out"] == 0
    assert last["fade_in"] == 0
    assert [call["background_offset"] for call in state["render_calls"]] == pytest.approx([0, 1.5, 3.0])
    assert all(call["output_path"].endswith(".mkv") for call in state["render_calls"])
    concat = next(command for command in commands if "concat" in command)
    assert concat[concat.index("-c:a") + 1] == "aac"


@pytest.mark.slow
def test_real_longform_segment_preserves_audio_and_quran_marks(tmp_path):
    import numpy as np
    from moviepy.editor import AudioClip, ColorClip, VideoFileClip
    import arabic_reshaper
    from bidi.algorithm import get_display
    from PIL import Image, ImageDraw, ImageFont
    from requests.exceptions import RequestException
    utility = definitions("core/utils.py", {"hashlib": hashlib, "json": json,
        "subprocess": subprocess, "RequestException": RequestException, "time": time})
    audio = AudioClip(lambda t: 0.25 * np.sin(2 * np.pi * 440 * t), duration=0.4, fps=44100)
    audio_path = tmp_path / "voice.wav"
    audio.write_audiofile(str(audio_path), fps=44100, codec="pcm_s16le", logger=None)
    audio.close()
    background = ColorClip((64, 36), (20, 30, 40), duration=0.5)
    background_path = tmp_path / "background.mp4"
    background.write_videofile(str(background_path), fps=10, codec="libx264", audio=False, logger=None)
    background.close()
    ns = definitions("longform/compiler.py", dict(utility, os=os, re=re, subprocess=subprocess,
        Image=Image, ImageDraw=ImageDraw, ImageFont=ImageFont, arabic_reshaper=arabic_reshaper,
        get_display=get_display, FONT_PATH=ROOT / "assets/fonts/amiri/Amiri-Bold.ttf",
        LONGFORM_WIDTH=1920, LONGFORM_HEIGHT=1080, LONGFORM_FPS=10, DETECTED_ENCODER="libx264", NVENC_PARAMS=[]))
    text = "إِنَّهُۥ هُوَ ٱلسَّمِيعُ ٱلْبَصِيرُ"
    assert ns["_clean_arabic"](text) == text
    output = tmp_path / "segment.mkv"
    duration = ns["_render_ayah_segment"](str(audio_path), text, 1, "Synthetic", "Synthetic",
        str(background_path), str(output), 0.4, fade_in=0.2, fade_out=0.2, padding_after=0.2)
    assert duration == pytest.approx(0.6)
    with VideoFileClip(str(output)) as clip:
        samples = clip.audio.get_frame(np.arange(0.30, 0.38, 1 / 44100))
        assert np.sqrt(np.mean(samples ** 2)) > 0.12
    second = tmp_path / "second.mkv"
    ns["_render_ayah_segment"](str(audio_path), text, 2, "Synthetic", "Synthetic",
        str(background_path), str(second), 0.4, fade_in=0, fade_out=0, padding_after=0.2,
        background_offset=0.1)
    concat = tmp_path / "concat.txt"
    concat.write_text("".join(f"file '{path.as_posix()}'\n" for path in (output, second)), encoding="utf-8")
    final = tmp_path / "joined.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    str(final)], check=True, capture_output=True, text=True, timeout=60)
    assert utility["verify_media_streams"](final, 1.2, 1920, 1080)["audio_duration"] == pytest.approx(1.2, abs=0.15)
    with VideoFileClip(str(final)) as clip:
        samples = clip.audio.get_frame(np.arange(0.70, 0.78, 1 / 44100))
        assert np.sqrt(np.mean(samples ** 2)) > 0.12
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(final), "-f", "null", "-"],
                   check=True, capture_output=True, text=True, timeout=60)
    assert not list(tmp_path.glob("_overlay_*.png"))


@pytest.mark.slow
def test_long_karaoke_states_keep_current_word_inside_frame(tmp_path):
    from PIL import Image
    from playwright.sync_api import sync_playwright
    ns = definitions("core/karaoke_renderer.py", {"base64": base64, "VIDEO_WIDTH": 1080, "VIDEO_HEIGHT": 1920})
    tree = ast.parse((ROOT / "core/karaoke_renderer.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_HTML" for t in node.targets):
            ns["_HTML"] = ast.literal_eval(node.value)
    words = ["كَلِمَةٌ"] * 130
    style = ns["KaraokeStyle"](font_path=ROOT / "assets/fonts/amiri/Amiri-Bold.ttf", font_size=72)
    html = ns["_build_html"](words, style)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.set_content(html)
            page.evaluate("document.fonts.ready")
            if "_prepare_pages" in ns:
                ns["_prepare_pages"](page, len(words), style)
            for index in (0, 64, 129):
                if "_activate_word" in ns:
                    ns["_activate_word"](page, index)
                bounds = page.locator(f"#w{index}").bounding_box()
                assert bounds is not None
                assert bounds["y"] >= 0
                assert bounds["y"] + bounds["height"] <= 1920
        finally:
            browser.close()
