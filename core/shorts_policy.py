"""The owner's explicit voice policy for future Shorts."""
from config.settings import SHORTS_RECITERS


def require_shorts_reciter(reciter_key):
    if reciter_key not in SHORTS_RECITERS:
        raise ValueError("Shorts reciter must be minshawi_mujawwad, banna or yasser_dossari")
    return reciter_key
