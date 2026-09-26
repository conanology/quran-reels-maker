import json
from unittest.mock import MagicMock
import pytest
from core.asset_provenance import download_background_asset
from core.person_detector import inspect_people
from core import ai_brain


def test_failed_download_never_becomes_reusable_media(tmp_path, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.side_effect = OSError("interrupted stream")
    monkeypatch.setattr("core.asset_provenance.requests.get", lambda *a, **kw: response)
    target = tmp_path / "background.mp4"
    with pytest.raises(OSError):
        download_background_asset(target, "https://example.invalid/video", {"provider": "fixture"})
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


def test_detection_missing_file_is_unchecked(tmp_path):
    assert inspect_people(tmp_path / "missing.mp4")["status"] == "unchecked"


def test_default_metadata_makes_no_ai_call(monkeypatch):
    monkeypatch.delenv("ENABLE_AI_METADATA", raising=False)
    def forbidden(*args):
        raise AssertionError("unapproved paid call")
    monkeypatch.setattr(ai_brain, "call_openrouter", forbidden)
    assert ai_brain.generate_video_metadata("Al-Fatihah", 1, 1, "alafasy", "fixture") == {}


def test_canonical_metadata_needs_no_optional_translation_service(monkeypatch):
    from youtube.uploader import generate_metadata
    monkeypatch.delenv("ENABLE_AI_METADATA", raising=False)
    def forbidden(*args):
        raise AssertionError("Canonical metadata must not fetch an unused translation")
    monkeypatch.setattr("core.quran_api.get_ayah_translation", forbidden)
    metadata = generate_metadata(1, 1, 3, "alafasy", full_text="Synthetic reviewed text")
    assert "1-3" in metadata["title"]
    assert "Synthetic reviewed text" in metadata["description"]


@pytest.mark.parametrize("tags", ["Quran", [1], [""], ["Quran" * 100]])
def test_bad_ai_metadata_rejected_before_review(tags, monkeypatch):
    monkeypatch.setenv("ENABLE_AI_METADATA", "true")
    monkeypatch.setattr(ai_brain, "call_openrouter", lambda *args: json.dumps({
        "title": "Fixture", "description": "Fixture", "tags": tags}))
    assert ai_brain.generate_video_metadata("Al-Fatihah", 1, 1, "alafasy", "fixture") == {}
