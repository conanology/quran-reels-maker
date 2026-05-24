"""
Resolve Qur'an verse references for documentary overlays using the existing V4 API.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import logging
import re
from typing import Any

from core.quran_v4_api import (
    get_multiple_ayat,
    get_ayah_translation,
    get_surah_name,
    validate_verse_range,
)

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^\s*(\d{1,3})\s*:\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*$")


@dataclass
class QuranVersePayload:
    quran_ref: str
    surah: int
    start_ayah: int
    end_ayah: int
    surah_name_ar: str
    surah_name_en: str
    arabic_text: str
    translation_text: str
    citation_en: str
    citation_ar: str
    translation_source: str = "Sahih International"

    def to_dict(self) -> dict[str, Any]:
        return {
            "quran_ref": self.quran_ref,
            "surah": self.surah,
            "start_ayah": self.start_ayah,
            "end_ayah": self.end_ayah,
            "surah_name_ar": self.surah_name_ar,
            "surah_name_en": self.surah_name_en,
            "arabic_text": self.arabic_text,
            "translation_text": self.translation_text,
            "citation_en": self.citation_en,
            "citation_ar": self.citation_ar,
            "translation_source": self.translation_source,
        }


def parse_quran_ref(quran_ref: str) -> tuple[int, int, int] | None:
    m = _REF_RE.match((quran_ref or "").strip())
    if not m:
        return None
    surah = int(m.group(1))
    start_ayah = int(m.group(2))
    end_ayah = int(m.group(3) or start_ayah)
    return surah, start_ayah, end_ayah


def resolve_quran_verse_payload(quran_ref: str, *, translation_lang: str = "en") -> QuranVersePayload | None:
    parsed = parse_quran_ref(quran_ref)
    if not parsed:
        return None

    surah, start_ayah, end_ayah = parsed
    start_ayah, end_ayah = validate_verse_range(surah, start_ayah, end_ayah)

    ayat = get_multiple_ayat(surah, start_ayah, end_ayah)
    arabic_parts = []
    trans_parts = []
    for a in ayat:
        anum = int(a.get("ayah", 0) or 0)
        text = str(a.get("text", "") or "").strip()
        if text:
            arabic_parts.append(f"{text} \uFD3F{anum}\uFD3E")
        t = get_ayah_translation(surah, anum, translation_lang)
        if t:
            trans_parts.append(str(t).strip())

    if not arabic_parts:
        logger.warning("No Qur'an text resolved for ref %s", quran_ref)
        return None

    surah_name_ar = get_surah_name(surah, "ar")
    surah_name_en = get_surah_name(surah, "en")
    ref_norm = f"{surah}:{start_ayah}" + (f"-{end_ayah}" if end_ayah != start_ayah else "")
    citation_en = f"Qur'an {ref_norm} • Surah {surah_name_en}"
    citation_ar = f"القرآن {ref_norm} • سورة {surah_name_ar}"

    return QuranVersePayload(
        quran_ref=ref_norm,
        surah=surah,
        start_ayah=start_ayah,
        end_ayah=end_ayah,
        surah_name_ar=surah_name_ar,
        surah_name_en=surah_name_en,
        arabic_text=" ".join(arabic_parts),
        translation_text=" ".join(trans_parts).strip(),
        citation_en=citation_en,
        citation_ar=citation_ar,
    )


def write_quran_payload_snapshot(output_path: Path, payloads: list[QuranVersePayload]) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.to_dict() for p in payloads]
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path

