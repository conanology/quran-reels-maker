"""Loopback-only compiler. One admitted job across processes; every job owns its data."""
from __future__ import annotations
import json
import asyncio
import os
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import compiler, downloader
from .common import DATA_DIR, BASE_DIR, MAX_CLIPS, MAX_JOB_BYTES, MAX_JOB_SECONDS, JobCancelled, atomic_json, contained, output_name, channel_url, video_id, transition, check_cancel

class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_url: str = Field(min_length=3, max_length=200)
    @field_validator("channel_url")
    @classmethod
    def valid_channel(cls, value): return channel_url(value)

class ClipItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: str
    reciter_name: str = Field(min_length=1, max_length=120)
    surah_name: str = Field(min_length=1, max_length=180)
    attribution_verified: bool = False
    @field_validator("video_id")
    @classmethod
    def valid_id(cls, value): return video_id(value)
    @field_validator("reciter_name", "surah_name")
    @classmethod
    def valid_label(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Reciter and Surah/verse coverage are required, without control characters.")
        return value
    @field_validator("attribution_verified")
    @classmethod
    def reviewed(cls, value):
        if not value: raise ValueError("Confirm each selected clip's attribution against its source recording.")
        return value
    @model_validator(mode="after")
    def require_review(self):
        if not self.attribution_verified:
            raise ValueError("Attribution review is required.")
        return self

class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clips: list[ClipItem] = Field(min_length=1, max_length=MAX_CLIPS)
    transition_duration: float = 1.5
    output_filename: str = "final_compilation.mp4"
    @field_validator("transition_duration")
    @classmethod
    def valid_transition(cls, value): return transition(value)
    @field_validator("output_filename")
    @classmethod
    def valid_filename(cls, value): return output_name(value)
    @model_validator(mode="after")
    def unique_ids(self):
        ids = [c.video_id for c in self.clips]
        if len(ids) != len(set(ids)): raise ValueError("Duplicate source clips are not allowed.")
        return self

class Cancellation:
    def __init__(self, path): self.path = path
    def is_set(self): return self.path.exists()

class JobStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._mutex = threading.RLock()
    def path(self, ident):
        if not re.fullmatch(r"[a-f0-9]{32}", ident): raise HTTPException(404, "Unknown job.")
        return contained(self.root, ident)
    def read(self, ident):
        # Windows can briefly deny a read during atomic replacement. Bound the
        # retry and serialize same-process readers with the status writer.
        with self._mutex:
            for attempt in range(5):
                try:
                    return json.loads((self.path(ident) / "status.json").read_text(encoding="utf-8"))
                except FileNotFoundError:
                    raise HTTPException(404, "Unknown job.")
                except PermissionError:
                    if attempt == 4: raise HTTPException(503, "Job status is temporarily unavailable. Retry shortly.")
                    time.sleep(.02)
                except (ValueError, OSError):
                    raise HTTPException(503, "Job status is unreadable; retain this job for recovery.")
    def update(self, ident, **fields):
        with self._mutex:
            status = self.read(ident)
            status.update(fields)
            atomic_json(self.path(ident) / "status.json", status)
    def reserve(self, kind):
        self.root.mkdir(parents=True, exist_ok=True)
        ident = uuid.uuid4().hex
        lock = self.root / "active.lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Never steal a peer's job or silently retry after a crash.
            raise HTTPException(409, "Another job is active. Wait or cancel it. If the server crashed, see the recovery instructions.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"job_id": ident, "pid": os.getpid()}, handle)
            job = self.path(ident)
            job.mkdir()
            atomic_json(job / "status.json", {"job_id": ident, "kind": kind, "status": "queued", "current": 0, "total": 1, "message": "Job queued", "result": None, "created_at": time.time()})
            return ident
        except BaseException:
            lock.unlink(missing_ok=True)
            raise
    def release(self, ident):
        with self._mutex:
            lock = self.root / "active.lock"
            try:
                owner = json.loads(lock.read_text(encoding="utf-8"))
                if owner.get("job_id") == ident: lock.unlink()
            except FileNotFoundError: pass


def create_app(data_dir=DATA_DIR):
    app = FastAPI(title="Local Quran Clips Compiler")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    store = JobStore(data_dir)
    app.state.jobs = store

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        peer = request.client.host if request.client else ""
        if peer not in {"127.0.0.1", "::1"}: return JSONResponse({"detail": "This reviewer is available only on loopback."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "Use application/json."}, status_code=415)
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 65536: return JSONResponse({"detail": "Request exceeds the 64 KB limit."}, status_code=413)
            except TimeoutError:
                return JSONResponse({"detail": "Request body timed out."}, status_code=408)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https://i.ytimg.com https://img.youtube.com; media-src 'self'; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def runner(ident, work):
        cancel = Cancellation(store.path(ident) / "cancel")
        try:
            check_cancel(cancel)
            result = work(cancel)
            check_cancel(cancel)
            store.update(ident, status="completed", current=1, total=1, message="Ready for review", result=result)
        except JobCancelled as exc:
            store.update(ident, status="cancelled", message=str(exc), result=None)
        except Exception as exc:
            # Our tools expose only bounded, actionable errors; no stderr/credential URLs.
            message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError, FileExistsError, TimeoutError, RuntimeError)) else "Job failed; check the source selection and retry."
            store.update(ident, status="failed", message=message[:500], result=None)
        finally:
            store.release(ident)

    @app.get("/api/shorts")
    def shorts():
        path = store.root / "shorts-cache.json"
        try: return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError: return []
        except (ValueError, OSError): raise HTTPException(500, "Metadata cache is unavailable; fetch the channel again.")

    @app.post("/api/fetch-shorts", status_code=202)
    def fetch(request: FetchRequest, background_tasks: BackgroundTasks):
        ident = store.reserve("fetch")
        def work(cancel):
            store.update(ident, status="fetching", message="Fetching up to 50 source titles; attribution still needs review")
            items = downloader.fetch_shorts_metadata(request.channel_url, cancel=cancel)
            check_cancel(cancel)
            atomic_json(store.root / "shorts-cache.json", items)
            return {"shorts": items}
        background_tasks.add_task(runner, ident, work)
        return {"job_id": ident, "status": "queued"}

    @app.post("/api/compile", status_code=202)
    def compile_request(request: CompileRequest, background_tasks: BackgroundTasks):
        ident = store.reserve("compile")
        def work(cancel):
            job = store.path(ident)
            total_size, total_duration = 0, 0.0
            clips = [c.model_dump() for c in request.clips]
            for idx, clip in enumerate(clips):
                store.update(ident, status="downloading", current=idx, total=len(clips), message=f"Downloading clip {idx+1}/{len(clips)}")
                path = downloader.download_video(clip["video_id"], downloads_dir=job / "downloads", cancel=cancel)
                total_size += Path(path).stat().st_size
                total_duration += compiler.probe_media(path, cancel=cancel)
                if total_size > MAX_JOB_BYTES or total_duration > MAX_JOB_SECONDS:
                    raise ValueError("Selected sources exceed the 1 GB / one-hour job limit.")
            def progress(current, total, message):
                check_cancel(cancel)
                store.update(ident, status="compiling", current=current, total=total, message=message)
            result = compiler.compile_longform(clips, request.output_filename, request.transition_duration, progress, job_dir=job, cancel=cancel)
            result["download_url"] = f"/api/jobs/{ident}/download"
            result["preview_url"] = f"/api/jobs/{ident}/preview"
            return result
        background_tasks.add_task(runner, ident, work)
        return {"job_id": ident, "status": "queued"}

    @app.get("/api/jobs/{ident}")
    def status(ident: str): return store.read(ident)

    @app.post("/api/jobs/{ident}/cancel")
    def cancel(ident: str):
        status = store.read(ident)
        if status["status"] in {"completed", "failed", "cancelled"}: return status
        (store.path(ident) / "cancel").touch()
        return {"job_id": ident, "status": "cancelling"}

    def output(ident, attachment):
        status = store.read(ident)
        if status["status"] != "completed" or status["kind"] != "compile": raise HTTPException(409, "This job has no completed video.")
        name = output_name(status["result"]["output_filename"])
        path = contained(store.path(ident) / "output", name)
        if not path.is_file(): raise HTTPException(404, "Output is missing; start a new compilation.")
        return FileResponse(path, media_type="video/mp4", filename=name if attachment else None)
    @app.get("/api/jobs/{ident}/download")
    def download(ident: str): return output(ident, True)
    @app.get("/api/jobs/{ident}/preview")
    def preview(ident: str): return output(ident, False)

    frontend = BASE_DIR / "frontend"
    @app.get("/assets/amiri.ttf")
    def font():
        from .common import FONT_PATH
        if not FONT_PATH.is_file(): raise HTTPException(404, "Bundled Amiri font is missing.")
        return FileResponse(FONT_PATH, media_type="font/ttf")
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, workers=1)
