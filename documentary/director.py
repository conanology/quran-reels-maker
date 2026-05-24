"""
Director layer (v1) for converting narrative scenes into a shot plan.

This version is intentionally heuristic and non-destructive: it generates a
`shot_plan.json` artifact for visibility and future integration without
changing the existing render path yet.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from documentary.shot_plan import (
    BeatSpec,
    EpisodeBeatPlan,
    EpisodeShotPlan,
    SceneBeatPlan,
    SceneShotPlan,
    ShotSpec,
)

logger = logging.getLogger(__name__)


_QURAN_MARKERS = re.compile(
    r"\b(qur['’]?\s*an|quran|surah|ayah|ayat|verse|verses|iqra|al-alaq|read in the name)\b",
    re.IGNORECASE,
)
_TEXT_VISUAL_MARKERS = re.compile(
    r"\b(calligraphy|manuscript|scroll|parchment|script|lettering|typography|legible text)\b",
    re.IGNORECASE,
)


class Director:
    """Heuristic documentary director for shot planning."""

    def __init__(self, style_profile: str = "cinematic_historical_v1"):
        self.style_profile = style_profile

    def plan_episode(self, script, *, episode_number: int, episode_title: str) -> EpisodeShotPlan:
        scenes = getattr(script, "scenes", []) or []
        plan_scenes: list[SceneShotPlan] = []
        total = 0.0
        beat_plan = self.build_beat_plan(
            script,
            episode_number=episode_number,
            episode_title=episode_title,
        )
        beat_map = {scene.scene_number: scene.beats for scene in beat_plan.scenes}

        for scene in scenes:
            scene_plan = self._plan_scene(scene, beats=beat_map.get(int(getattr(scene, "scene_number", 0) or 0), []))
            plan_scenes.append(scene_plan)
            total += sum(max(0.25, shot.duration_seconds) for shot in scene_plan.shots)

        return EpisodeShotPlan(
            episode_number=episode_number,
            episode_title=episode_title,
            style_profile=self.style_profile,
            planned_total_duration_seconds=round(total, 2),
            scenes=plan_scenes,
        )

    def build_beat_plan(self, script, *, episode_number: int, episode_title: str) -> EpisodeBeatPlan:
        scenes = getattr(script, "scenes", []) or []
        beat_scenes: list[SceneBeatPlan] = []
        for scene in scenes:
            scene_number = int(getattr(scene, "scene_number", 0) or 0)
            target_dur = float(getattr(scene, "duration_target_seconds", 40.0) or 40.0)
            beats = self._plan_scene_beats(scene)
            beat_scenes.append(
                SceneBeatPlan(
                    scene_number=scene_number,
                    target_duration_seconds=target_dur,
                    narration_excerpt=(
                        (narr[:200] + "...") if len((narr := str(getattr(scene, "narration", "") or ""))) > 200 else narr
                    ),
                    beats=beats,
                )
            )
        return EpisodeBeatPlan(
            episode_number=episode_number,
            episode_title=episode_title,
            style_profile=self.style_profile,
            scenes=beat_scenes,
        )

    def save_shot_plan(self, plan: EpisodeShotPlan, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "shot_plan.json"
        path.write_text(
            json.dumps(plan.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Shot plan saved: %s", path)
        return path

    def save_beat_plan(self, plan: EpisodeBeatPlan, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "beat_plan.json"
        path.write_text(
            json.dumps(plan.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Beat plan saved: %s", path)
        return path

    # ----- scene planning -----

    def _plan_scene_beats(self, scene) -> list[BeatSpec]:
        scene_number = int(getattr(scene, "scene_number", 0) or 0)
        narration = str(getattr(scene, "narration", "") or "").strip()
        target_dur = float(getattr(scene, "duration_target_seconds", 40.0) or 40.0)
        parts = self._split_narration_into_beats(narration)
        if not parts:
            parts = [narration] if narration else ["Atmospheric transition."]

        word_counts = [max(1, len(p.split())) for p in parts]
        total_words = sum(word_counts) or 1
        raw_durs = [target_dur * (wc / total_words) for wc in word_counts]
        # Clamp then redistribute lightly
        durs = [max(2.0, min(9.0, d)) for d in raw_durs]
        diff = target_dur - sum(durs)
        idx = 0
        while abs(diff) > 0.05 and durs:
            step = 0.25 if diff > 0 else -0.25
            j = idx % len(durs)
            nxt = durs[j] + step
            if 1.5 <= nxt <= 10.0:
                durs[j] = nxt
                diff -= step
            idx += 1
            if idx > 200:
                break

        beats: list[BeatSpec] = []
        cursor = 0.0
        for i, (text, dur) in enumerate(zip(parts, durs), start=1):
            start_ratio = cursor / target_dur if target_dur > 0 else 0.0
            cursor += dur
            end_ratio = min(1.0, cursor / target_dur) if target_dur > 0 else 1.0
            action, mood, entities = self._infer_beat_semantics(text)
            visual_intent = self._visual_intent_for_beat(text, action, mood)
            forbidden = self._forbidden_visuals_for_beat(text, action, mood, entities)
            beats.append(
                BeatSpec(
                    beat_id=f"s{scene_number:02d}_b{i:02d}",
                    scene_number=scene_number,
                    order_index=i,
                    start_ratio=round(start_ratio, 4),
                    end_ratio=round(end_ratio, 4),
                    duration_seconds=round(max(1.5, dur), 2),
                    text=text,
                    action=action,
                    mood=mood,
                    entities=entities,
                    visual_intent=visual_intent,
                    forbidden_visuals=forbidden,
                )
            )
        return beats

    def _split_narration_into_beats(self, narration: str) -> list[str]:
        text = (narration or "").strip()
        if not text:
            return []
        # Normalize weird punctuation while preserving references like 96:1-5.
        text = re.sub(r"\s+", " ", text)
        sentence_parts = re.split(r"(?<=[\.\!\?])\s+", text)
        beats: list[str] = []
        for sent in sentence_parts:
            sent = sent.strip(" \u2014-")
            if not sent:
                continue
            if len(sent) <= 120:
                beats.append(sent)
                continue
            # Split long sentences by strong commas / clauses.
            clauses = [c.strip(" ,;") for c in re.split(r";|,\s+(?=(?:and|but|then|while|as|when|before|after)\b)", sent, flags=re.I) if c.strip()]
            if len(clauses) <= 1:
                clauses = [c.strip() for c in re.split(r",\s+", sent) if c.strip()]
            if len(clauses) <= 1:
                beats.append(sent)
            else:
                for c in clauses:
                    if len(c) > 160:
                        # Last fallback: split around em dashes/colons
                        sub = [x.strip(" :-") for x in re.split(r"\s+[-:]\s+|\s+—\s+", c) if x.strip()]
                        beats.extend(sub or [c])
                    else:
                        beats.append(c)
        # Keep a practical range so the beat plan remains useful.
        if len(beats) > 8:
            merged = []
            i = 0
            while i < len(beats):
                chunk = beats[i]
                if i + 1 < len(beats) and len(chunk) < 45:
                    chunk = f"{chunk} {beats[i+1]}".strip()
                    i += 1
                merged.append(chunk)
                i += 1
            beats = merged
        beats = [b for b in beats if b]
        # Merge low-information fragments (e.g., "Now", "the bustling")
        compacted: list[str] = []
        for beat in beats:
            wc = len(beat.split())
            if compacted and (wc <= 2 or len(beat) < 22):
                compacted[-1] = f"{compacted[-1]} {beat}".strip()
            else:
                compacted.append(beat)
        beats = compacted
        # If a fragment still remains first, merge it forward.
        if len(beats) > 1 and (len(beats[0].split()) <= 2 or len(beats[0]) < 20):
            beats[1] = f"{beats[0]} {beats[1]}".strip()
            beats = beats[1:]
        return beats

    def _infer_beat_semantics(self, text: str) -> tuple[str, str, list[str]]:
        t = (text or "").lower()
        action = "describe"
        mood = "neutral"
        if any(k in t for k in ("climb", "journey", "walk", "approach", "ascend", "path")):
            action = "journey"
        elif any(k in t for k in ("revelation", "revealed", "read", "iqra", "angel", "squeezed")):
            action = "revelation"
        elif any(k in t for k in ("fear", "shiver", "tremble", "terrified")):
            action = "fear"
        elif any(k in t for k in ("comfort", "reassure", "calm", "embrace")):
            action = "comfort"
        elif any(k in t for k in ("verses", "quran", "surah", "ayah", "namus")):
            action = "text_reflection"

        if any(k in t for k in ("fear", "darkness", "terror", "tremble", "shivering")):
            mood = "tension"
        elif any(k in t for k in ("light", "revelation", "heavens", "angel", "iqra")):
            mood = "awe"
        elif any(k in t for k in ("comfort", "reassure", "anchor", "faith", "wisdom")):
            mood = "comfort"
        elif any(k in t for k in ("night", "quiet", "solitude", "retreat")):
            mood = "contemplative"

        entities = []
        for token in ("hira", "jabal al-nour", "makkah", "khadija", "namus", "qur'an", "surah", "jibreel", "gabriel"):
            if token in t:
                entities.append(token)
        qref = re.search(r"\b\d{1,3}:\d{1,3}(?:-\d{1,3})?\b", t)
        if qref:
            entities.append(qref.group(0))
        return action, mood, entities

    def _visual_intent_for_beat(self, text: str, action: str, mood: str) -> str:
        t = (text or "").lower()
        if action == "journey":
            return "environmental movement showing ascent/path/terrain"
        if action == "revelation":
            return "reverent symbolic light and cave atmosphere without figures"
        if action == "comfort":
            return "warm interior atmosphere, non-modern, no people"
        if action == "text_reflection":
            return "text-safe sacred manuscript environment for verified overlay"
        if "cave" in t:
            return "cave geography and texture with historical neutrality"
        return "historical atmosphere tied to narration beat"

    def _forbidden_visuals_for_beat(self, text: str, action: str, mood: str, entities: list[str]) -> list[str]:
        forbidden = ["humans", "faces", "bodies", "modern furniture", "modern interiors", "countdown candles"]
        t = (text or "").lower()
        if any(e in {"hira", "jabal al-nour", "makkah"} for e in entities):
            forbidden.extend(["tourist pathways", "railing", "walkways", "lush green modern caves"])
        if action in {"revelation", "text_reflection"} or any(k in t for k in ("qur", "ayah", "verse", "iqra")):
            forbidden.extend(["readable generated arabic text", "fake scripture text", "calligraphy gibberish"])
        if mood in {"comfort"}:
            forbidden.extend(["modern chairs", "apartments", "glass windows"])
        return sorted(set(forbidden))

    def _assign_beats_to_shots(self, beats: list[BeatSpec], shot_count: int) -> list[BeatSpec | None]:
        if shot_count <= 0:
            return []
        if not beats:
            return [None] * shot_count
        assigned: list[BeatSpec] = []
        for i in range(shot_count):
            idx = min(len(beats) - 1, int((i / max(1, shot_count)) * len(beats)))
            assigned.append(beats[idx])
        # Ensure all beats are represented at least once if possible.
        if shot_count >= len(beats):
            for beat_idx, beat in enumerate(beats):
                assign_idx = round((beat_idx + 0.5) * shot_count / len(beats) - 0.5)
                assign_idx = max(0, min(shot_count - 1, assign_idx))
                assigned[assign_idx] = beat
        return assigned

    def _plan_scene(self, scene, *, beats: list[BeatSpec] | None = None) -> SceneShotPlan:
        scene_number = int(getattr(scene, "scene_number", 0) or 0)
        narration = str(getattr(scene, "narration", "") or "").strip()
        visual_type = str(getattr(scene, "visual_type", "video") or "video").lower()
        video_prompt = str(getattr(scene, "video_prompt", "") or "").strip()
        image_prompt = str(getattr(scene, "image_prompt", "") or "").strip()
        target_dur = float(getattr(scene, "duration_target_seconds", 40.0) or 40.0)

        scene_goal = self._infer_scene_goal(narration, video_prompt, image_prompt)
        scene_type = "quran_verse" if self._needs_quran_overlay(narration, video_prompt, image_prompt) else "narrative"

        continuity_tags = self._extract_tags(narration, video_prompt, image_prompt)
        shot_count = self._shot_count_for_duration(target_dur, scene_goal)
        roles = self._roles_for_scene_goal(scene_goal, shot_count)
        durations = self._allocate_shot_durations(target_dur, roles, scene_goal)

        shots: list[ShotSpec] = []
        base_prompt = image_prompt if visual_type == "image" and image_prompt else video_prompt or image_prompt
        fallback_prompt = image_prompt or video_prompt

        beats = beats or self._plan_scene_beats(scene)
        shot_beats = self._assign_beats_to_shots(beats, len(roles))
        quota_targets = self._scene_source_quota_targets(
            scene_goal=scene_goal,
            scene_type=scene_type,
            shot_count=len(roles),
        )

        for idx, (role, dur, beat) in enumerate(zip(roles, durations, shot_beats), start=1):
            source_strategy = self._select_source_strategy(
                role=role,
                scene_goal=scene_goal,
                scene_type=scene_type,
                original_visual_type=visual_type,
            )
            camera_motion = self._camera_motion_for(role, scene_goal, source_strategy)
            prompt = self._build_shot_prompt(
                base_prompt=base_prompt,
                beat_text=beat.text if beat else narration,
                visual_intent=(beat.visual_intent if beat else ""),
                role=role,
                camera_motion=camera_motion,
                scene_goal=scene_goal,
                source_strategy=source_strategy,
                forbidden_visuals=(beat.forbidden_visuals if beat else []),
            )
            shot_id = f"s{scene_number:02d}_sh{idx:02d}"
            shots.append(
                ShotSpec(
                    shot_id=shot_id,
                    scene_number=scene_number,
                    order_index=idx,
                    duration_seconds=dur,
                    shot_role=role,
                    source_strategy=source_strategy,
                    camera_motion=camera_motion,
                    energy_level=self._energy_for(role, scene_goal),
                    prompt=prompt,
                    fallback_prompt=fallback_prompt,
                    continuity_tags=continuity_tags,
                    forbidden_visuals=(beat.forbidden_visuals if beat else []),
                    sacred_text_overlay=(scene_type == "quran_verse" and role in {"hero", "detail", "symbolic"}),
                    quran_ref=self._extract_quran_ref(narration),
                    beat_id=(beat.beat_id if beat else None),
                    beat_text=(beat.text if beat else None),
                    beat_start_ratio=(beat.start_ratio if beat else None),
                    beat_end_ratio=(beat.end_ratio if beat else None),
                    notes=self._shot_notes(role, scene_goal, source_strategy),
                )
            )

        return SceneShotPlan(
            scene_number=scene_number,
            scene_type=scene_type,  # type: ignore[arg-type]
            scene_goal=scene_goal,  # type: ignore[arg-type]
            target_duration_seconds=target_dur,
            original_visual_type="image" if visual_type == "image" else "video",
            narration_excerpt=(narration[:200] + "...") if len(narration) > 200 else narration,
            continuity_tags=continuity_tags,
            source_quota_targets=quota_targets,
            beats=beats,
            shots=shots,
        )

    def _infer_scene_goal(self, narration: str, video_prompt: str, image_prompt: str) -> str:
        text = " ".join([narration, video_prompt, image_prompt]).lower()
        if any(k in text for k in ("revealed", "revelation", "iqra", "angel", "read in the name")):
            return "revelation"
        if any(k in text for k in ("fear", "shaken", "darkness", "terror", "urgent", "rushing")):
            return "tension"
        if any(k in text for k in ("returned", "comfort", "calmed", "after", "assured")):
            return "aftermath"
        if any(k in text for k in ("journey", "path", "mountain", "climb", "desert route", "tracking shot")):
            return "journey"
        if any(k in text for k in ("quiet", "reflection", "ponder", "stillness", "night sky")):
            return "reflection"
        return "setup"

    def _needs_quran_overlay(self, narration: str, video_prompt: str, image_prompt: str) -> bool:
        text = " ".join([narration, video_prompt, image_prompt])
        if _QURAN_MARKERS.search(text):
            return True
        # Text-heavy scenes often become garbage if we rely on generated lettering.
        return bool(_TEXT_VISUAL_MARKERS.search(text) and any(k in text.lower() for k in ("arabic", "verse", "surah", "iqra")))

    def _extract_quran_ref(self, narration: str) -> str | None:
        m = re.search(r"\b(\d{1,3}:\d{1,3}(?:-\d{1,3})?)\b", narration)
        if m:
            return m.group(1)
        t = (narration or "").lower()
        # Common Revelation (Iqra) wording often appears without explicit citation.
        if any(k in t for k in ("iqra", "read in the name of your lord", "who taught by the pen")):
            return "96:1-5"
        return None

    def _extract_tags(self, *texts: str) -> list[str]:
        joined = " ".join(t.lower() for t in texts if t)
        tags = []
        for token in ("desert", "mountain", "cave", "night", "dawn", "stone", "parchment", "lamp", "light", "revelation"):
            if token in joined:
                tags.append(token)
        return tags or ["historical", "atmospheric"]

    def _shot_count_for_duration(self, target_dur: float, scene_goal: str) -> int:
        # Aim for faster editorial cadence (roughly 3-6s average shots)
        # to avoid stretching short generated clips into visible loops.
        base = round(target_dur / 5.0)
        base = max(5, min(9, base))
        if scene_goal in {"tension", "journey"}:
            base += 1
        if scene_goal in {"revelation", "reflection"}:
            base = max(5, base - 1)
        return max(5, min(10, base))

    def _roles_for_scene_goal(self, scene_goal: str, shot_count: int) -> list[str]:
        templates = {
            "setup": ["establishing", "medium", "detail", "hero", "closing"],
            "journey": ["establishing", "transition", "medium", "detail", "hero", "transition", "closing"],
            "tension": ["hook", "medium", "detail", "symbolic", "hero", "closing"],
            "revelation": ["establishing", "symbolic", "hero", "detail", "closing"],
            "aftermath": ["medium", "detail", "symbolic", "hero", "closing"],
            "reflection": ["establishing", "detail", "symbolic", "hero", "closing"],
        }
        roles = templates.get(scene_goal, templates["setup"]).copy()
        if len(roles) > shot_count:
            while len(roles) > shot_count:
                # Prefer removing repeated middle shots first, keeping strong open/close.
                roles.pop(max(1, len(roles) - 2))
        elif len(roles) < shot_count:
            insert_idx = max(1, len(roles) - 1)
            fillers = ["medium", "detail", "transition", "symbolic"]
            i = 0
            while len(roles) < shot_count:
                roles.insert(insert_idx, fillers[i % len(fillers)])
                i += 1
                insert_idx = min(insert_idx + 1, len(roles) - 1)
        return roles

    def _allocate_shot_durations(self, target_dur: float, roles: list[str], scene_goal: str) -> list[float]:
        role_weights = {
            "hook": 0.95,
            "establishing": 1.2 if scene_goal in {"setup", "reflection"} else 1.0,
            "medium": 1.0,
            "detail": 0.85,
            "hero": 1.15 if scene_goal in {"revelation", "reflection"} else 1.0,
            "symbolic": 0.95,
            "transition": 0.75,
            "closing": 0.9,
        }
        weights = [role_weights.get(r, 1.0) for r in roles]
        total_w = sum(weights) or 1.0
        raw = [target_dur * (w / total_w) for w in weights]
        # Clamp for editing cadence and redistribute any residual to the hero/closing shots.
        max_shot = 6.0 if scene_goal in {"tension", "journey"} else 7.0
        clamped = [max(2.2, min(max_shot, d)) for d in raw]
        diff = target_dur - sum(clamped)
        if abs(diff) > 0.01:
            preferred = [i for i, r in enumerate(roles) if r in {"hero", "establishing", "closing"}] or list(range(len(roles)))
            i = 0
            while abs(diff) > 0.05 and preferred:
                idx = preferred[i % len(preferred)]
                step = 0.25 if diff > 0 else -0.25
                nxt = clamped[idx] + step
                if 2.0 <= nxt <= (max_shot + 0.75):
                    clamped[idx] = nxt
                    diff -= step
                i += 1
                if i > 200:
                    break
        return [round(max(1.5, d), 2) for d in clamped]

    def _select_source_strategy(
        self,
        *,
        role: str,
        scene_goal: str,
        scene_type: str,
        original_visual_type: str,
    ) -> str:
        if scene_type == "quran_verse" and role in {"hero", "detail", "symbolic"}:
            return "image"  # verse text is rendered locally as overlay; keep background simple
        if role in {"establishing", "transition"}:
            return "stock"
        if original_visual_type == "image":
            if role in {"hero", "symbolic", "detail"}:
                return "image"
            return "stock"
        if scene_goal in {"tension", "journey"} and role in {"hook", "hero", "medium"}:
            return "veo"
        if role in {"hero", "medium"}:
            return "veo"
        if role == "symbolic":
            return "image"
        return "auto"

    def _camera_motion_for(self, role: str, scene_goal: str, source_strategy: str) -> str:
        if role == "establishing":
            return "slow_dolly_or_aerial"
        if role == "transition":
            return "glide"
        if role == "detail":
            return "macro_push_in" if source_strategy != "stock" else "slow_pan"
        if role == "hook":
            return "dynamic_sweep"
        if role == "hero":
            return "measured_push_in" if scene_goal in {"revelation", "reflection"} else "cinematic_tracking"
        if role == "symbolic":
            return "static_or_slow_float"
        return "slow_pan"

    def _energy_for(self, role: str, scene_goal: str) -> int:
        base = {"tension": 5, "journey": 4, "setup": 3, "revelation": 3, "aftermath": 2, "reflection": 2}.get(scene_goal, 3)
        if role in {"hook", "hero"}:
            return min(5, base + 1)
        if role in {"detail", "symbolic"}:
            return max(1, base - 1)
        return base

    def _build_shot_prompt(
        self,
        *,
        base_prompt: str,
        beat_text: str,
        visual_intent: str,
        role: str,
        camera_motion: str,
        scene_goal: str,
        source_strategy: str,
        forbidden_visuals: list[str] | None = None,
    ) -> str:
        base = base_prompt.strip()
        if not base:
            base = "Cinematic historical environment, atmospheric, no humans, no readable text"

        role_directives = {
            "hook": "Immediate visual hook, high contrast, strong motion cue, no clutter.",
            "establishing": "Wide establishing composition, clear geography, cinematic depth.",
            "medium": "Mid-distance framing that advances the scene visually.",
            "detail": "Close detail texture shot, tactile surfaces, selective focus.",
            "hero": "Most iconic image of this beat, premium cinematic composition.",
            "symbolic": "Symbolic atmospheric insert, reverent and restrained.",
            "transition": "Bridge shot for editorial transition, smooth visual movement.",
            "closing": "Resolve the scene and create a clean transition out.",
        }
        source_hint = {
            "stock": "Prefer realistic stock-footage-friendly environment cues.",
            "veo": "Cinematic motion and dynamic camera movement preferred.",
            "image": "Still-image composition suitable for subtle motion in edit.",
            "auto": "Choose the strongest cinematic option.",
        }
        beat_text_clean = " ".join((beat_text or "").strip().split())
        if len(beat_text_clean) > 180:
            beat_text_clean = beat_text_clean[:177].rstrip() + "..."
        forbidden_clause = ""
        if forbidden_visuals:
            trimmed = ", ".join(list(dict.fromkeys(forbidden_visuals))[:8])
            if trimmed:
                forbidden_clause = f" Avoid: {trimmed}."
        suffix = (
            f" Narration beat: {beat_text_clean}. Visual intent: {visual_intent or 'historical atmosphere tied to narration'}. "
            f"Shot role: {role}. Camera motion: {camera_motion}. Scene mood: {scene_goal}. "
            f"{role_directives.get(role, '')} {source_hint.get(source_strategy, '')} "
            "No humans, no faces, no bodies, no readable text."
            f"{forbidden_clause}"
        )
        return f"{base} {suffix}".strip()

    def _shot_notes(self, role: str, scene_goal: str, source_strategy: str) -> str:
        notes = []
        if source_strategy == "stock":
            notes.append("stock_preferred")
        if source_strategy == "veo":
            notes.append("veo_anchor")
        if role in {"symbolic", "hero"} and scene_goal == "revelation":
            notes.append("slow_cut_recommended")
        return ", ".join(notes)

    def _scene_source_quota_targets(self, *, scene_goal: str, scene_type: str, shot_count: int) -> dict[str, int]:
        """Soft scene-level source quotas to prevent stock-dominant timelines."""
        shot_count = max(1, int(shot_count))
        if scene_type == "quran_verse":
            return {
                "min_non_stock": max(2, round(shot_count * 0.45)),
                "max_stock": max(1, round(shot_count * 0.50)),
                "min_image": max(2, round(shot_count * 0.30)),
                "min_veo": 0,
            }
        if scene_goal in {"tension", "journey"}:
            return {
                "min_non_stock": max(2, round(shot_count * 0.35)),
                "max_stock": max(2, round(shot_count * 0.65)),
                "min_image": 1,
                "min_veo": 2 if shot_count >= 6 else 1,
            }
        if scene_goal in {"revelation", "reflection"}:
            return {
                "min_non_stock": max(2, round(shot_count * 0.40)),
                "max_stock": max(1, round(shot_count * 0.55)),
                "min_image": max(2, round(shot_count * 0.25)),
                "min_veo": 1,
            }
        return {
            "min_non_stock": max(2, round(shot_count * 0.30)),
            "max_stock": max(2, round(shot_count * 0.70)),
            "min_image": 1,
            "min_veo": 1 if shot_count >= 6 else 0,
        }
