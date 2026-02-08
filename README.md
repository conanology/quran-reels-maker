# 🕌 Quran Reels Maker

Automated Quran short video generator for YouTube Shorts. Generates beautiful vertical (9:16) videos with Quranic recitations and text overlays, then automatically uploads them to YouTube.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Features

- **🎬 Automated Video Generation** - Creates vertical 9:16 videos perfect for YouTube Shorts
- **📖 Sequential Quran Journey** - Automatically progresses through the entire Quran
- **🎙️ Multiple Reciters** - Support for 11+ world-famous reciters
- **📤 YouTube Auto-Upload** - Direct upload to YouTube with SEO-optimized metadata
- **🔄 Smart Scheduling** - Never repeat verses, track progress through the Quran
- **🎨 Beautiful Design** - Arabic text with proper Tashkeel on nature backgrounds

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or download the project
cd QuranReelsMaker

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Add Background Videos

Add some nature/landscape videos to the `assets/backgrounds/` folder:
- MP4 format recommended
- Any resolution (will be auto-cropped to 9:16)
- 10-60 second clips work best

### 3. Add Arabic Font

Download an Arabic font and place it in `assets/fonts/`:
- Recommended: Dubai Bold, Amiri, or any Quran-compatible font
- Name it `DUBAI-BOLD.TTF` or update `config/settings.py`

### 4. Generate Your First Reel

```bash
# Generate next verses (auto-selected)
python main.py generate

# Generate specific surah
python main.py generate --surah 112

# Check status
python main.py status
```

## 🎥 YouTube Upload Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable **YouTube Data API v3**
4. Go to Credentials → Create Credentials → OAuth Client ID
5. Choose "Desktop app"
6. Download the JSON and save as `client_secrets.json` in project root

### 2. Authenticate

```bash
python main.py setup-youtube
```

A browser will open for you to authorize the application.

### 3. Auto-Generate and Upload

```bash
# Generate and upload (public)
python main.py auto

# Generate and upload as private (for testing)
python main.py auto --test
```

## 📋 Commands

| Command | Description |
|---------|-------------|
| `python main.py generate` | Generate next reel in sequence |
| `python main.py generate --surah 1` | Generate specific surah |
| `python main.py generate --verses 5` | Set verses per reel |
| `python main.py upload <path>` | Upload existing video |
| `python main.py auto` | Generate AND upload |
| `python main.py auto --test` | Upload as private |
| `python main.py status` | Show progress & stats |
| `python main.py history` | Show recent reels |
| `python main.py set-position 36 1` | Jump to Surah 36, Ayah 1 |
| `python main.py setup-youtube` | Configure YouTube auth |

## ⏰ Scheduled Automation

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task → Name: "Quran Daily Reel"
3. Trigger: Daily at your preferred time
4. Action: Start a program
   - Program: `python`
   - Arguments: `main.py auto`
   - Start in: `D:\05_Work\QuranReelsMaker`

### Linux Cron

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 6 AM)
0 6 * * * cd /path/to/QuranReelsMaker && python main.py auto
```

## 🎙️ Available Reciters

| Key | Reciter |
|-----|---------|
| `alafasy` | Mishary Alafasy (default) |
| `sudais` | Abdurrahman As-Sudais |
| `maher_muaiqly` | Maher Al-Muaiqly |
| `abdul_basit_mujawwad` | Abdul Basit (Mujawwad) |
| `abdul_basit_murattal` | Abdul Basit (Murattal) |
| `husary` | Mahmoud Al-Husary |
| `minshawi_mujawwad` | Minshawi (Mujawwad) |
| `shuraym` | Saud Ash-Shuraym |
| `hudhaify` | Ali Al-Hudhaify |
| `shaatree` | Abu Bakr Ash-Shaatree |
| `banna` | Mahmoud Ali Al-Banna |

```bash
# Use specific reciter
python main.py generate --reciter sudais
```

## 📁 Project Structure

```
QuranReelsMaker/
├── config/
│   └── settings.py          # All configuration
├── core/
│   ├── quran_api.py          # Fetch Quran text
│   ├── audio_processor.py    # Download & process audio
│   ├── video_generator.py    # Create videos with MoviePy
│   └── verse_scheduler.py    # Track progress
├── youtube/
│   ├── auth.py               # OAuth2 authentication
│   └── uploader.py           # YouTube upload
├── database/
│   └── models.py             # SQLite models
├── assets/
│   ├── fonts/                # Arabic fonts
│   └── backgrounds/          # Nature videos
├── outputs/
│   ├── videos/               # Generated reels
│   └── audio/                # Temp audio
├── main.py                   # CLI entry point
└── requirements.txt
```

## ⚙️ Configuration

Edit `config/settings.py` to customize:

- Video dimensions and FPS
- Font sizes and colors
- Default reciter
- Verses per reel
- YouTube metadata templates

## 📊 API Quota

YouTube Data API has a daily quota:
- Default: 10,000 units/day
- Video upload: 1,600 units
- Maximum ~6 uploads/day

For 1 daily reel, the default quota is sufficient.

## 🤝 Credits

- Quran Text API: [alquran.cloud](https://alquran.cloud/)
- Audio: [everyayah.com](https://everyayah.com/)
- Inspired by: [Arabianaischool/Quran-Reels-Generator](https://github.com/Arabianaischool/Quran-Reels-Generator)

## 📜 License

MIT License - See LICENSE file

---

⚠️ **Disclaimer**: This project is for educational purposes. All Quran recitations belong to their respective owners. Please ensure your use complies with Islamic guidelines and YouTube's terms of service.
