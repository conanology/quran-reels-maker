# Quran Reels Maker

Generate Quran recitation videos locally, review the final content, and publish through explicit YouTube/TikTok routes. Arabic Shorts use browser-shaped word highlights for mapped reciters; longform generation requires complete requested verse coverage. The separate [local web compiler](quran_compiler/README.md) reviews and joins existing clips and has no publishing endpoint.

## Install and generate

Use Python 3.11+ with FFmpeg/FFprobe on PATH. Python 3.14 on Windows is locally verified; the workflows include a clean Python 3.11/Linux regression gate. Use the project interpreter explicitly if another application's Python is on PATH.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chromium
.\venv\Scripts\python.exe main.py generate --surah 112 --start 1 --end 4 --reciter alafasy
```

For Linux, use `venv/bin/python` and `python -m playwright install --with-deps chromium`. Add reviewed nature backgrounds to `assets/backgrounds/`. Bundled fonts are used; the active style selects its font. Record source/creator/license review with each asset rather than treating a download as rights clearance. Missing backgrounds/fonts, expected timing failures, overlong first verses and incomplete longform coverage stop generation visibly.

Copy `.env.example` to `.env` for local configuration. Default reciter is alafasy, CPU encoder is libx264, Shorts target is 59 seconds (a product default, configurable up to 180). `VIDEO_ENCODER=h264_nvenc` is explicit; `_detect_encoder()` provides a real runtime probe for integrations instead of trusting advertised encoders. Imports do not create output directories, database tables or log files.

Generated files have a `.manifest.json` sidecar with verified stream durations, exact verse/recording coverage, reciter, audio/video checksums, background provenance and content-review requirements. Do not distribute or publish a failed/partial artifact merely because an MP4 exists. Actual recording identity, Uthmani marks, basmala boundaries and pronunciation require a qualified visual/listening review. No automated test certifies those domain properties.

## Commands and publication policy

| Command | Behavior |
| --- | --- |
| `generate --surah 112 --start 1 --end 4 --reciter alafasy` | Generate local content; does not advance published progress. |
| `generate --dry-run` | Read-only illustrative selection, no rendering or store changes. |
| `auto --test` | Generate only; no review messages or platform uploads. |
| `auto --dry-run` | No generation, account calls or state changes. |
| `auto` / `batch` | Reserve content, review final package and publish; one automatic job at a time. |
| `upload <path> --privacy private` | Explicit manual upload; this is an external mutation, separate from test mode. |
| `tiktok <path> --surah 112 --start 1 --end 4 --reciter alafasy` | Explicit manual TikTok route; valid attribution required. |
| `longform compile --surah 112 --reciter alafasy` | Local complete-coverage compilation. |
| `longform auto --test` | Preview mode skips automatic generation and publication; use `longform compile` for local rendering. |
| `longform auto` | Reserve/review/publish the next complete group. |
| `growth-engine run --slot morning_short --dry-run` | Illustrative decision without settings/auth/analytics writes. |
| `growth-engine run-feedback` | Advisory observations; no automatic penalties or fabricated metric-driven selection. |
| `status`, `history`, `longform status` | Inspect local progression and receipts/history. |
| `set-position 36 1` | Explicitly reconcile/reset the published journey after reviewing previous coverage. |
| `setup-youtube`, `setup-tiktok` | Explicit interactive authorization; automatic routes cannot silently start OAuth. |

Automatic publishing always requires `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_APPROVER_ID` and `YOUTUBE_EXPECTED_CHANNEL_ID`. Set `TIKTOK_EXPECTED_OPEN_ID` before separately enabling `ENABLE_TIKTOK_AUTOPUBLISH=true`. Missing configuration, failed delivery, wrong account, rejected/expired approval or changed media/metadata/thumbnail stops transfer. `APPROVAL_REQUIRED=false` cannot bypass this boundary. Approval replies must target the specific video and include its nonce and package hash. Legacy cookie/browser TikTok posting is disabled because it cannot verify privacy/account/completion.

Test mode never uploads privately or publicly. A manual private upload remains a real platform mutation. Transfers, processing completion and public publication are distinct outcomes. YouTube/TikTok account processing is polled with bounded deadlines; durable transfer attempts/receipts prevent blind retransfers after a crash. A timeout is an unresolved outcome, not permission to post again.

Only confirmed public sequential publication advances the journey. Friday/thematic selections have separate reservations. Existing progress from the old generation-based model requires explicit reconciliation; it is not evidence of published coverage. Schema migration backs up legacy state and does not choose/delete competing cursors.

AI metadata is disabled by default (`ENABLE_AI_METADATA=false`). Enabled output is a bounded suggestion requiring final review; canonical Quran text/translation attribution is authoritative. Unavailable CTR/retention stays null. Automatic experiment promotion, synthetic A/B variants and the incomplete sleep/weekly/documentary formats are unavailable until their content/exposure contracts are implemented. See [documentary status](documentary/README.md). Thumbnail generation logic is retained for the next separately requested refactor; final thumbnail bytes participate in approval.

## Scheduling and recovery

Workflows share one concurrency group and use typed inputs/environment values as literal arguments. They do not commit/rebase/push binary SQLite state. Morning is 05:00–07:00 Asia/Riyadh; evening is 21:00–23:00 except Friday, when the complete longform slot uses that window. Sleep automation is unavailable. Late/outside-window runs skip rather than publish a different format; Cairo daylight saving is not a fixed UTC+2 assumption.

Repository variable `AUTOMATED_PUBLISHING_ENABLED=true` is an operational enablement gate after domain, account and state review. Actual workflow publication is restricted to the repository default branch; previews remain available on other branches. Configure review secrets/expected channel and reviewed initial state before enablement. A first checkpoint allows `QRM_ALLOW_STATE_BOOTSTRAP=true` only when prior workflow history proves no publication attempt; remove that allowance after the first successful checkpoint. Earlier/unknown publication history requires deliberate checkpoint recovery. Missing/expired/corrupt state or later publishing activity without its expected checkpoint blocks publication. Automated reruns also require explicit remote/state reconciliation.

Authoritative state is uploaded as the `qrm-publishing-state` run artifact, including SQLite, background history, transfer attempts and receipts, with checksum validation on restore. Retention is 90 days, so archive an independent backup before expiry; this is not indefinite storage. Media/recovery evidence is retained separately for 14 days. A failed transfer retains job files and receipts instead of cleaning them before recovery. Artifact upload failure also blocks later runs from silently using stale state.

To recover, stop automatic jobs, preserve the last checkpoint plus failed-run media/attempts/receipts, verify actual platform processing/privacy/account outcomes, and reconcile local history/cursor against confirmed remote IDs. Do not delete an uncertain transfer marker or reserve new sequential content until that remote outcome is known. `set-position` is a deliberate cursor action, not remote receipt reconciliation. Re-enable scheduling only after recovered state has a new valid checkpoint. No automatic workflow was run or enabled during remediation.

`QRM_OUTPUTS_DIR`, `QRM_DATABASE_DIR`, `QRM_DATABASE_PATH`, `QRM_ASSETS_DIR` and `QRM_LOG_FILE` allow isolated storage. Background downloads are atomic, probed and limited to 256 MiB/ten minutes; each cache admits at most 20 new assets and never automatically evicts files another render may use. Archive inactive assets deliberately with jobs stopped. Logs and credentials must remain private; no token files are included in run artifacts or Git.

## Verification and documentation

Install the separate web/test dependencies to run the whole suite:

```powershell
.\venv\Scripts\python.exe -m pip install -r quran_compiler/backend/requirements.txt
.\venv\Scripts\python.exe -B scripts/checks.py tests
```

The remediation runner copies current source/fonts/frontend/workflows into a sandbox, disables dotenv/live secrets, blocks external network calls, uses disposable state, and checks the production database hash. Real Chromium and tiny FFmpeg media checks are included. Legacy root manual test scripts are inert; broad test discovery cannot delete production tables or start live AI/upload calls. CI runs isolated tests before restoring credentials.

- [Historical audit](docs/audit-report.md)
- [Remediation decisions](docs/remediation-decisions.md)
- [Remediation implementation status](docs/remediation-status.md)
- [YouTube account setup](docs/youtube_setup_guide.md)

Platform quota, processing and Shorts eligibility depend on the current account/project and official rules. Consult [YouTube upload reference](https://developers.google.com/youtube/v3/docs/videos/insert), [processing status](https://developers.google.com/youtube/v3/guides/implementation/videos), [Shorts guidance](https://support.google.com/youtube/answer/15424877) and [TikTok posting status](https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status). Local title scores are heuristics, not measured vidIQ scores or a promise of reach.
