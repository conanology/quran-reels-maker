"""Unavailable feature and reusable helper gates, entirely synthetic."""
import json
import sys
import types
from pathlib import Path
import pytest
import documentary
from documentary.cost_tracker import APICostTracker
from documentary import quality_validator as quality
from documentary.stock_provider import DocumentaryStockProvider, StockAssetResult

def test_unfinished_documentary_cannot_be_enabled():
    assert documentary.AVAILABLE is False
    with pytest.raises(RuntimeError,match="incomplete"): documentary.require_available()

def test_cost_unknown_cache_and_concurrency_are_truthful(tmp_path):
    tracker=APICostTracker(enabled=True)
    tracker.start_episode(tmp_path)
    tracker.record_cache_hit(category="text",operation="cached",model="synthetic")
    tracker.record_event(category="text",operation="unpriced",model="synthetic")
    with pytest.raises(RuntimeError): tracker.start_episode(tmp_path/"another")
    with pytest.raises(ValueError): tracker.record_event(category="text",operation="bad",model="synthetic",estimated_cost_usd=float("nan"))
    path=tracker.finalize_episode()
    totals=json.loads(path.read_text())["totals"]
    assert totals["api_calls"]==1 and totals["cache_hits"]==1 and totals["unpriced_calls"]==1
    assert totals["estimated_cost_usd"] is None
    assert not list(tmp_path.glob("*.tmp"))

def test_budget_does_not_allow_unknown_or_over_budget_event(tmp_path):
    tracker=APICostTracker(enabled=True,budget_usd=1)
    tracker.start_episode(tmp_path)
    with pytest.raises(RuntimeError): tracker.record_event(category="text",operation="unknown",model="synthetic")
    with pytest.raises(RuntimeError): tracker.record_event(category="text",operation="expensive",model="synthetic",estimated_cost_usd=2)

def test_final_video_needs_audio_and_executed_checks(tmp_path,monkeypatch):
    path=tmp_path/"synthetic.mp4"; path.write_bytes(b"synthetic")
    monkeypatch.setattr(quality,"ffprobe_media",lambda p: {"format":{"duration":"2","size":"9"},"streams":[{"codec_type":"video","width":640,"height":360}]})
    monkeypatch.setattr(quality,"detect_black_segments",lambda p: (_ for _ in ()).throw(quality.QualityCheckUnavailable("synthetic")))
    monkeypatch.setattr(quality,"detect_freeze_segments",lambda p: [])
    monkeypatch.setattr(quality,"_video_has_people_best_effort",lambda p: None)
    result=quality.validate_final_video(path)
    assert not result.ok
    assert {"missing_audio_stream","black_check_unavailable","people_check_unavailable_requires_review"}.issubset(result.reasons)

def test_cached_stock_retains_provenance_and_rejects_partial_corruption(tmp_path):
    provider=DocumentaryStockProvider(api_key="synthetic",cache_dir=tmp_path)
    path=tmp_path/"source.mp4"; path.write_bytes(b"complete synthetic media")
    assert provider._cached_asset(path) is None
    asset=StockAssetResult(path=path,source_kind="pexels_video",provider_id="synthetic",source_url="https://www.pexels.com/video/synthetic",creator="Synthetic creator",query="desert")
    provider._save_provenance(asset)
    cached=provider._cached_asset(path)
    assert cached.source_url==asset.source_url and cached.creator==asset.creator
    path.write_bytes(b"partial")
    assert provider._cached_asset(path) is None
    provider.close()

@pytest.mark.parametrize("mode", ["missing", "order", "translation"])
def test_quran_payload_cannot_claim_incomplete_text_or_translation(monkeypatch,mode):
    from documentary.quran_scene_resolver import resolve_quran_verse_payload
    ayat=[{"ayah":1,"text":"Exact synthetic text 1"},{"ayah":2,"text":"Exact synthetic text 2"}]
    if mode=="missing": ayat.pop()
    if mode=="order": ayat.reverse()
    stub=types.ModuleType("core.quran_api")
    stub.get_multiple_ayat=lambda *a:ayat
    stub.get_ayah_translation=lambda *a:None if mode=="translation" else "Synthetic translation"
    stub.get_surah_name=lambda *a:"Synthetic Surah"
    stub.validate_verse_range=lambda s,a,b:(a,b)
    monkeypatch.setitem(sys.modules,"core.quran_api",stub)
    with pytest.raises(ValueError): resolve_quran_verse_payload("1:1-2")
