"""
Visual Randomizer - Generate subtle random FFmpeg filter parameters.
Keeps variation gentle and reverent — this is Quran content.
"""
import random
from typing import Dict, List


# ---------------------------------------------------------------------------
# Individual randomizers
# ---------------------------------------------------------------------------

def get_random_color_grade() -> Dict[str, float]:
    """
    Return random FFmpeg ``colorbalance`` filter values.

    Produces one of three tint families (warm / cool / neutral) with very
    subtle shifts so the video never looks garish.

    Returns:
        dict with keys 'rs', 'gs', 'bs' (shadow-channel balance values).
    """
    tint = random.choice(["warm", "cool", "neutral"])

    if tint == "warm":
        return {
            "rs": round(random.uniform(0.03, 0.08), 3),
            "gs": round(random.uniform(-0.03, 0.01), 3),
            "bs": round(random.uniform(-0.05, -0.01), 3),
        }
    elif tint == "cool":
        return {
            "rs": round(random.uniform(-0.05, -0.01), 3),
            "gs": round(random.uniform(-0.02, 0.02), 3),
            "bs": round(random.uniform(0.02, 0.07), 3),
        }
    else:  # neutral
        return {
            "rs": round(random.uniform(-0.02, 0.02), 3),
            "gs": round(random.uniform(-0.02, 0.02), 3),
            "bs": round(random.uniform(-0.02, 0.02), 3),
        }


def get_random_ken_burns() -> Dict:
    """
    Return random Ken-Burns zoom + pan parameters.

    Zoom range is kept very subtle (1.0 → ~1.05) to avoid distracting motion.

    Returns:
        dict with 'zoom_start', 'zoom_end', 'pan_x', 'pan_y'.
    """
    zoom_end = round(random.uniform(1.03, 1.08), 3)

    # ~30 % chance of zoom-out instead of zoom-in
    if random.random() < 0.3:
        zoom_start = zoom_end
        zoom_end = 1.0
    else:
        zoom_start = 1.0

    pan_x = random.choice(["left", "right", "center"])
    pan_y = random.choice(["up", "down", "center"])

    return {
        "zoom_start": zoom_start,
        "zoom_end": zoom_end,
        "pan_x": pan_x,
        "pan_y": pan_y,
    }


def get_random_transition_duration() -> float:
    """
    Return a random crossfade / transition duration between 2.5 and 4.5 s.
    """
    return round(random.uniform(2.5, 4.5), 2)


def get_random_overlay_opacity() -> float:
    """
    Return a random dark-overlay opacity between 0.3 and 0.5.

    The overlay is drawn on top of the background footage to ensure white
    Arabic text remains legible.
    """
    return round(random.uniform(0.3, 0.5), 2)


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------

def generate_segment_style() -> Dict:
    """
    Combine all individual randomizers into a single style dict for one
    video segment.

    Returns:
        dict with keys 'color_grade', 'ken_burns', 'transition_duration',
        'overlay_opacity'.
    """
    return {
        "color_grade": get_random_color_grade(),
        "ken_burns": get_random_ken_burns(),
        "transition_duration": get_random_transition_duration(),
        "overlay_opacity": get_random_overlay_opacity(),
    }


def generate_compilation_style(num_segments: int) -> List[Dict]:
    """
    Generate a list of visual styles, one per segment in a compilation.

    Rules:
      * The first segment always has a longer fade-in (5 s) so the video
        opens gently.
      * All segments share the *same* Ken-Burns direction but get slightly
        different colour grades for organic variation.

    Args:
        num_segments: number of segments in the compilation.

    Returns:
        List of style dicts (length == num_segments).
    """
    if num_segments <= 0:
        return []

    # Shared across the whole compilation
    shared_ken_burns = get_random_ken_burns()
    shared_overlay = get_random_overlay_opacity()

    styles: List[Dict] = []
    for i in range(num_segments):
        style = {
            "color_grade": get_random_color_grade(),
            "ken_burns": shared_ken_burns,
            "transition_duration": get_random_transition_duration(),
            "overlay_opacity": shared_overlay,
        }

        # First segment: longer fade-in
        if i == 0:
            style["transition_duration"] = 5.0

        styles.append(style)

    return styles
