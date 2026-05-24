"""
Shot-plan schemas for the documentary director layer.

This is the bridge between narrative scenes (30-45s) and editorially directed
shot sequences (3-8s units) used by the visual generation/composition pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


SceneType = Literal["narrative", "quran_verse", "transition", "chapter_card"]
SceneGoal = Literal["setup", "journey", "tension", "revelation", "aftermath", "reflection"]
ShotRole = Literal["hook", "establishing", "medium", "detail", "hero", "symbolic", "transition", "closing"]
SourceStrategy = Literal["auto", "stock", "veo", "image"]


class BeatSpec(BaseModel):
    beat_id: str
    scene_number: int
    order_index: int
    start_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    end_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    duration_seconds: float = 0.0
    text: str
    action: str = ""
    mood: str = ""
    entities: list[str] = Field(default_factory=list)
    visual_intent: str = ""
    forbidden_visuals: list[str] = Field(default_factory=list)


class ShotSpec(BaseModel):
    shot_id: str
    scene_number: int
    order_index: int
    duration_seconds: float
    shot_role: ShotRole
    source_strategy: SourceStrategy = "auto"
    camera_motion: str = "static"
    energy_level: int = Field(default=3, ge=1, le=5)
    prompt: str
    fallback_prompt: str = ""
    continuity_tags: list[str] = Field(default_factory=list)
    forbidden_visuals: list[str] = Field(default_factory=list)
    sacred_text_overlay: bool = False
    quran_ref: str | None = None
    beat_id: str | None = None
    beat_text: str | None = None
    beat_start_ratio: float | None = None
    beat_end_ratio: float | None = None
    notes: str = ""


class SceneShotPlan(BaseModel):
    scene_number: int
    scene_type: SceneType = "narrative"
    scene_goal: SceneGoal = "setup"
    target_duration_seconds: float
    original_visual_type: Literal["video", "image"] = "video"
    narration_excerpt: str = ""
    continuity_tags: list[str] = Field(default_factory=list)
    source_quota_targets: dict[str, int] = Field(default_factory=dict)
    beats: list[BeatSpec] = Field(default_factory=list)
    shots: list[ShotSpec] = Field(default_factory=list)


class EpisodeShotPlan(BaseModel):
    episode_number: int
    episode_title: str
    style_profile: str = "cinematic_historical_v1"
    generated_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    planned_total_duration_seconds: float = 0.0
    scenes: list[SceneShotPlan] = Field(default_factory=list)


class SceneBeatPlan(BaseModel):
    scene_number: int
    target_duration_seconds: float
    narration_excerpt: str = ""
    beats: list[BeatSpec] = Field(default_factory=list)


class EpisodeBeatPlan(BaseModel):
    episode_number: int
    episode_title: str
    style_profile: str = "cinematic_historical_v1"
    generated_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    scenes: list[SceneBeatPlan] = Field(default_factory=list)
