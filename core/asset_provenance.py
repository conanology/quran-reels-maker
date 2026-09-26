"""Bounded verified background downloads and truthful source/review metadata."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import requests
from core.runtime_safety import atomic_write_json, exclusive_lock


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_background(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "stream=codec_type:format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    if not 0 < duration <= 600 or not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
        raise ValueError("Background is invalid or exceeds ten-minute asset limit")
    return duration


def get_asset_provenance(path):
    path = Path(path)
    source = {"provider": "local", "filename": path.name, "license_review_required": True}
    sidecar = Path(str(path) + ".source.json")
    if sidecar.is_file():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            source.update(data)
    source["sha256"] = checksum(path)
    from core.person_detector import inspect_people
    source["people_inspection"] = inspect_people(path) if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} else {
        "status": "unchecked", "reason": "Still image requires visual review"}
    source["content_review_required"] = True
    return source


def download_background_asset(output_path, download_url, source):
    """Never return existence-only or partial cache entries; retain source checksum."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(str(output_path) + ".source.json")
    with exclusive_lock(output_path.parent / ".background_download.lock"), exclusive_lock(Path(str(output_path) + ".lock")):
        if output_path.is_file() and source_path.is_file():
            try:
                cached = json.loads(source_path.read_text(encoding="utf-8"))
                if cached.get("download_url") == download_url and cached.get("sha256") == checksum(output_path):
                    validate_background(output_path)
                    return output_path
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        if not output_path.exists() and len(list(output_path.parent.glob("*.mp4"))) >= 20:
            raise ValueError("Background cache is full; retain active assets and explicitly archive unused ones")
        fd, name = tempfile.mkstemp(prefix="background_", suffix=".part", dir=output_path.parent)
        temporary = Path(name)
        try:
            deadline = time.monotonic() + 180
            with os.fdopen(fd, "wb") as handle, requests.get(download_url, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024 * 1024 or time.monotonic() > deadline:
                        raise ValueError("Background exceeded download size/time bound")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            duration = validate_background(temporary)
            source = dict(source, download_url=download_url, duration_seconds=duration,
                          sha256=checksum(temporary), license_review_required=True)
            os.replace(temporary, output_path)
            atomic_write_json(source_path, source)
            return output_path
        finally:
            temporary.unlink(missing_ok=True)
