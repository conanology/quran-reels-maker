"""Person detection for background video filtering using OpenCV HOG."""
import numpy as np
from pathlib import Path
from typing import List
from loguru import logger

try:
    import cv2
    _hog = cv2.HOGDescriptor()
    _hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    DETECTION_AVAILABLE = True
except Exception as e:
    # Detection is optional, so no OpenCV failure may reach the caller: this module
    # is imported by longform/__init__.py and would otherwise break every command.
    # OpenCV 5.0 removed HOGDescriptor, which raises AttributeError, not ImportError.
    _hog = None
    DETECTION_AVAILABLE = False
    logger.warning(f"Person detection disabled ({type(e).__name__}: {e})")


def has_people(video_path: Path, num_frames: int = 5) -> bool:
    """
    Check whether a video contains visible people.
    Samples `num_frames` evenly spaced frames and runs HOG detection.
    Returns True if people detected in ANY frame.
    Compatibility boolean only; False is not evidence that inspection succeeded.
    Call inspect_people for review/provenance decisions.
    """
    if not DETECTION_AVAILABLE:
        return False
    try:
        frames = _extract_frames(video_path, num_frames)
        for frame in frames:
            if _detect_people_in_frame(frame):
                return True
        return False
    except Exception as e:
        logger.warning(f"Person detection failed for {video_path.name}: {e}")
        return False


def _extract_frames(video_path: Path, num_frames: int) -> List[np.ndarray]:
    """Extract evenly-spaced frames from a video using OpenCV."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            return []
        positions = [int(total * p) for p in np.linspace(0.1, 0.9, num_frames)]
        frames = []
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
        return frames
    finally:
        cap.release()


def _detect_people_in_frame(frame: np.ndarray) -> bool:
    """Run HOG person detector on a single frame."""
    h, w = frame.shape[:2]
    if w > 720:
        scale = 720 / w
        frame = cv2.resize(frame, (720, int(h * scale)))

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detections, weights = _hog.detectMultiScale(
        gray,
        winStride=(8, 8),
        padding=(4, 4),
        scale=1.05,
    )
    for det, weight in zip(detections, weights):
        if weight > 0.3:
            return True
    return False


def inspect_people(video_path: Path, num_frames: int = 5) -> dict:
    """Expose unavailable/unreadable detection instead of asserting people-free."""
    if not DETECTION_AVAILABLE:
        return {"status": "unchecked", "reason": "Detector unavailable"}
    try:
        frames = _extract_frames(Path(video_path), num_frames)
        if not frames:
            return {"status": "unchecked", "reason": "No readable frames"}
        return {"status": "people_detected" if any(_detect_people_in_frame(frame) for frame in frames) else "sampled_no_people",
                "sampled_frames": len(frames), "full_content_verified": False}
    except Exception:
        return {"status": "unchecked", "reason": "Detector failed"}
