"""Local compiler boundaries. Importing this module performs no I/O."""
from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("QURAN_COMPILER_DATA_DIR", BASE_DIR / "data" / "jobs")).resolve()
FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "Amiri-Regular.ttf"
MAX_CLIPS = 20
MAX_CLIP_SECONDS = 600
MAX_JOB_SECONDS = 3600
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_JOB_BYTES = 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * MAX_JOB_BYTES
PROCESS_TIMEOUT = 1800

class JobCancelled(RuntimeError):
    pass

def check_cancel(cancel=None):
    if cancel is not None and cancel.is_set():
        raise JobCancelled("Job cancelled. You can retry with the same selection.")

def video_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        raise ValueError("Video ID must be an 11-character YouTube identifier.")
    return value

def output_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.mp4", value):
        raise ValueError("Use a simple MP4 name with letters, numbers, hyphens or underscores.")
    if value.rsplit(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1,10)), *(f"LPT{i}" for i in range(1,10))}:
        raise ValueError("This filename is reserved by the operating system.")
    return value

def contained(root: Path, *parts: str) -> Path:
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Path is outside the job directory.")
    return target

def channel_url(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"@[A-Za-z0-9_.-]{3,100}", value):
        return f"https://www.youtube.com/{value}/shorts"
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com"} or parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Enter a YouTube channel handle or an HTTPS youtube.com channel URL.")
    path = parsed.path.rstrip("/")
    if path.endswith("/shorts"):
        path = path[:-7]
    if not re.fullmatch(r"/(?:@[A-Za-z0-9_.-]{3,100}|channel/UC[A-Za-z0-9_-]{22}|(?:c|user)/[A-Za-z0-9_.-]{1,100})", path):
        raise ValueError("Use a channel URL, not a playlist, watch URL or arbitrary address.")
    return f"https://www.youtube.com{path}/shorts"

def transition(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 5:
        raise ValueError("Visual transition must be a finite number from 0 to 5 seconds.")
    return value

def atomic_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)

def child_environment():
    # yt-dlp/FFmpeg do not inherit API keys, OAuth settings, cookies or proxy variables.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "PYTHONPATH"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}

def run_process(args, *, timeout=PROCESS_TIMEOUT, cancel=None, max_stdout=4 * 1024 * 1024, monitor=None):
    """Bounded subprocess output and lifetime; cancellation also reaps the child."""
    check_cancel(cancel)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        proc = subprocess.Popen(args, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                env=child_environment(), creationflags=flags, start_new_session=os.name != "nt")
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                check_cancel(cancel)
                if monitor is not None:
                    monitor()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Media operation timed out; retry fewer or shorter clips.")
                if out.tell() > max_stdout or err.tell() > 4 * 1024 * 1024:
                    raise ValueError("Media tool returned too much diagnostic data.")
                time.sleep(0.05)
            if monitor is not None:
                monitor()
            if proc.returncode:
                raise RuntimeError("Media tool failed. Check the selected source, codecs and installed FFmpeg.")
            out.seek(0)
            data = out.read(max_stdout + 1)
            if len(data) > max_stdout:
                raise ValueError("Media response exceeded the size limit.")
            return data.decode("utf-8", errors="replace")
        finally:
            if proc.poll() is None:
                # yt-dlp can spawn a merge/JS helper. Reap only the tree/group
                # rooted at the child this function created, never a named
                # global FFmpeg/Node process.
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == "nt": proc.kill()
                    else: os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=3)
