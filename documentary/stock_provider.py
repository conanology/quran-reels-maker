"""
Documentary stock footage provider (Pexels-first).

Provides landscape 16:9 footage/images for shot-plan roles such as
establishing shots and transitions. Keeps a local cache and returns
provenance metadata so episodes can emit a sources manifest.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from config.settings import ASSETS_DIR
from core.person_detector import has_people


PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
PEXELS_IMAGE_SEARCH_URL = "https://api.pexels.com/v1/search"
logger = logging.getLogger(__name__)


@dataclass
class StockAssetResult:
    path: Path
    source_kind: str  # pexels_video | pexels_image | cache
    provider: str = "pexels"
    provider_id: str | None = None
    source_url: str | None = None
    creator: str | None = None
    query: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    screening: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "source_kind": self.source_kind,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "source_url": self.source_url,
            "creator": self.creator,
            "query": self.query,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "screening": self.screening,
        }


class DocumentaryStockProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or PEXELS_API_KEY
        self.cache_dir = ASSETS_DIR / "documentary" / "stock_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": self.api_key})

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def fetch_video_for_shot(
        self,
        *,
        shot_prompt: str,
        continuity_tags: list[str] | None = None,
        forbidden_visuals: list[str] | None = None,
        target_path: Path,
    ) -> StockAssetResult | None:
        """Search and download a stock video suitable for a documentary shot."""
        if not self.enabled:
            return None

        target_path = Path(target_path)
        if target_path.exists() and target_path.stat().st_size > 1024:
            return StockAssetResult(path=target_path, source_kind="cache")

        queries = self._build_queries(shot_prompt, continuity_tags or [])
        for query in queries[:6]:
            video_meta = self._search_video(query, forbidden_visuals=forbidden_visuals or [])
            if not video_meta:
                continue
            downloaded = self._download_video(video_meta, query=query, forbidden_visuals=forbidden_visuals or [])
            if not downloaded:
                continue
            if target_path.resolve() != downloaded.path.resolve():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(downloaded.path, target_path)
                downloaded.path = target_path
            return downloaded
        return None

    def fetch_image_for_shot(
        self,
        *,
        shot_prompt: str,
        continuity_tags: list[str] | None = None,
        forbidden_visuals: list[str] | None = None,
        target_path: Path,
    ) -> StockAssetResult | None:
        """Search and download a stock image (fallback for static shots)."""
        if not self.enabled:
            return None

        target_path = Path(target_path)
        if target_path.exists() and target_path.stat().st_size > 1024:
            return StockAssetResult(path=target_path, source_kind="cache")

        queries = self._build_queries(shot_prompt, continuity_tags or [])
        for query in queries[:6]:
            img_meta = self._search_image(query, forbidden_visuals=forbidden_visuals or [])
            if not img_meta:
                continue
            downloaded = self._download_image(img_meta, query=query, forbidden_visuals=forbidden_visuals or [])
            if not downloaded:
                continue
            if target_path.resolve() != downloaded.path.resolve():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(downloaded.path, target_path)
                downloaded.path = target_path
            return downloaded
        return None

    # ----- internals -----

    def _build_queries(self, prompt: str, continuity_tags: list[str]) -> list[str]:
        p = (prompt or "").lower()
        tags = [t.lower() for t in continuity_tags]
        queries: list[str] = []

        def add(q: str):
            q = q.strip()
            if q and q not in queries:
                queries.append(q)

        # Tag-driven queries first (higher precision than raw prompt fragments)
        if "cave" in tags:
            add("cave interior light rays")
            add("rock cave cinematic")
        if "mountain" in tags:
            add("desert mountains aerial")
            add("rocky mountain landscape")
        if "desert" in tags:
            add("desert dunes aerial")
            add("desert landscape cinematic")
        if "night" in tags and "sky" in p or "star" in p:
            add("starry night sky timelapse")
        if "lamp" in tags:
            add("candle flame close up")
            add("oil lamp close up")
        if "parchment" in tags:
            add("old paper parchment close up")
            add("ancient manuscript table")
        if "stone" in tags:
            add("ancient stone wall interior")
        if "light" in tags:
            add("light rays dust interior")
            add("god rays window dust")

        # Prompt keyword heuristics
        for pat, q in [
            (r"\bstar|milky way|night sky\b", "starry night sky"),
            (r"\bcave\b", "cave interior"),
            (r"\bmountain|rocky\b", "rocky mountains"),
            (r"\bdesert|dune\b", "desert dunes"),
            (r"\bparchment|scroll|manuscript\b", "old manuscript close up"),
            (r"\blamp|candle|flame\b", "candle flame close up"),
            (r"\bwindow light|light rays|volumetric\b", "window light rays dust"),
            (r"\btable\b", "wooden table close up"),
        ]:
            if re.search(pat, p):
                add(q)

        # Prompt-derived noun-ish chunk (sanitized)
        cleaned = re.sub(r"[^a-z0-9\s]", " ", p)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            tokens = [
                t for t in cleaned.split()
                if t not in {
                    "cinematic", "historical", "environment", "only", "camera", "motion",
                    "scene", "mood", "no", "humans", "faces", "bodies", "readable", "text",
                    "shot", "role", "prefer", "strongest", "option", "composition", "lighting",
                    "documentary", "style",
                }
            ]
            if tokens:
                add(" ".join(tokens[:6]))

        add("desert landscape cinematic")
        add("rocky mountains aerial")
        add("cave interior light rays")

        return queries

    def _search_video(self, query: str, *, forbidden_visuals: list[str]) -> dict[str, Any] | None:
        try:
            r = self.session.get(
                PEXELS_VIDEO_SEARCH_URL,
                params={
                    "query": query,
                    "per_page": 15,
                    "orientation": "landscape",
                    "size": "large",
                },
                timeout=12,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            videos = data.get("videos", [])
            random.shuffle(videos)
            ranked_candidates: list[tuple[int, dict[str, Any]]] = []
            for v in videos:
                if not (5 <= int(v.get("duration", 0)) <= 90):
                    continue
                if self._looks_people_heavy(v):
                    continue
                screen = self._screen_candidate_metadata(v, query=query, forbidden_visuals=forbidden_visuals)
                if not screen["ok"]:
                    continue
                ranked_candidates.append((int(screen.get("score", 0)), v))
            if not ranked_candidates:
                return None
            ranked_candidates.sort(key=lambda x: x[0], reverse=True)
            return ranked_candidates[0][1]
        except Exception:
            return None

    def _search_image(self, query: str, *, forbidden_visuals: list[str]) -> dict[str, Any] | None:
        try:
            r = self.session.get(
                PEXELS_IMAGE_SEARCH_URL,
                params={
                    "query": query,
                    "per_page": 15,
                    "orientation": "landscape",
                    "size": "large",
                },
                timeout=12,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            photos = data.get("photos", [])
            random.shuffle(photos)
            ranked_candidates: list[tuple[int, dict[str, Any]]] = []
            for p in photos:
                if self._looks_people_heavy(p):
                    continue
                screen = self._screen_candidate_metadata(p, query=query, forbidden_visuals=forbidden_visuals)
                if not screen["ok"]:
                    continue
                ranked_candidates.append((int(screen.get("score", 0)), p))
            if not ranked_candidates:
                return None
            ranked_candidates.sort(key=lambda x: x[0], reverse=True)
            return ranked_candidates[0][1]
        except Exception:
            return None

    def _download_video(self, video: dict[str, Any], *, query: str, forbidden_visuals: list[str]) -> StockAssetResult | None:
        files = video.get("video_files", []) or []
        # Prefer 16:9-ish HD files
        ranked = sorted(
            files,
            key=lambda f: (
                -min(f.get("width", 0), 4096) * min(f.get("height", 0), 4096),
                abs(self._aspect_ratio(f) - (16 / 9)),
            ),
        )
        selected = None
        for vf in ranked:
            if vf.get("width", 0) >= 1280 and vf.get("height", 0) >= 720:
                selected = vf
                break
        if not selected and ranked:
            selected = ranked[0]
        if not selected:
            return None

        pexels_id = str(video.get("id", "unknown"))
        width = int(selected.get("width", 0) or 0)
        height = int(selected.get("height", 0) or 0)
        ext = ".mp4"
        cache_path = self.cache_dir / f"pexels_vid_{pexels_id}_{width}x{height}.mp4"
        screening = self._screen_candidate_metadata(video, query=query, forbidden_visuals=forbidden_visuals)
        if not screening.get("ok", True):
            logger.info("Rejected Pexels video %s for query '%s': %s", pexels_id, query, ", ".join(screening.get("reasons", [])))
            return None

        if cache_path.exists() and cache_path.stat().st_size > 1024:
            return StockAssetResult(
                path=cache_path,
                source_kind="pexels_video",
                provider_id=pexels_id,
                source_url=video.get("url"),
                creator=(video.get("user") or {}).get("name"),
                query=query,
                width=width,
                height=height,
                duration=float(video.get("duration", 0) or 0),
                screening=screening,
            )

        link = selected.get("link")
        if not link:
            return None
        try:
            with requests.get(link, stream=True, timeout=30) as r:
                r.raise_for_status()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
        except Exception:
            return None

        # Best-effort people rejection
        try:
            if has_people(cache_path, num_frames=5):
                cache_path.unlink(missing_ok=True)
                return None
        except Exception:
            pass

        return StockAssetResult(
            path=cache_path,
            source_kind="pexels_video",
            provider_id=pexels_id,
            source_url=video.get("url"),
            creator=(video.get("user") or {}).get("name"),
            query=query,
            width=width,
            height=height,
            duration=float(video.get("duration", 0) or 0),
            screening=screening,
        )

    def _download_image(self, photo: dict[str, Any], *, query: str, forbidden_visuals: list[str]) -> StockAssetResult | None:
        pexels_id = str(photo.get("id", "unknown"))
        src = photo.get("src") or {}
        img_url = src.get("large2x") or src.get("large") or src.get("original")
        if not img_url:
            return None
        screening = self._screen_candidate_metadata(photo, query=query, forbidden_visuals=forbidden_visuals)
        if not screening.get("ok", True):
            logger.info("Rejected Pexels image %s for query '%s': %s", pexels_id, query, ", ".join(screening.get("reasons", [])))
            return None

        width = int(photo.get("width", 0) or 0)
        height = int(photo.get("height", 0) or 0)
        cache_path = self.cache_dir / f"pexels_img_{pexels_id}_{width}x{height}.jpg"
        if not (cache_path.exists() and cache_path.stat().st_size > 1024):
            try:
                r = requests.get(img_url, timeout=30)
                r.raise_for_status()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(r.content)
            except Exception:
                return None

        return StockAssetResult(
            path=cache_path,
            source_kind="pexels_image",
            provider_id=pexels_id,
            source_url=photo.get("url"),
            creator=(photo.get("photographer") or None),
            query=query,
            width=width,
            height=height,
            duration=None,
            screening=screening,
        )

    @staticmethod
    def _aspect_ratio(item: dict[str, Any]) -> float:
        w = float(item.get("width", 1) or 1)
        h = float(item.get("height", 1) or 1)
        return w / h if h else 1.0

    @staticmethod
    def _looks_people_heavy(item: dict[str, Any]) -> bool:
        text = " ".join(
            str(item.get(k, "")) for k in ("url", "alt", "avg_color")
        ).lower()
        # Weak heuristic only; actual rejection relies on detector when available.
        return any(tok in text for tok in ("portrait", "wedding", "person", "people"))

    @staticmethod
    def _candidate_metadata_text(item: dict[str, Any], *, query: str = "") -> str:
        parts = [
            query,
            str(item.get("url", "")),
            str(item.get("alt", "")),
            str(item.get("title", "")),
            str((item.get("user") or {}).get("name", "")),
            str(item.get("photographer", "")),
        ]
        return " ".join(p for p in parts if p).lower()

    def _screen_candidate_metadata(
        self,
        item: dict[str, Any],
        *,
        query: str,
        forbidden_visuals: list[str],
    ) -> dict[str, Any]:
        text = self._candidate_metadata_text(item, query=query)
        reasons: list[str] = []
        warnings: list[str] = []
        score = 100

        # Hard blocks for obvious modern/social/celebration content.
        hard_block_terms = {
            "car": "vehicle_content",
            "cars": "vehicle_content",
            "vehicle": "vehicle_content",
            "jeep": "vehicle_content",
            "truck": "vehicle_content",
            "suv": "vehicle_content",
            "road": "road_content",
            "highway": "road_content",
            "power line": "powerline_content",
            "electric line": "powerline_content",
            "birthday": "birthday_content",
            "party": "party_content",
            "wedding": "wedding_content",
            "office": "office_content",
            "conference": "conference_content",
            "meeting": "meeting_content",
            "apartment": "apartment_content",
            "living room": "living_room_content",
            "sofa": "sofa_content",
            "chair": "chair_content",
            "tourist": "tourist_content",
            "tourism": "tourism_content",
            "hiker": "hiker_content",
            "hiking": "hiking_content",
            "traveler": "traveler_content",
            "tour guide": "tourist_content",
            "woman": "human_cue",
            "man": "human_cue",
            "people": "human_cue",
            "person": "human_cue",
            "family": "human_cue",
            "child": "human_cue",
            "kids": "human_cue",
        }
        for term, label in hard_block_terms.items():
            if term in text:
                reasons.append(label)

        # Map director forbidden phrases into keyword checks.
        forbidden_map = {
            "countdown candles": ["countdown", "birthday", "number candle", "anniversary candle"],
            "modern furniture": ["chair", "sofa", "table setting", "interior design", "living room"],
            "modern interiors": ["apartment", "office", "meeting room", "conference room"],
            "tourist pathways": ["tourist", "trail", "hiking", "boardwalk", "stair", "stairs"],
            "railing": ["railing", "fence", "handrail", "guardrail"],
            "walkways": ["walkway", "pathway", "boardwalk", "paved path"],
            "lush green modern caves": ["lush", "green cave", "river cave", "tour cave"],
            "glass windows": ["glass window", "window view", "modern window"],
        }
        forbidden_text = " | ".join((forbidden_visuals or [])).lower()
        for phrase, terms in forbidden_map.items():
            if phrase in forbidden_text:
                for term in terms:
                    if term in text:
                        reasons.append(f"forbidden_match:{phrase}")
                        break

        # Soft scoring for historical-fit cues
        positive_terms = ["desert", "mountain", "rock", "cave", "stone", "dune", "sky", "night", "flame", "lamp", "dust"]
        if any(t in text for t in positive_terms):
            score += 10
        if any(t in text for t in ("modern", "city", "urban", "street", "building", "house")):
            warnings.append("modern_cues_present")
            score -= 20
        if any(t in text for t in ("tour", "park", "hiking", "travel")):
            warnings.append("tourism_cues_present")
            score -= 25

        # If query is candle-like but forbidden mentions countdown candles, be extra strict.
        if "candle" in text and "countdown candles" in forbidden_text:
            reasons.append("forbidden_match:countdown_candles")

        # De-duplicate while preserving order
        reasons = list(dict.fromkeys(reasons))
        warnings = list(dict.fromkeys(warnings))
        return {"ok": not reasons, "score": score, "reasons": reasons, "warnings": warnings}
