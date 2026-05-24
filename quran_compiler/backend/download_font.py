import os
import urllib.request

font_url = "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf"
output_dir = r"C:\Users\acona\.gemini\antigravity\scratch\quran_compiler\backend\assets\fonts"
output_path = os.path.join(output_dir, "Amiri-Regular.ttf")

os.makedirs(output_dir, exist_ok=True)

print(f"Downloading Amiri font from {font_url}...")
try:
    urllib.request.urlretrieve(font_url, output_path)
    print(f"Successfully downloaded to {output_path}")
except Exception as e:
    print(f"Error downloading font: {e}")
