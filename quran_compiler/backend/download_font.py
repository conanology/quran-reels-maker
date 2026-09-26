"""The Amiri font is bundled; this compatibility utility does not download at import."""
from pathlib import Path

def main():
    path = Path(__file__).resolve().parent / "assets" / "fonts" / "Amiri-Regular.ttf"
    if not path.is_file() or path.stat().st_size < 1024:
        raise SystemExit("Bundled font is missing. Restore backend/assets/fonts/Amiri-Regular.ttf from the project checkout.")
    print("Bundled Amiri font is available.")

if __name__ == "__main__":
    main()
