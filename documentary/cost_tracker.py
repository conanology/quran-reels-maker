"""
Per-episode API usage and cost tracking for the documentary pipeline.

This tracks all GenAI API calls made through ``documentary.api_client`` and writes a
machine-readable report to ``api_cost_report.json`` in the episode output folder.

Important:
- Google APIs do not always return billing-grade cost data in responses.
- This module records *actual call counts/usage metadata where available* and computes
  an estimated USD cost using configurable rates from environment variables.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from documentary.config import (
    DOCUMENTARY_COST_TRACKING_ENABLED,
    DOCUMENTARY_COST_TEXT_INPUT_PER_1M_TOKENS,
    DOCUMENTARY_COST_TEXT_OUTPUT_PER_1M_TOKENS,
    DOCUMENTARY_COST_TTS_PER_1K_CHARS,
    DOCUMENTARY_COST_IMAGE_PER_IMAGE,
    DOCUMENTARY_COST_VEO_PER_SECOND,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class _EpisodeCostState:
    episode_dir: Path
    episode_number: int | None = None
    episode_title: str = ""
    started_at_utc: str = field(default_factory=_now_iso)
    status: str = "running"
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class APICostTracker:
    def __init__(self) -> None:
        self._enabled = bool(DOCUMENTARY_COST_TRACKING_ENABLED)
        self._lock = threading.Lock()
        self._state: _EpisodeCostState | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_episode(self, episode_dir: Path, *, episode_number: int | None = None, episode_title: str = "") -> None:
        if not self._enabled:
            return
        with self._lock:
            self._state = _EpisodeCostState(
                episode_dir=Path(episode_dir),
                episode_number=episode_number,
                episode_title=episode_title or "",
            )
            self._flush_locked()

    def record_event(
        self,
        *,
        category: str,
        operation: str,
        model: str,
        duration_seconds: float | None = None,
        units: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        estimated_cost_usd: float | None = None,
        cache_hit: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._state is None:
                return
            event = {
                "timestamp_utc": _now_iso(),
                "category": category,
                "operation": operation,
                "model": model,
                "cache_hit": bool(cache_hit),
            }
            if duration_seconds is not None:
                event["duration_seconds"] = round(float(duration_seconds), 3)
            if units:
                event["units"] = units
            if usage:
                event["usage"] = usage
            if estimated_cost_usd is not None:
                event["estimated_cost_usd"] = round(float(estimated_cost_usd), 8)
            if metadata:
                event["metadata"] = metadata
            self._state.events.append(event)
            self._flush_locked()

    def record_cache_hit(self, *, category: str, operation: str, model: str, metadata: dict[str, Any] | None = None) -> None:
        self.record_event(
            category=category,
            operation=operation,
            model=model,
            cache_hit=True,
            metadata=metadata or {},
            estimated_cost_usd=0.0,
        )

    def finalize_episode(self, *, status: str = "completed", error: str | None = None) -> Path | None:
        if not self._enabled:
            return None
        with self._lock:
            if self._state is None:
                return None
            self._state.status = status
            self._state.error = error
            path = self._flush_locked()
            return path

    # ----- helpers -----

    def _totals_from_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        totals: dict[str, Any] = {
            "estimated_cost_usd": 0.0,
            "api_calls": 0,
            "cache_hits": 0,
            "by_category": {},
            "usage": {
                "text_prompt_tokens": 0,
                "text_output_tokens": 0,
                "text_total_tokens": 0,
                "tts_input_chars": 0,
                "image_requests": 0,
                "video_requested_seconds": 0.0,
                "video_returned_clips": 0,
            },
        }
        for ev in events:
            totals["api_calls"] += 1
            if ev.get("cache_hit"):
                totals["cache_hits"] += 1
            totals["estimated_cost_usd"] += float(ev.get("estimated_cost_usd") or 0.0)
            cat = str(ev.get("category") or "unknown")
            by_cat = totals["by_category"].setdefault(cat, {"calls": 0, "estimated_cost_usd": 0.0})
            by_cat["calls"] += 1
            by_cat["estimated_cost_usd"] += float(ev.get("estimated_cost_usd") or 0.0)

            units = ev.get("units") or {}
            usage = totals["usage"]
            usage["text_prompt_tokens"] += int(units.get("prompt_tokens") or 0)
            usage["text_output_tokens"] += int(units.get("output_tokens") or 0)
            usage["text_total_tokens"] += int(units.get("total_tokens") or 0)
            usage["tts_input_chars"] += int(units.get("input_chars") or 0)
            usage["image_requests"] += int(units.get("image_count") or 0)
            usage["video_requested_seconds"] += float(units.get("video_seconds_requested") or 0.0)
            usage["video_returned_clips"] += int(units.get("returned_clips") or 0)

        totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 8)
        totals["usage"]["video_requested_seconds"] = round(totals["usage"]["video_requested_seconds"], 3)
        for cat_vals in totals["by_category"].values():
            cat_vals["estimated_cost_usd"] = round(cat_vals["estimated_cost_usd"], 8)
        return totals

    def _report_dict_locked(self) -> dict[str, Any]:
        assert self._state is not None
        events = list(self._state.events)
        return {
            "generated_at_utc": _now_iso(),
            "tracking_enabled": self._enabled,
            "pricing_mode": "estimated_from_configured_rates",
            "pricing_rates_usd": {
                "text_input_per_1m_tokens": DOCUMENTARY_COST_TEXT_INPUT_PER_1M_TOKENS,
                "text_output_per_1m_tokens": DOCUMENTARY_COST_TEXT_OUTPUT_PER_1M_TOKENS,
                "tts_per_1k_chars": DOCUMENTARY_COST_TTS_PER_1K_CHARS,
                "image_per_image": DOCUMENTARY_COST_IMAGE_PER_IMAGE,
                "veo_per_second": DOCUMENTARY_COST_VEO_PER_SECOND,
            },
            "episode": {
                "number": self._state.episode_number,
                "title": self._state.episode_title,
                "output_dir": str(self._state.episode_dir),
                "started_at_utc": self._state.started_at_utc,
                "status": self._state.status,
                "error": self._state.error,
            },
            "totals": self._totals_from_events(events),
            "events": events,
        }

    def _flush_locked(self) -> Path | None:
        if self._state is None:
            return None
        self._state.episode_dir.mkdir(parents=True, exist_ok=True)
        path = self._state.episode_dir / "api_cost_report.json"
        try:
            path.write_text(
                json.dumps(self._report_dict_locked(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not write api_cost_report.json: %s", exc)
            return None
        return path


_TRACKER: APICostTracker | None = None


def get_cost_tracker() -> APICostTracker:
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = APICostTracker()
    return _TRACKER

