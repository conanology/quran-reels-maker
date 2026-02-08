# Arabic Fonts

Place your Arabic font files here.

## Required Font
The default configuration expects: `DUBAI-BOLD.TTF`

## Recommended Free Fonts

### Dubai Font (Recommended)
- Download from: https://dubaifont.com/
- Use: `DUBAI-BOLD.TTF` or `DUBAI-MEDIUM.TTF`

### Amiri Font
- Download from: https://fonts.google.com/specimen/Amiri
- Good for classic Quranic style

### Scheherazade New
- Download from: https://fonts.google.com/specimen/Scheherazade+New
- Optimized for Arabic typography

### Noto Naskh Arabic
- Download from: https://fonts.google.com/noto/specimen/Noto+Naskh+Arabic
- Google's comprehensive Arabic font

## After Adding Font
If you use a different font name, update `config/settings.py`:
```python
FONT_PATH = str(FONTS_DIR / "YOUR-FONT-NAME.TTF")
```
