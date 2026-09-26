import os
import re
import json
import sys
from pathlib import Path
from .common import (MAX_CLIP_SECONDS, MAX_DOWNLOAD_BYTES, contained, video_id as validate_video_id,
                     channel_url as validate_channel_url, run_process, check_cancel)

# Folder setup
# All downloads are explicitly owned by the caller's job. No import-time writes.

# 114 Surahs mapping: (English name, Arabic name)
SURAHS = [
    ("Al-Fatihah", "الفاتحة"), ("Al-Baqarah", "البقرة"), ("Al-Imran", "آل عمران"),
    ("An-Nisa", "النساء"), ("Al-Ma'idah", "المائدة"), ("Al-An'am", "الأنعام"),
    ("Al-A'raf", "الأعراف"), ("Al-Anfal", "الأنفال"), ("At-Tawbah", "التوبة"),
    ("Yunus", "يونس"), ("Hud", "هود"), ("Yusuf", "يوسف"), ("Ar-Ra'd", "الرعد"),
    ("Ibrahim", "ابراهيم"), ("Al-Hijr", "الحجر"), ("An-Nahl", "النحل"),
    ("Al-Isra", "الإسراء"), ("Al-Kahf", "الكهف"), ("Maryam", "مريم"),
    ("Taha", "طه"), ("Al-Anbiya", "الأنبياء"), ("Al-Hajj", "الحج"),
    ("Al-Mu'minun", "المؤمنون"), ("An-Nur", "النور"), ("Al-Furqan", "الفرقان"),
    ("Ash-Shu'ara", "الشعراء"), ("An-Naml", "النمل"), ("Al-Qasas", "القصص"),
    ("Al-Ankabut", "العنكبوت"), ("Ar-Rum", "الروم"), ("Luqman", "لقمان"),
    ("As-Sajdah", "السجدة"), ("Al-Ahzab", "الأحزاب"), ("Saba", "سبأ"),
    ("Fatir", "فاطر"), ("Yasin", "يس"), ("As-Saffat", "الصافات"),
    ("Sad", "ص"), ("Az-Zumar", "الزمر"), ("Ghafir", "غافر"),
    ("Fussilat", "فصلت"), ("Ash-Shura", "الشورى"), ("Az-Zukhruf", "الزخرف"),
    ("Ad-Dukhan", "الدخان"), ("Al-Jathiyah", "الجاثية"), ("Al-Ahqaf", "الأحقاف"),
    ("Muhammad", "محمد"), ("Al-Fath", "الفتح"), ("Al-Hujurat", "الحجرات"),
    ("Qaf", "ق"), ("Adh-Dhariyat", "الذاريات"), ("At-Tur", "الطور"),
    ("An-Najm", "النجم"), ("Al-Qamar", "القمر"), ("Ar-Rahman", "الرحمن"),
    ("Al-Waqi'ah", "الواقعة"), ("Al-Hadid", "الحديد"), ("Al-Mujadilah", "المجادلة"),
    ("Al-Hashr", "الحشر"), ("Al-Mumtahanah", "الممتحنة"), ("As-Saff", "الصف"),
    ("Al-Jumu'ah", "الجمعة"), ("Al-Munafiqun", "المنافقون"), ("At-Taghabun", "التغابن"),
    ("At-Talaq", "الطلاق"), ("At-Tahrim", "التحريم"), ("Al-Mulk", "الملك"),
    ("Al-Qalam", "القلم"), ("Al-Haqqah", "الحاقة"), ("Al-Ma'arij", "المعارج"),
    ("Nuh", "نوح"), ("Al-Jinn", "الجن"), ("Al-Muzzammil", "المزمل"),
    ("Al-Muddaththir", "المدثر"), ("Al-Qiyamah", "القيامة"), ("Al-Insan", "الإنسان"),
    ("Al-Mursalat", "المرسلات"), ("An-Naba", "النبأ"), ("An-Nazi'at", "النازعات"),
    ("Abasa", "عبس"), ("At-Takwir", "التكوير"), ("Al-Infitar", "الانفطار"),
    ("Al-Mutaffifin", "المطففين"), ("Al-Inshiqaq", "الانشقاق"), ("Al-Buruj", "البروج"),
    ("At-Tariq", "الطارق"), ("Al-A'la", "الأعلى"), ("Al-Ghashiyah", "الغاشية"),
    ("Al-Fajr", "الفجر"), ("Al-Balad", "البلد"), ("Ash-Shams", "الشمس"),
    ("Al-Layl", "الليل"), ("Ad-Duha", "الضحى"), ("Ash-Sharh", "الشرح"),
    ("At-Tin", "التين"), ("Al-Alaq", "العلق"), ("Al-Qadr", "القدر"),
    ("Al-Bayyinah", "البينة"), ("Az-Zalzalah", "الزلزلة"), ("Al-Adiyat", "العاديات"),
    ("Al-Qari'ah", "القارعة"), ("At-Takathur", "التكاثر"), ("Al-Asr", "العصر"),
    ("Al-Humazah", "الهمزة"), ("Al-Fil", "الفيل"), ("Quraysh", "قريش"),
    ("Al-Ma'un", "الماعون"), ("Al-Kauthar", "الكوثر"), ("Al-Kafirun", "الكافرون"),
    ("An-Nasr", "النصر"), ("Al-Masad", "المسد"), ("Al-Ikhlas", "الإخلاص"),
    ("Al-Falaq", "الفلق"), ("An-Nas", "الناس")
]

def normalize_text(text):
    """
    Normalizes English and Arabic text for robust search matching.
    Removes accents, symbols, prefixes like Al-, and standardizes characters.
    """
    if not text:
        return ""
    text = text.lower()
    # Remove Arabic diacritics
    text = re.sub(r"[\u064B-\u065F\u0640]", "", text)
    # Standardize Alif variants
    text = re.sub(r"[أإآ]", "ا", text)
    # Standardize Ta-Marbuta to Ha
    text = re.sub(r"ة", "ه", text)
    # Remove Quran helper words
    text = text.replace("surah", "").replace("سورة", "")
    # Remove non-alphanumeric characters (keep English, numbers, and Arabic characters)
    text = re.sub(r"[^a-z0-9\u0621-\u064A]", "", text)
    # Remove common English transliteration article prefixes (al-, el-, an-, ar-, etc.)
    text = re.sub(r"^(al|an|ash|at|as|ar|az|ad|el)\-?", "", text)
    return text.strip()

def find_surah_index(surah_name_str):
    """
    Finds the 1-based Surah index from a given name string by scanning SURAHS.
    Returns 999 if no match is found.
    """
    norm_search = normalize_text(surah_name_str)
    if not norm_search:
        return 999

    for idx, (en, ar) in enumerate(SURAHS):
        norm_en = normalize_text(en)
        norm_ar = normalize_text(ar)
        if norm_search == norm_en or norm_search == norm_ar or norm_search in norm_en or norm_search in norm_ar or norm_en in norm_search or norm_ar in norm_search:
            return idx + 1
    return 999

def parse_video_title(title):
    """
    Parses video titles to extract:
    - Surah name (English/Arabic)
    - Surah index (1-114)
    - Starting Ayah number (integer)
    - Ending Ayah number (integer)
    - Reciter name (English/Arabic)
    """
    surah_en = ""
    reciter_en = ""
    surah_ar = ""
    reciter_ar = ""
    surah_num = 999
    ayah_start = 0
    ayah_end = 0

    title_clean = title.strip()

    # 1. Search for Surah in English
    surah_en_match = re.search(r"Surah\s+([A-Za-z\-]+(?:\s+[A-Za-z\-]+)*)", title_clean, re.IGNORECASE)
    if surah_en_match:
        surah_en = surah_en_match.group(1).strip()
        surah_num = find_surah_index(surah_en)

    # 2. Search for Surah in Arabic
    surah_ar_match = re.search(r"سورة\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+)*)", title_clean)
    if surah_ar_match:
        surah_ar = "سورة " + surah_ar_match.group(1).strip()
        if surah_num == 999:  # Fill if not already resolved by English
            surah_num = find_surah_index(surah_ar_match.group(1))

    # 3. Search for Ayah references
    # Case A: Colon notation like "2:185" or "2:185-186" or "2: 185 - 186"
    colon_match = re.search(r"\b(\d+)\s*:\s*(\d+)(?:\s*[-–—]\s*(\d+))?\b", title_clean)
    if colon_match:
        surah_num_parsed = int(colon_match.group(1))
        if 1 <= surah_num_parsed <= 114:
            surah_num = surah_num_parsed
            # Set English and Arabic Surah names from catalog
            surah_en = SURAHS[surah_num - 1][0]
            surah_ar = "سورة " + SURAHS[surah_num - 1][1]
        ayah_start = int(colon_match.group(2))
        ayah_end = int(colon_match.group(3)) if colon_match.group(3) else ayah_start

    # Case B: English "Ayah 185-186" or "Verse 185" or "Ayat 5"
    if ayah_start == 0:
        ayah_en_match = re.search(r"(?:Ayah|Verse|Ayat)\s*(\d+)(?:\s*[-–—]\s*(\d+))?", title_clean, re.IGNORECASE)
        if ayah_en_match:
            ayah_start = int(ayah_en_match.group(1))
            ayah_end = int(ayah_en_match.group(2)) if ayah_en_match.group(2) else ayah_start

    # Case C: Arabic "آية 185-186" or "الآية 185" or "الآيات 5-8"
    if ayah_start == 0:
        ayah_ar_match = re.search(r"(?:آية|الآية|الآيات|آيات)\s*(\d+)(?:\s*[-–—]\s*(\d+))?", title_clean)
        if ayah_ar_match:
            ayah_start = int(ayah_ar_match.group(1))
            ayah_end = int(ayah_ar_match.group(2)) if ayah_ar_match.group(2) else ayah_start

    # Case D: Fallback digits matching after Surah name (e.g. "Surah Al-Baqarah 185-186")
    if ayah_start == 0 and surah_en:
        digit_fallback = re.search(rf"{re.escape(surah_en)}\s+(\d+)(?:\s*[-–—]\s*(\d+))?", title_clean, re.IGNORECASE)
        if digit_fallback:
            ayah_start = int(digit_fallback.group(1))
            ayah_end = int(digit_fallback.group(2)) if digit_fallback.group(2) else ayah_start

    if ayah_start == 0 and surah_ar:
        # Extract Arabic surah word name without "سورة " prefix for clean regex matching
        clean_ar_name = surah_ar.replace("سورة ", "").strip()
        digit_fallback_ar = re.search(rf"{re.escape(clean_ar_name)}\s+(\d+)(?:\s*[-–—]\s*(\d+))?", title_clean)
        if digit_fallback_ar:
            ayah_start = int(digit_fallback_ar.group(1))
            ayah_end = int(digit_fallback_ar.group(2)) if digit_fallback_ar.group(2) else ayah_start

    # 4. Search for Reciter / Sheikh in English
    reciter_en_match = re.search(r"(?:Reciter|Sheikh|by)\s+([A-Za-z]+(?:\s+[A-Za-z]+){1,3})", title_clean, re.IGNORECASE)
    if reciter_en_match:
        reciter_en = reciter_en_match.group(1).strip()
    
    # 5. Search for Reciter / Sheikh in Arabic
    reciter_ar_match = re.search(r"(?:القارئ|الشيخ|تلاوة)\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){1,3})", title_clean)
    if reciter_ar_match:
        reciter_ar = reciter_ar_match.group(1).strip()

    # Fallback mappings for split titles
    if not reciter_ar:
        parts = re.split(r"[-|—•_]", title_clean)
        if len(parts) > 1:
            for part in parts:
                part = part.strip()
                if re.search(r"[\u0600-\u06FF]", part) and "سورة" not in part and "آية" not in part and len(part.split()) <= 4:
                    reciter_ar = part
                    break

    if not reciter_ar and reciter_en:
        reciter_ar = reciter_en

    # Complete missing localized surah names from catalog index if resolved
    if surah_num != 999:
        if not surah_en:
            surah_en = SURAHS[surah_num - 1][0]
        if not surah_ar:
            surah_ar = "سورة " + SURAHS[surah_num - 1][1]

    return {
        "surah_en": surah_en,
        "reciter_en": reciter_en,
        "surah_ar": surah_ar,
        "reciter_ar": reciter_ar,
        "surah_num": surah_num,
        "ayah_start": ayah_start,
        "ayah_end": ayah_end
    }

def fetch_shorts_metadata(channel_url_or_handle, *, cancel=None):
    """Only YouTube channel metadata; no config, cookies or arbitrary extractor URLs."""
    url = validate_channel_url(channel_url_or_handle)
    raw = run_process([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-cookies", "--no-playlist", "--flat-playlist", "--skip-download", "--playlist-end", "50", "--socket-timeout", "15", "--retries", "1", "--extractor-retries", "1", "--use-extractors", "youtube:tab", "--dump-single-json", "--", url], timeout=120, cancel=cancel)
    info = json.loads(raw)
    if not isinstance(info, dict) or not isinstance(info.get("entries"), list):
        raise ValueError("YouTube returned unusable channel metadata.")
    shorts = []
    seen = set()
    for entry in info["entries"][:50]:
        if not isinstance(entry, dict):
            continue
        ident = entry.get("id", "")
        try:
            validate_video_id(ident)
        except (ValueError, TypeError):
            continue
        if ident in seen:
            continue
        seen.add(ident)
        title = str(entry.get("title") or "Untitled source clip")[:500]
        parsed = parse_video_title(title)
        thumbnails = entry.get("thumbnails") or []
        thumbnail = str(thumbnails[-1].get("url", "")) if thumbnails and isinstance(thumbnails[-1], dict) else ""
        duration = entry.get("duration")
        duration = float(duration) if isinstance(duration, (float, int)) and 0 < duration <= MAX_CLIP_SECONDS else None
        shorts.append({"id": ident, "url": f"https://www.youtube.com/watch?v={ident}", "title": title, "thumbnail": thumbnail,
                       "duration": duration, **parsed, "attribution_verified": False})
    return shorts


def download_video(video_id, progress_hook=None, *, downloads_dir, cancel=None):
    ident = validate_video_id(video_id)
    root = Path(downloads_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = contained(root, f"{ident}.mp4")
    if destination.exists():
        raise FileExistsError("Source file already exists in this job; start a new job to retry.")
    check_cancel(cancel)
    template = contained(root, f"{ident}.%(ext)s")
    def size_check():
        total = sum(p.stat().st_size for p in root.glob(f"{ident}.*") if p.is_file())
        if total > MAX_DOWNLOAD_BYTES:
            raise ValueError("Downloaded bytes exceed the per-clip size limit.")
    try:
        run_process([sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-cookies", "--no-playlist", "--no-progress", "--socket-timeout", "15", "--retries", "1", "--fragment-retries", "1", "--extractor-retries", "1", "--use-extractors", "youtube", "--max-filesize", str(MAX_DOWNLOAD_BYTES), "--match-filters", f"duration <= {MAX_CLIP_SECONDS}", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]", "--merge-output-format", "mp4", "--no-overwrites", "-o", str(template), "--", f"https://www.youtube.com/watch?v={ident}"], timeout=300, cancel=cancel, monitor=size_check)
        if not destination.is_file() or not 0 < destination.stat().st_size <= MAX_DOWNLOAD_BYTES:
            raise ValueError("Download was skipped, incomplete or exceeded the size limit.")
        if progress_hook:
            progress_hook({"status": "finished"})
        return str(destination)
    except BaseException:
        # Only this validated video's owned files, including partial downloads.
        for candidate in root.glob(f"{ident}.*"):
            if candidate.is_file() and candidate.resolve().is_relative_to(root):
                candidate.unlink(missing_ok=True)
        raise
