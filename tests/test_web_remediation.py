"""Isolated native web regressions: no dotenv, credentials or live network."""
import importlib.util
import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from quran_compiler.backend import common, compiler

@pytest.mark.parametrize("value", ["../escape.mp4", "C:\\escape.mp4", "\\\\host\\share\\x.mp4", "a/b.mp4", "a\\b.mp4", "CON.mp4", "NUL.mp4", "x.mp4.json", "x;bad.mp4", ".mp4"])
def test_output_containment_rejects_unsafe_names(value):
    with pytest.raises(ValueError): common.output_name(value)

@pytest.mark.parametrize("value", ["http://127.0.0.1/a", "https://youtube.com.evil/@test", "https://youtube.com@evil/@test", "https://youtube.com/watch?v=abc", "https://youtube.com/@test?x=1", "https://youtube.com:443/@test", "https://youtube.com/@test#x", "file:///secret"])
def test_only_canonical_youtube_channel_urls(value):
    with pytest.raises(ValueError): common.channel_url(value)

def test_safe_channel_and_symlink_containment(tmp_path):
    assert common.channel_url("@Example") == "https://www.youtube.com/@Example/shorts"
    assert common.channel_url("https://youtube.com/@Example/shorts/") == "https://www.youtube.com/@Example/shorts"
    with pytest.raises(ValueError): common.contained(tmp_path, "../outside")

@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), 99999])
def test_visual_transition_is_finite_and_bounded(value):
    with pytest.raises(ValueError): common.transition(value)

def native():
    pytest.importorskip("fastapi")
    from quran_compiler.backend import main
    from fastapi.testclient import TestClient
    return main, TestClient

def reviewed():
    return {"video_id": "synthetic01", "reciter_name": "Reviewed reciter", "surah_name": "Reviewed coverage 112:1", "attribution_verified": True}

@pytest.mark.parametrize("changes", [{"clips": []}, {"transition_duration": float("inf")}, {"output_filename": "../bad.mp4"}, {"clips": [dict(reviewed(), attribution_verified=False)]}, {"clips": [dict(reviewed(), reciter_name=" ")]}, {"clips": [dict(reviewed(), video_id="../escape")]}, {"clips": [reviewed()]*21}, {"clips": [reviewed(),reviewed()]}])
def test_native_models_reject_invalid_jobs(changes):
    main, _ = native()
    from pydantic import ValidationError
    payload = {"clips": [reviewed()], "transition_duration": 1.5, "output_filename": "test.mp4", **changes}
    with pytest.raises(ValidationError): main.CompileRequest(**payload)

def test_cross_process_store_admission_before_enqueue(tmp_path):
    main, _ = native()
    barrier = Barrier(2)
    stores = [main.JobStore(tmp_path), main.JobStore(tmp_path)]
    def reserve(store):
        barrier.wait()
        try: return store.reserve("compile")
        except main.HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, stores))
    assert sum(isinstance(x,str) for x in results) == 1
    assert 409 in results
    ident = next(x for x in results if isinstance(x,str))
    assert stores[0].read(ident)["status"] == "queued"
    stores[0].release("0"*32)
    assert (tmp_path/"active.lock").exists()
    stores[1].release(ident)
    assert not (tmp_path/"active.lock").exists()

def test_native_mocked_complete_flow_and_owned_output(tmp_path, monkeypatch):
    main, Client = native()
    app = main.create_app(tmp_path)
    def download(ident, *, downloads_dir, cancel):
        Path(downloads_dir).mkdir(parents=True)
        path = Path(downloads_dir)/f"{ident}.mp4"
        path.write_bytes(b"synthetic source")
        return path
    def compile(clips, name, fade, callback, *, job_dir, cancel):
        (job_dir/"output").mkdir()
        (job_dir/"output"/name).write_bytes(b"synthetic output")
        return {"output_filename": name, "recommended_title": "Reviewed", "description": "Reviewed source", "chapters": []}
    monkeypatch.setattr(main.downloader, "download_video", download)
    monkeypatch.setattr(main.compiler, "probe_media", lambda *a,**kw: 1.0)
    monkeypatch.setattr(main.compiler, "compile_longform", compile)
    with Client(app, base_url="http://127.0.0.1", client=("127.0.0.1",50000)) as client:
        ids = []
        for _ in range(2):
            result = client.post("/api/compile", json={"clips":[reviewed()], "output_filename":"same.mp4"})
            assert result.status_code == 202
            ident = result.json()["job_id"]; ids.append(ident)
            status = client.get(f"/api/jobs/{ident}").json()
            assert status["status"] == "completed" and status["job_id"] == ident
            assert client.get(status["result"]["download_url"]).content == b"synthetic output"
        assert ids[0] != ids[1]
        assert len(list(tmp_path.glob("*/output/same.mp4"))) == 2
        assert client.get("/api/jobs/../outside/download").status_code != 200
        assert client.post("/api/fetch-shorts", json={"channel_url":"http://127.0.0.1/internal"}).status_code == 422
        assert client.post("/api/fetch-shorts", json={"channel_url":"@Example"}, headers={"Origin":"https://evil.example"}).status_code == 403
        assert client.post("/api/compile", content="x"*65537, headers={"Content-Type":"application/json"}).status_code == 413
        assert client.get("/", headers={"Host":"evil.example"}).status_code == 400
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]

def test_native_failure_releases_reservation_and_does_not_complete(tmp_path, monkeypatch):
    main, Client = native()
    monkeypatch.setattr(main.downloader,"fetch_shorts_metadata",lambda *a,**kw: (_ for _ in ()).throw(TimeoutError("Synthetic timeout")))
    with Client(main.create_app(tmp_path),base_url="http://127.0.0.1",client=("127.0.0.1",50000)) as client:
        ident=client.post("/api/fetch-shorts",json={"channel_url":"@Example"}).json()["job_id"]
        status=client.get(f"/api/jobs/{ident}").json()
        assert status["status"]=="failed" and status["result"] is None
        assert not (tmp_path/"active.lock").exists()
        assert client.get(f"/api/jobs/{ident}/download").status_code==409

def test_cancel_is_owned_and_checked_before_tool(tmp_path):
    main, _ = native()
    store=main.JobStore(tmp_path); ident=store.reserve("compile")
    marker=store.path(ident)/"cancel"; marker.touch()
    with pytest.raises(common.JobCancelled): common.run_process(["unused"],cancel=main.Cancellation(marker))
    store.release(ident)

def test_runtime_timeout_and_secret_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY","synthetic-no-inherit")
    assert "OPENROUTER_API_KEY" not in common.child_environment()
    with pytest.raises(TimeoutError): common.run_process([sys.executable,"-c","import time; time.sleep(5)"],timeout=.1)

def test_root_manual_scripts_import_no_application(tmp_path):
    root=Path(__file__).resolve().parents[1]
    before=set(sys.modules)
    for name in ("test_ai_pipeline.py","test_growth_engine.py","test_longform_thumbnail.py","test_tiktok.py"):
        spec=importlib.util.spec_from_file_location("legacy_"+name[:-3],root/name)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        assert module.__test__ is False
        with pytest.raises(SystemExit): module.main()
    assert set(sys.modules)==before

def test_media_probe_rejects_missing_audio(tmp_path, monkeypatch):
    path=tmp_path/"synthetic.mp4"; path.write_bytes(b"synthetic")
    monkeypatch.setattr(compiler,"run_process",lambda *a,**kw: json.dumps({"format":{"duration":"1"},"streams":[{"codec_type":"video","width":64,"height":64}]}))
    with pytest.raises(ValueError,match="audio"): compiler.probe_media(path)

@pytest.mark.slow
def test_real_tiny_compilation_preserves_audio_and_owns_temp(tmp_path):
    import shutil
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): pytest.skip("FFmpeg/FFprobe not installed")
    downloads=tmp_path/"downloads"; downloads.mkdir()
    common.run_process(["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-f","lavfi","-i","color=c=blue:s=64x96:r=30:d=0.5","-f","lavfi","-i","sine=frequency=440:duration=0.5","-c:v","libx264","-c:a","aac","-shortest",str(downloads/"synthetic01.mp4")],timeout=30)
    result=compiler.compile_longform([reviewed()],"tiny.mp4",5,job_dir=tmp_path)
    assert result["audio_preserved"] and result["duration_seconds"]>=.5
    assert not list(tmp_path.glob("compile-*"))
    assert compiler.probe_media(tmp_path/"output"/"tiny.mp4") == result["duration_seconds"]
