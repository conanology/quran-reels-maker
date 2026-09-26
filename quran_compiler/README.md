# Local Quran Clips Compiler

This separate app imports source titles, lets a reviewer identify the actual recording/reciter/verse coverage, and compiles selected clips. It does not publish. Titles supply suggestions only; every selected label requires explicit human confirmation. Unknown labels remain blank. A selected clip compilation never claims complete Surah coverage.

## Run

Use Python 3.11 or newer and FFmpeg/FFprobe on PATH. From the repository root, in a dedicated virtual environment:

```powershell
python -m pip install -r quran_compiler/backend/requirements.txt
python -m quran_compiler.backend.main
```

Open http://127.0.0.1:8000. The supported deployment is one worker on loopback. Peer/Host/Origin checks reject remote and cross-origin requests. Do not expose this unauthenticated reviewer via a public proxy. Bundled Amiri is used without external font downloads. Python module imports create no storage or contact any service.

`QURAN_COMPILER_DATA_DIR` sets a dedicated storage directory; the default is `quran_compiler/data/jobs`. No CLI credentials or dotenv are loaded. Each request receives an opaque job ID, owns downloads/temp/output/status, and polls `/api/jobs/{job_id}`. The API admits one job at a time using an atomic filesystem lock, including across processes. It rejects overlapping requests with 409 before enqueueing. Compilation includes downloads in one job; the former separate global download/status endpoints are retired.

## Limits and review

- Only HTTPS youtube.com channel URLs/handles and 11-character YouTube video IDs are accepted. Arbitrary/private-network URLs cannot enter an extractor; only YouTube extractors are enabled and user yt-dlp configuration/cookies are ignored.
- Up to 50 metadata entries and 20 distinct clips per compilation. Each clip is at most 10 minutes / 256 MB; total source material is at most one hour / 1 GB. Requests are at most 64 KB. Output is capped at 2 GB and probed for audio/video and matching duration before success.
- Network tools/processes have bounded deadlines and cancellation. A cancelled/failed job cannot supply a completed download. Retry creates a new job and retains selection/order. Output names are simple MP4 basenames inside the job; the same name in another job cannot overwrite it.
- Visual fades are limited to half each clip. Audio is retained without fades, speed changes or trimming; AAC encoding is a format conversion, not proof of identical samples. Listen to the full boundaries and verify labels/text before distributing. Preview and Download refer to the same completed job.
- Source rights, recording identity, Quran accuracy and any translation attribution require content review. A checkbox records the reviewer's confirmation; it is not automated verification of the recording.

## Recovery and storage

Status JSON is written atomically. A server crash leaves an active lock deliberately blocking new work so a second process cannot steal a running job. Stop all compiler processes first, inspect the job ID/status in `active.lock`, retain its artifacts for review, and remove only that stale lock from the configured storage directory before restarting. An interrupted compilation must be retried as a new job; no publication occurs. Never remove a lock while a peer process runs.

Jobs retain outputs and diagnostics for review. Archive/delete individual terminal job directories deliberately when no reader or process uses them; never bulk-clean an active storage directory. Current limits bound one job, not total retained history. Data is private to the local reviewer; no shared account identity is used.

## Verification

`tests/test_web_remediation.py` exercises native request validation, owned jobs, concurrency, cancellation and media probes with synthetic files and mocked downloads. Browser validation uses synthetic API/media responses at desktop and mobile sizes. Legacy root/web manual scripts are inert and cannot accidentally use production credentials/state. Live YouTube/API tests require separate explicit authorization.

Dependency contracts checked 2026-09-26 against primary [FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/), [Pydantic](https://pypi.org/project/pydantic/) and [yt-dlp](https://pypi.org/project/yt-dlp/) documentation. The separate requirements bound compatible major/calendar versions; test the resolved versions before upgrading.
