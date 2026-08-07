"""
Tests for core.person_detector module

Regression guard for the outage that started 2026-07-03: OpenCV 5.0.0 removed
cv2.HOGDescriptor, and the module-level guard here only caught ImportError. The
resulting AttributeError propagated through longform/__init__.py into every CLI
command, taking both scheduled workflows down for five weeks.
"""
import importlib
import sys

import pytest

cv2 = pytest.importorskip("cv2")

_LONGFORM_MODULES = ("longform", "core.person_detector")


@pytest.fixture
def opencv_without_hog(monkeypatch):
    """Simulate OpenCV 5.x, where the HOG person detector no longer exists."""
    monkeypatch.delattr(cv2, "HOGDescriptor", raising=False)
    monkeypatch.delattr(cv2, "HOGDescriptor_getDefaultPeopleDetector", raising=False)
    _purge_modules()
    yield
    _purge_modules()


def _purge_modules():
    """Drop cached imports so the next import re-runs the module-level guard."""
    for name in list(sys.modules):
        if name in _LONGFORM_MODULES or name.startswith("longform."):
            del sys.modules[name]


class TestDetectionUnavailableFallback:
    """Person detection is a nice-to-have and must degrade, never crash."""

    def test_import_survives_missing_hog_descriptor(self, opencv_without_hog):
        """Importing must disable detection rather than raise AttributeError"""
        detector = importlib.import_module("core.person_detector")

        assert detector.DETECTION_AVAILABLE is False

    def test_has_people_returns_false_when_detection_unavailable(
        self, opencv_without_hog, tmp_path
    ):
        """The conservative answer is 'no people', so backgrounds still get used"""
        detector = importlib.import_module("core.person_detector")

        assert detector.has_people(tmp_path / "missing.mp4") is False

    def test_longform_package_imports_without_hog(self, opencv_without_hog):
        """The actual outage path: longform -> background_renderer -> person_detector"""
        importlib.import_module("longform")


class TestDetectionAvailable:
    """With a working OpenCV the detector should still be wired up."""

    def test_detection_enabled_when_hog_present(self):
        detector = importlib.import_module("core.person_detector")

        if not hasattr(cv2, "HOGDescriptor"):
            pytest.skip("Installed OpenCV has no HOG detector")

        assert detector.DETECTION_AVAILABLE is True

    def test_has_people_handles_unreadable_video(self, tmp_path):
        """A missing file must return False, not propagate an OpenCV error"""
        detector = importlib.import_module("core.person_detector")

        assert detector.has_people(tmp_path / "missing.mp4") is False
