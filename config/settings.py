"""
Quran Reels Maker - Configuration Settings
All application settings in one place
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# PATH CONFIGURATION
# =============================================================================

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
DATABASE_DIR = BASE_DIR / "database"

# Asset paths
FONTS_DIR = ASSETS_DIR / "fonts"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"

# Output paths
VIDEOS_DIR = OUTPUTS_DIR / "videos"
AUDIO_DIR = OUTPUTS_DIR / "audio"

# Database
DATABASE_PATH = DATABASE_DIR / "quran_reels.db"

# YouTube credentials
YOUTUBE_CLIENT_SECRETS = BASE_DIR / "client_secrets.json"
YOUTUBE_TOKEN_PATH = BASE_DIR / "token.pickle"

# Create directories if they don't exist
for directory in [FONTS_DIR, BACKGROUNDS_DIR, VIDEOS_DIR, AUDIO_DIR, DATABASE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# =============================================================================
# VIDEO SETTINGS
# =============================================================================

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 aspect ratio for Shorts
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"

# Text overlay settings
FONT_PATH = str(FONTS_DIR / "amiri" / "Amiri-Bold.ttf")
FONT_COLOR = "white"
TEXT_MAX_WIDTH = 1000  # pixels

# Dynamic font sizing based on word count (increased for better visibility)
FONT_SIZE_CONFIG = {
    "very_long": {"min_words": 60, "font_size": 36, "words_per_line": 8},
    "long": {"min_words": 40, "font_size": 42, "words_per_line": 7},
    "medium_long": {"min_words": 25, "font_size": 52, "words_per_line": 6},
    "medium": {"min_words": 15, "font_size": 62, "words_per_line": 5},
    "short": {"min_words": 0, "font_size": 72, "words_per_line": 5},
}

# =============================================================================
# QURAN API SETTINGS
# =============================================================================

QURAN_TEXT_API = "https://api.alquran.cloud/v1/ayah/{surah}:{ayah}/quran-uthmani"
QURAN_AUDIO_BASE = "https://everyayah.com/data/{reciter}/{surah:03d}{ayah:03d}.mp3"

# Default verses per reel
DEFAULT_VERSES_PER_REEL = 3
MAX_VERSES_PER_REEL = 10
MAX_REEL_DURATION_SECONDS = 59  # YouTube Shorts limit
MIN_REEL_DURATION_SECONDS = 30  # Minimum duration for engagement

# Video effect settings (extracted from video_generator.py)
AYAH_PADDING_SECONDS = 0.48      # Pause between ayahs
BACKGROUND_BRIGHTNESS = 0.55     # Darken background (0.0-1.0)
TEXT_FADE_IN_SECONDS = 0.4       # Text fade-in duration
TEXT_FADE_OUT_SECONDS = 0.4      # Text fade-out duration
AUDIO_FADE_IN_SECONDS = 0.2      # Audio fade-in duration
AUDIO_FADE_OUT_SECONDS = 0.3     # Audio fade-out duration
VIDEO_FADE_SECONDS = 0.8         # Overall video fade in/out

# =============================================================================
# RECITERS
# =============================================================================

RECITERS = {
    "abdul_basit_mujawwad": {
        "id": "AbdulSamad_64kbps_QuranExplorer.Com",
        "name_ar": "الشيخ عبدالباسط عبدالصمد",
        "name_en": "Abdul Basit (Mujawwad)"
    },
    "abdul_basit_murattal": {
        "id": "Abdul_Basit_Murattal_64kbps",
        "name_ar": "الشيخ عبدالباسط عبدالصمد (مرتل)",
        "name_en": "Abdul Basit (Murattal)"
    },
    "sudais": {
        "id": "Abdurrahmaan_As-Sudais_64kbps",
        "name_ar": "الشيخ عبدالرحمن السديس",
        "name_en": "Abdurrahman As-Sudais"
    },
    "maher_muaiqly": {
        "id": "Maher_AlMuaiqly_64kbps",
        "name_ar": "الشيخ ماهر المعيقلي",
        "name_en": "Maher Al-Muaiqly"
    },
    "minshawi_mujawwad": {
        "id": "Minshawy_Mujawwad_64kbps",
        "name_ar": "الشيخ محمد صديق المنشاوي (مجود)",
        "name_en": "Minshawi (Mujawwad)"
    },
    "shuraym": {
        "id": "Saood_ash-Shuraym_64kbps",
        "name_ar": "الشيخ سعود الشريم",
        "name_en": "Saud Ash-Shuraym"
    },
    "alafasy": {
        "id": "Alafasy_64kbps",
        "name_ar": "الشيخ مشاري العفاسي",
        "name_en": "Mishary Alafasy"
    },
    "husary": {
        "id": "Husary_64kbps",
        "name_ar": "الشيخ محمود خليل الحصري",
        "name_en": "Mahmoud Khalil Al-Husary"
    },
    "hudhaify": {
        "id": "Hudhaify_64kbps",
        "name_ar": "الشيخ عبدالله الحذيفي",
        "name_en": "Ali Al-Hudhaify"
    },
    "shaatree": {
        "id": "Abu_Bakr_Ash-Shaatree_128kbps",
        "name_ar": "الشيخ أبو بكر الشاطري",
        "name_en": "Abu Bakr Ash-Shaatree"
    },
    "banna": {
        "id": "mahmoud_ali_al_banna_32kbps",
        "name_ar": "الشيخ محمود علي البنا",
        "name_en": "Mahmoud Ali Al-Banna"
    }
}

# Default reciter
DEFAULT_RECITER = "alafasy"

# =============================================================================
# SURAH DATA
# =============================================================================

VERSE_COUNTS = {
    1: 7, 2: 286, 3: 200, 4: 176, 5: 120, 6: 165, 7: 206, 8: 75, 9: 129, 10: 109,
    11: 123, 12: 111, 13: 43, 14: 52, 15: 99, 16: 128, 17: 111, 18: 110, 19: 98, 20: 135,
    21: 112, 22: 78, 23: 118, 24: 64, 25: 77, 26: 227, 27: 93, 28: 88, 29: 69, 30: 60,
    31: 34, 32: 30, 33: 73, 34: 54, 35: 45, 36: 83, 37: 182, 38: 88, 39: 75, 40: 85,
    41: 54, 42: 53, 43: 89, 44: 59, 45: 37, 46: 35, 47: 38, 48: 29, 49: 18, 50: 45,
    51: 60, 52: 49, 53: 62, 54: 55, 55: 78, 56: 96, 57: 29, 58: 22, 59: 24, 60: 13,
    61: 14, 62: 11, 63: 11, 64: 18, 65: 12, 66: 12, 67: 30, 68: 52, 69: 52, 70: 44,
    71: 28, 72: 28, 73: 20, 74: 56, 75: 40, 76: 31, 77: 50, 78: 40, 79: 46, 80: 42,
    81: 29, 82: 19, 83: 36, 84: 25, 85: 22, 86: 17, 87: 19, 88: 26, 89: 30, 90: 20,
    91: 15, 92: 21, 93: 11, 94: 8, 95: 8, 96: 19, 97: 5, 98: 8, 99: 8, 100: 11,
    101: 11, 102: 8, 103: 3, 104: 9, 105: 5, 106: 4, 107: 7, 108: 3, 109: 6, 110: 3,
    111: 5, 112: 4, 113: 5, 114: 6
}

SURAH_NAMES_AR = [
    'الفاتحة', 'البقرة', 'آل عمران', 'النساء', 'المائدة', 'الأنعام', 'الأعراف', 'الأنفال', 'التوبة', 'يونس',
    'هود', 'يوسف', 'الرعد', 'إبراهيم', 'الحجر', 'النحل', 'الإسراء', 'الكهف', 'مريم', 'طه',
    'الأنبياء', 'الحج', 'المؤمنون', 'النور', 'الفرقان', 'الشعراء', 'النمل', 'القصص', 'العنكبوت', 'الروم',
    'لقمان', 'السجدة', 'الأحزاب', 'سبأ', 'فاطر', 'يس', 'الصافات', 'ص', 'الزمر', 'غافر',
    'فصلت', 'الشورى', 'الزخرف', 'الدخان', 'الجاثية', 'الأحقاف', 'محمد', 'الفتح', 'الحجرات', 'ق',
    'الذاريات', 'الطور', 'النجم', 'القمر', 'الرحمن', 'الواقعة', 'الحديد', 'المجادلة', 'الحشر', 'الممتحنة',
    'الصف', 'الجمعة', 'المنافقون', 'التغابن', 'الطلاق', 'التحريم', 'الملك', 'القلم', 'الحاقة', 'المعارج',
    'نوح', 'الجن', 'المزمل', 'المدثر', 'القيامة', 'الإنسان', 'المرسلات', 'النبأ', 'النازعات', 'عبس',
    'التكوير', 'الانفطار', 'المطففين', 'الانشقاق', 'البروج', 'الطارق', 'الأعلى', 'الغاشية', 'الفجر', 'البلد',
    'الشمس', 'الليل', 'الضحى', 'الشرح', 'التين', 'العلق', 'القدر', 'البينة', 'الزلزلة', 'العاديات',
    'القارعة', 'التكاثر', 'العصر', 'الهمزة', 'الفيل', 'قريش', 'الماعون', 'الكوثر', 'الكافرون', 'النصر',
    'المسد', 'الإخلاص', 'الفلق', 'الناس'
]

SURAH_NAMES_EN = [
    'Al-Fatihah', 'Al-Baqarah', 'Aal-Imran', 'An-Nisa', 'Al-Maidah', 'Al-Anam', 'Al-Araf', 'Al-Anfal', 'At-Tawbah', 'Yunus',
    'Hud', 'Yusuf', 'Ar-Rad', 'Ibrahim', 'Al-Hijr', 'An-Nahl', 'Al-Isra', 'Al-Kahf', 'Maryam', 'Ta-Ha',
    'Al-Anbiya', 'Al-Hajj', 'Al-Muminun', 'An-Nur', 'Al-Furqan', 'Ash-Shuara', 'An-Naml', 'Al-Qasas', 'Al-Ankabut', 'Ar-Rum',
    'Luqman', 'As-Sajdah', 'Al-Ahzab', 'Saba', 'Fatir', 'Ya-Sin', 'As-Saffat', 'Sad', 'Az-Zumar', 'Ghafir',
    'Fussilat', 'Ash-Shura', 'Az-Zukhruf', 'Ad-Dukhan', 'Al-Jathiyah', 'Al-Ahqaf', 'Muhammad', 'Al-Fath', 'Al-Hujurat', 'Qaf',
    'Adh-Dhariyat', 'At-Tur', 'An-Najm', 'Al-Qamar', 'Ar-Rahman', 'Al-Waqiah', 'Al-Hadid', 'Al-Mujadilah', 'Al-Hashr', 'Al-Mumtahanah',
    'As-Saff', 'Al-Jumuah', 'Al-Munafiqun', 'At-Taghabun', 'At-Talaq', 'At-Tahrim', 'Al-Mulk', 'Al-Qalam', 'Al-Haqqah', 'Al-Maarij',
    'Nuh', 'Al-Jinn', 'Al-Muzzammil', 'Al-Muddaththir', 'Al-Qiyamah', 'Al-Insan', 'Al-Mursalat', 'An-Naba', 'An-Naziat', 'Abasa',
    'At-Takwir', 'Al-Infitar', 'Al-Mutaffifin', 'Al-Inshiqaq', 'Al-Buruj', 'At-Tariq', 'Al-Ala', 'Al-Ghashiyah', 'Al-Fajr', 'Al-Balad',
    'Ash-Shams', 'Al-Layl', 'Ad-Duha', 'Ash-Sharh', 'At-Tin', 'Al-Alaq', 'Al-Qadr', 'Al-Bayyinah', 'Az-Zalzalah', 'Al-Adiyat',
    'Al-Qariah', 'At-Takathur', 'Al-Asr', 'Al-Humazah', 'Al-Fil', 'Quraysh', 'Al-Maun', 'Al-Kawthar', 'Al-Kafirun', 'An-Nasr',
    'Al-Masad', 'Al-Ikhlas', 'Al-Falaq', 'An-Nas'
]

# =============================================================================
# YOUTUBE SETTINGS
# =============================================================================

YOUTUBE_CATEGORY_ID = "22"  # People & Blogs (also works: 27 = Education)
YOUTUBE_PRIVACY_STATUS = "public"  # Options: public, private, unlisted
YOUTUBE_MADE_FOR_KIDS = False

# Default tags for all videos
YOUTUBE_DEFAULT_TAGS = [
    "Quran", "القرآن الكريم", "Islam", "إسلام",
    "Quran Recitation", "تلاوة القرآن", "Islamic",
    "QuranShorts", "Shorts"
]

# Title/description templates
YOUTUBE_TITLE_TEMPLATE = "سورة {surah_name_ar} | آية {verse_range} | {reciter_name_ar} #Shorts"
YOUTUBE_DESCRIPTION_TEMPLATE = """🕌 {full_text}

📖 Surah: {surah_name_ar} ({surah_name_en}) - {surah_num}
🔢 Verses: {verse_start} - {verse_end}
🎙️ Reciter: {reciter_name_ar} ({reciter_name_en})

═══════════════════════════════

#Quran #القرآن #Islam #QuranRecitation #Shorts #QuranShorts

═══════════════════════════════

📌 Subscribe for daily Quran recitations!

⚠️ For educational purposes. All recitations belong to their respective owners.
"""

# =============================================================================
# SCHEDULING SETTINGS
# =============================================================================

# Time to post daily (24-hour format)
DAILY_POST_HOUR = 6
DAILY_POST_MINUTE = 0

# Timezone
TIMEZONE = "Africa/Cairo"  # Egypt timezone (UTC+2)

# =============================================================================
# LOGGING
# =============================================================================

LOG_FILE = BASE_DIR / "quran_reels.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"

# =============================================================================
# QURAN API V4 (For Word-by-Word Timings)
# =============================================================================

QURAN_V4_API_BASE = "https://api.quran.com/api/v4"

# Map internal reciter keys to Quran.com V4 Reciter IDs
RECITER_MAPPING_V4 = {
    "alafasy": 7,  # Mishary Rashid Alafasy
    "abdul_basit_murattal": 2, # AbdulBaset AbdulSamad (Murattal)
    "minshawi_mujawwad": 10, # Al-Minshawi (Mujawwad uses different ID?)
    "husary": 5,   # Al-Husary
    "shuraym": 6,  # Sa'ud ash-Shuraym
    "sudais": 3,   # Abdur-Rahman as-Sudais
    # Add others as needed, default to 7 if unknown
}
