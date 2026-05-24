"""
Quality validation utilities for documentary assets and final videos.

Provides lightweight, best-effort checks to prevent obviously broken outputs:
- fully/mostly black videos
- invalid dimensions/durations
- probable human depictions (via OpenCV HOG if available)
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_BLACK_RE = re.compile(
    r"black_start:(?P<start>[0-9.]+)\s+black_end:(?P<end>[0-9.]+)\s+black_duration:(?P<dur>[0-9.]+)"
)
_FREEZE_START_RE = re.compile(r"freeze_start:\s*(?P<start>[0-9.]+)")
_FREEZE_END_RE = re.compile(r"freeze_end:\s*(?P<end>[0-9.]+)")
_FREEZE_DUR_RE = re.compile(r"freeze_duration:\s*(?P<dur>[0-9.]+)")


@dataclass
class ValidationResult:
    ok: bool
    kind: str
    path: str
    reasons: list[str]
    warnings: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_json_command(args: list[str]) -> dict[str, Any] | None:
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return json.loads(cp.stdout)
    except Exception as exc:
        logger.debug("Command failed (%s): %s", " ".join(args[:2]), exc)
        return None


def ffprobe_media(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    return _run_json_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,width,height,duration,bit_rate",
            "-of",
            "json",
            str(path),
        ]
    )


def detect_black_segments(path: Path, *, pic_th: float = 0.98, min_dur: float = 0.5) -> list[dict[str, float]]:
    """Return blackdetect segments from ffmpeg output (best-effort)."""
    try:
        cp = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(path),
                "-vf",
                f"blackdetect=d={min_dur}:pic_th={pic_th}",
                "-an",
                "-f",
                "null",
                os.devnull,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        logger.debug("blackdetect unavailable for %s: %s", path, exc)
        return []

    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    segments = []
    for m in _BLACK_RE.finditer(text):
        segments.append(
            {
                "start": float(m.group("start")),
                "end": float(m.group("end")),
                "duration": float(m.group("dur")),
            }
        )
    return segments


def detect_freeze_segments(path: Path, *, noise: float = 0.002, min_dur: float = 0.8) -> list[dict[str, float]]:
    """Return freezedetect segments from ffmpeg output (best-effort)."""
    try:
        cp = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(path),
                "-vf",
                f"freezedetect=n={noise}:d={min_dur}",
                "-an",
                "-f",
                "null",
                os.devnull,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        logger.debug("freezedetect unavailable for %s: %s", path, exc)
        return []

    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    starts = [float(m.group("start")) for m in _FREEZE_START_RE.finditer(text)]
    ends = [float(m.group("end")) for m in _FREEZE_END_RE.finditer(text)]
    durs = [float(m.group("dur")) for m in _FREEZE_DUR_RE.finditer(text)]
    segs: list[dict[str, float]] = []
    for idx, start in enumerate(starts):
        dur = durs[idx] if idx < len(durs) else 0.0
        end = ends[idx] if idx < len(ends) else (start + dur if dur > 0 else start)
        segs.append({"start": start, "end": end, "duration": max(0.0, dur or (end - start))})
    return segs


def _image_has_people_best_effort(path: Path) -> bool:
    """Best-effort image people detection using existing HOG detector if available."""
    try:
        import cv2
        from core import person_detector as pd

        if not getattr(pd, "DETECTION_AVAILABLE", False):
            return False
        frame = cv2.imread(str(path))
        if frame is None:
            return False
        return bool(pd._detect_people_in_frame(frame))  # reuse existing detector
    except Exception as exc:
        logger.debug("Image person detection failed for %s: %s", path, exc)
        return False


def _video_has_people_best_effort(path: Path) -> bool:
    try:
        from core.person_detector import has_people

        return bool(has_people(Path(path), num_frames=5))
    except Exception as exc:
        logger.debug("Video person detection failed for %s: %s", path, exc)
        return False


def validate_image_asset(path: Path) -> ValidationResult:
    path = Path(path)
    reasons: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not path.exists():
        return ValidationResult(False, "image", str(path), ["file_missing"], [], {})

    try:
        img = Image.open(path).convert("RGB")
        arr = np.array(img)
        metrics["width"] = int(arr.shape[1])
        metrics["height"] = int(arr.shape[0])
        metrics["mean_luma"] = float(arr.mean())
        metrics["max_pixel"] = int(arr.max())
    except Exception as exc:
        return ValidationResult(False, "image", str(path), [f"image_read_failed:{exc}"], [], {})

    if metrics["width"] < 320 or metrics["height"] < 180:
        reasons.append("image_too_small")

    # Only reject truly black/empty images (do not reject dark night scenes)
    if metrics["max_pixel"] <= 5 or metrics["mean_luma"] < 2.0:
        reasons.append("image_near_black")

    if _image_has_people_best_effort(path):
        reasons.append("people_detected")

    return ValidationResult(not reasons, "image", str(path), reasons, warnings, metrics)


def validate_video_asset(path: Path, *, allow_intro_outro_black: bool = False) -> ValidationResult:
    path = Path(path)
    reasons: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not path.exists():
        return ValidationResult(False, "video", str(path), ["file_missing"], [], {})

    probe = ffprobe_media(path)
    if not probe:
        return ValidationResult(False, "video", str(path), ["ffprobe_failed"], [], {})

    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    metrics["size_bytes"] = int(float(fmt.get("size", 0) or 0))
    metrics["duration"] = float(fmt.get("duration", 0) or 0)
    metrics["bit_rate"] = int(float(fmt.get("bit_rate", 0) or 0))
    metrics["video_bit_rate"] = int(float((vstream or {}).get("bit_rate", 0) or 0))
    metrics["audio_bit_rate"] = int(float((astream or {}).get("bit_rate", 0) or 0)) if astream else 0
    metrics["width"] = int((vstream or {}).get("width", 0) or 0)
    metrics["height"] = int((vstream or {}).get("height", 0) or 0)

    if not vstream:
        reasons.append("missing_video_stream")
        return ValidationResult(False, "video", str(path), reasons, warnings, metrics)

    if metrics["duration"] < 1.0:
        reasons.append("duration_too_short")

    black_segments = detect_black_segments(path)
    metrics["black_segments"] = black_segments
    total_black = sum(s["duration"] for s in black_segments)
    metrics["black_total_s"] = round(total_black, 3)
    if metrics["duration"] > 0:
        metrics["black_ratio"] = round(total_black / metrics["duration"], 4)
    else:
        metrics["black_ratio"] = 0.0

    if allow_intro_outro_black:
        # Permit title/outro cards; reject if black dominates or entire body is black.
        if metrics["black_ratio"] > 0.35:
            reasons.append("video_mostly_black")
        if metrics["black_ratio"] > 0.90:
            reasons.append("video_effectively_all_black")
    else:
        if metrics["black_ratio"] > 0.90:
            reasons.append("video_effectively_all_black")

    if _video_has_people_best_effort(path):
        reasons.append("people_detected")

    freeze_segments = detect_freeze_segments(path)
    metrics["freeze_segments"] = freeze_segments
    total_freeze = sum(s["duration"] for s in freeze_segments)
    metrics["freeze_total_s"] = round(total_freeze, 3)
    if metrics["duration"] > 0:
        metrics["freeze_ratio"] = round(total_freeze / metrics["duration"], 4)
    else:
        metrics["freeze_ratio"] = 0.0
    if metrics["freeze_ratio"] > 0.75:
        warnings.append("very_high_freeze_ratio")
    elif metrics["freeze_ratio"] > 0.35:
        warnings.append("high_freeze_ratio")

    # Low bitrate is not a hard failure alone, but useful signal.
    if metrics["width"] >= 1280 and metrics["video_bit_rate"] and metrics["video_bit_rate"] < 120_000:
        warnings.append("very_low_video_bitrate")

    return ValidationResult(not reasons, "video", str(path), reasons, warnings, metrics)


def validate_visual_asset(path: Path) -> ValidationResult:
    path = Path(path)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return validate_image_asset(path)
    return validate_video_asset(path, allow_intro_outro_black=False)


def validate_final_video(path: Path) -> ValidationResult:
    return validate_video_asset(path, allow_intro_outro_black=True)


def build_episode_quality_report(episode_dir: Path) -> dict[str, Any]:
    """Generate a compact quality report for existing episode artifacts."""
    episode_dir = Path(episode_dir)
    report: dict[str, Any] = {
        "episode_dir": str(episode_dir),
        "assets": [],
        "shot_assets": [],
        "final_video": None,
    }

    scenes_dir = episode_dir / "scenes"
    if scenes_dir.exists():
        for p in sorted(scenes_dir.iterdir()):
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4"}:
                continue
            report["assets"].append(validate_visual_asset(p).to_dict())

    shots_dir = episode_dir / "shots"
    if shots_dir.exists():
        for p in sorted(shots_dir.iterdir()):
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4"}:
                continue
            report["shot_assets"].append(validate_visual_asset(p).to_dict())

    final_path = episode_dir / "final_video.mp4"
    if final_path.exists():
        report["final_video"] = validate_final_video(final_path).to_dict()

    return report


def write_episode_quality_report(episode_dir: Path) -> Path:
    episode_dir = Path(episode_dir)
    report = build_episode_quality_report(episode_dir)
    out_path = episode_dir / "quality_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Quality report written: %s", out_path)
    return out_path
