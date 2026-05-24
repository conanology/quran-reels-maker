"""
Background History - Persist and enforce anti-repeat background selection.
"""
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from config.settings import DATABASE_DIR


_PEXELS_FILE_RE = re.compile(r"^pexels_(\d+)_", re.IGNORECASE)
_DEFAULT_COOLDOWN = max(1, int(os.getenv("BACKGROUND_REPEAT_COOLDOWN", "18")))
_MAX_HISTORY_ENTRIES = max(50, int(os.getenv("BACKGROUND_HISTORY_MAX_ENTRIES", "500")))
_HISTORY_PATH = DATABASE_DIR / "background_usage_history.json"


def _load_history() -> List[Dict[str, Any]]:
    if not _HISTORY_PATH.exists():
        return []
    try:
        with _HISTORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception as exc:
        logger.warning(f"Could not read background history: {exc}")
    return []


def _save_history(history: List[Dict[str, Any]]) -> None:
    try:
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        trimmed = history[-_MAX_HISTORY_ENTRIES:]
        with _HISTORY_PATH.open("w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"Could not write background history: {exc}")


def background_key_from_path(path: Path) -> str:
    """
    Normalize a background key.
    For pexels files, key by stable video id (e.g., pexels:35178805).
    """
    name = path.name.lower()
    match = _PEXELS_FILE_RE.match(name)
    if match:
        return f"pexels:{match.group(1)}"
    return f"file:{name}"


def background_key_from_pexels_id(video_id: int | str) -> str:
    return f"pexels:{int(video_id)}"


def get_recent_background_keys(cooldown: int = _DEFAULT_COOLDOWN) -> set[str]:
    history = _load_history()
    recent = history[-max(1, int(cooldown)) :]
    return {
        str(entry.get("key", "")).strip()
        for entry in recent
        if str(entry.get("key", "")).strip()
    }


def _build_last_seen_index(history: List[Dict[str, Any]]) -> Dict[str, int]:
    last_seen: Dict[str, int] = {}
    for i, entry in enumerate(history):
        key = str(entry.get("key", "")).strip()
        if key:
            last_seen[key] = i
    return last_seen


def pick_background_candidate(
    candidates: Sequence[Path],
    cooldown: int = _DEFAULT_COOLDOWN,
) -> Optional[Path]:
    """
    Pick a background while avoiding recently used keys.
    If all are in cooldown, pick the least recently used candidate.
    """
    if not candidates:
        return None

    history = _load_history()
    last_seen = _build_last_seen_index(history)
    recent_keys = get_recent_background_keys(cooldown)

    eligible = [p for p in candidates if background_key_from_path(p) not in recent_keys]
    if eligible:
        return random.choice(eligible)

    # Cooldown saturated: prefer the least recently used option.
    ranked = sorted(
        candidates,
        key=lambda p: last_seen.get(background_key_from_path(p), -1),
    )
    oldest_seen = last_seen.get(background_key_from_path(ranked[0]), -1)
    oldest_group = [
        p
        for p in ranked
        if last_seen.get(background_key_from_path(p), -1) == oldest_seen
    ]
    return random.choice(oldest_group)


def pick_pexels_video_candidate(
    videos: Sequence[Dict[str, Any]],
    cooldown: int = _DEFAULT_COOLDOWN,
) -> Optional[Dict[str, Any]]:
    """
    Pick a Pexels video metadata object while avoiding recently used video ids.
    """
    if not videos:
        return None

    history = _load_history()
    last_seen = _build_last_seen_index(history)
    recent_keys = get_recent_background_keys(cooldown)

    def key_for(video: Dict[str, Any]) -> str:
        return background_key_from_pexels_id(video.get("id", 0))

    eligible = [v for v in videos if key_for(v) not in recent_keys]
    if eligible:
        return random.choice(eligible)

    ranked = sorted(videos, key=lambda v: last_seen.get(key_for(v), -1))
    oldest_seen = last_seen.get(key_for(ranked[0]), -1)
    oldest_group = [v for v in ranked if last_seen.get(key_for(v), -1) == oldest_seen]
    return random.choice(oldest_group)


def record_background_usage(path: Path, source: str = "") -> None:
    history = _load_history()
    key = background_key_from_path(path)
    history.append(
        {
            "key": key,
            "path": str(path).replace("\\", "/"),
            "source": source,
            "used_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_history(history)
