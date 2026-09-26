"""Bounded local FFmpeg compiler with job-owned files and preserved recitation audio."""
from __future__ import annotations
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from .common import (DATA_DIR, FONT_PATH, MAX_CLIPS, MAX_CLIP_SECONDS, MAX_JOB_SECONDS,
                     MAX_OUTPUT_BYTES, check_cancel, contained, output_name, video_id,
                     transition, atomic_json, run_process)


def probe_media(path, *, cancel=None, require_audio=True):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_OUTPUT_BYTES:
        raise ValueError("Media is missing, empty or exceeds the size limit.")
    data = json.loads(run_process(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], timeout=20, cancel=cancel, max_stdout=65536))
    duration = float(data.get("format", {}).get("duration", 0))
    streams = data.get("streams", [])
    visual = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not math.isfinite(duration) or duration <= 0 or not visual or visual.get("width", 0) < 1 or visual.get("height", 0) < 1:
        raise ValueError("Media has no valid video stream or duration.")
    if require_audio and not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError("Selected clip has no recitation audio stream.")
    return duration


def get_video_duration(video_path):
    return probe_media(video_path)


def format_timestamp(seconds):
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _filter_path(path):
    return str(Path(path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def process_single_clip(input_path, output_path, reciter_name, transition_duration=1.5, *, cancel=None):
    duration = probe_media(input_path, cancel=cancel)
    if duration > MAX_CLIP_SECONDS:
        raise ValueError("Clip exceeds the ten-minute limit.")
    if not FONT_PATH.is_file():
        raise FileNotFoundError("Bundled Amiri font is missing; restore backend/assets/fonts/Amiri-Regular.ttf.")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text_path = output_path.with_suffix(".txt")
    text_path.write_text(reciter_name, encoding="utf-8")
    fade = min(transition(transition_duration), duration / 2)
    filters = (
        "[0:v]split=2[background][foreground];"
        "[background]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=40:5[bg];"
        "[foreground]scale=1920:1080:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[ov];"
        f"[ov]drawtext=fontfile='{_filter_path(FONT_PATH)}':textfile='{_filter_path(text_path)}':"
        "fontcolor=white:fontsize=50:borderw=3:bordercolor=black@0.8:x=(w-text_w)/2:y=h-160"
    )
    if fade:
        filters += f",fade=t=in:st=0:d={fade},fade=t=out:st={duration-fade}:d={fade}"
    filters += "[v]"
    try:
        # Audio is not faded, shortened, sped up or normalized. Visual fades only.
        run_process(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(input_path), "-filter_complex", filters,
                     "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast", "-threads", "2", "-filter_complex_threads", "1",
                     "-c:a", "aac", "-pix_fmt", "yuv420p", "-r", "30", "-ar", "44100", "-ac", "2", "-fs", str(MAX_OUTPUT_BYTES), str(output_path)], cancel=cancel)
        rendered = probe_media(output_path, cancel=cancel)
        if abs(rendered-duration) > 0.25:
            raise ValueError("Rendered duration does not match the complete source clip.")
        return rendered
    finally:
        text_path.unlink(missing_ok=True)


def compile_longform(clips, output_filename="final_compilation.mp4", transition_duration=1.5, progress_callback=None, *, job_dir=None, cancel=None):
    if not 1 <= len(clips) <= MAX_CLIPS:
        raise ValueError(f"Choose between 1 and {MAX_CLIPS} clips.")
    name = output_name(output_filename)
    fade = transition(transition_duration)
    ids = [video_id(c["video_id"]) for c in clips]
    if len(set(ids)) != len(ids):
        raise ValueError("Each source clip may be included only once per compilation.")
    for clip in clips:
        if not clip.get("attribution_verified") or not str(clip.get("reciter_name", "")).strip() or not str(clip.get("surah_name", "")).strip():
            raise ValueError("Verify the reciter and actual Surah/verse coverage of every selected clip.")
    root = Path(job_dir or DATA_DIR).resolve()
    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = contained(output_dir, name)
    if final_path.exists() or final_path.with_suffix(".mp4.json").exists():
        raise FileExistsError("This job already has an output; create a new job to retry.")
    chapters, accumulated = [], 0.0
    try:
        with TemporaryDirectory(prefix="compile-", dir=root) as temp_name:
            temp = Path(temp_name)
            processed = []
            for idx, clip in enumerate(clips):
                check_cancel(cancel)
                raw = contained(root / "downloads", f"{ids[idx]}.mp4")
                if progress_callback:
                    progress_callback(idx, len(clips)+1, f"Processing clip {idx+1}/{len(clips)}")
                rendered = temp / f"processed_{idx:03d}.mp4"
                duration = process_single_clip(raw, rendered, clip["reciter_name"], fade, cancel=cancel)
                accumulated += duration
                if accumulated > MAX_JOB_SECONDS:
                    raise ValueError("Compilation exceeds the one-hour limit.")
                chapters.append({"timestamp": format_timestamp(accumulated-duration), "seconds": accumulated-duration,
                                 "title": f"{clip['surah_name']} — {clip['reciter_name']}",
                                 "source": f"https://www.youtube.com/watch?v={ids[idx]}", "attribution_verified": True})
                processed.append(rendered)
                if sum(p.stat().st_size for p in processed) > MAX_OUTPUT_BYTES:
                    raise ValueError("Processed clips exceed the 2 GB work-space budget.")
            manifest = temp / "concat.txt"
            # Generated filenames only, and a relative concat list avoids path quoting.
            manifest.write_text("".join(f"file '{p.name}'\n" for p in processed), encoding="utf-8")
            if progress_callback:
                progress_callback(len(clips), len(clips)+1, "Joining and validating complete output")
            run_process(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "concat", "-safe", "1", "-i", str(manifest), "-c", "copy", "-fs", str(MAX_OUTPUT_BYTES), str(final_path)], cancel=cancel)
            actual = probe_media(final_path, cancel=cancel)
            if abs(actual-accumulated) > max(0.3, len(clips)*0.1):
                raise ValueError("Final duration differs from included source coverage.")
            description = "Quran recitation clips — reviewed source labels\n\n" + "\n".join(f"{c['timestamp']} — {c['title']}" for c in chapters)
            description += f"\n\nVisual fades up to {fade:g} seconds; recitation audio retained without fades.\nSource clips and their selected coverage are listed above; this compilation does not claim full-Surah coverage."
            result = {"output_filename": name, "duration_seconds": actual, "duration_formatted": format_timestamp(actual), "chapters": chapters,
                      "description": description, "recommended_title": "Quran Recitation Clips | Reviewed Compilation", "coverage": "selected clips", "audio_preserved": True}
            atomic_json(final_path.with_suffix(".mp4.json"), result)
            return result
    except BaseException:
        final_path.unlink(missing_ok=True)
        final_path.with_suffix(".mp4.json").unlink(missing_ok=True)
        raise
