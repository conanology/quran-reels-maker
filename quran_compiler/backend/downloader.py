import os
import re
import json
import yt_dlp

# Folder setup
BASE_DIR = r"C:\Users\acona\.gemini\antigravity\scratch\quran_compiler"
DOWNLOADS_DIR = os.path.join(BASE_DIR, "data", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

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

def fetch_shorts_metadata(channel_url_or_handle):
    """
    Uses yt-dlp to fetch metadata for all Shorts from a given YouTube channel.
    Returns a list of dictionaries containing video metadata.
    """
    if channel_url_or_handle.startswith("@"):
        channel_url = f"https://www.youtube.com/{channel_url_or_handle}/shorts"
    elif "youtube.com" in channel_url_or_handle and "/shorts" not in channel_url_or_handle:
        channel_url = channel_url_or_handle.rstrip("/") + "/shorts"
    else:
        channel_url = channel_url_or_handle

    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'playlistend': 50,
    }

    print(f"Fetching metadata for channel: {channel_url}")
    shorts_list = []
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(channel_url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    if not entry:
                        continue
                    
                    title = entry.get('title', '')
                    video_id = entry.get('id', '')
                    video_url = entry.get('url', f"https://www.youtube.com/watch?v={video_id}")
                    
                    thumbnails = entry.get('thumbnails', [])
                    thumbnail_url = thumbnails[-1].get('url', '') if thumbnails else ''
                    
                    parsed = parse_video_title(title)
                    
                    shorts_list.append({
                        "id": video_id,
                        "url": video_url,
                        "title": title,
                        "thumbnail": thumbnail_url,
                        "duration": entry.get('duration', 30),
                        "surah_en": parsed["surah_en"],
                        "reciter_en": parsed["reciter_en"],
                        "surah_ar": parsed["surah_ar"],
                        "reciter_ar": parsed["reciter_ar"],
                        "surah_num": parsed["surah_num"],
                        "ayah_start": parsed["ayah_start"],
                        "ayah_end": parsed["ayah_end"]
                    })
        except Exception as e:
            print(f"Error fetching channel metadata: {e}")
            raise e

    return shorts_list

def download_video(video_id, progress_hook=None):
    """
    Downloads a single YouTube video by ID to the downloads directory.
    Saves it as {video_id}.mp4.
    """
    output_path = os.path.join(DOWNLOADS_DIR, f"{video_id}.mp4")
    
    if os.path.exists(output_path):
        print(f"Video {video_id} already exists locally.")
        return output_path

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(DOWNLOADS_DIR, f"{video_id}.%(ext)s"),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }
    
    if progress_hook:
        ydl_opts['progress_hooks'] = [progress_hook]

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Downloading video {video_id}...")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
        
    return output_path

if __name__ == "__main__":
    # Test cases
    test_titles = [
        "سورة البقرة آية 185 - القارئ ياسر الدوسري",
        "Surah Al-Imran 3:5-7 | Sheikh Al-Sudais",
        "Surah Al-Mulk Verse 1-4 | Maher Al-Muaiqly",
        "تلاوة خاشعة - سورة الكهف 30 | رعد الكردي"
    ]
    for t in test_titles:
        print(f"Title: {t}")
        print(json.dumps(parse_video_title(t), indent=2, ensure_ascii=False))
        print("-" * 30)
