# Audit remediation decisions and implementation sequence

The owner authorized all audit repairs and delegated product decisions on 2026-09-26. Thumbnail algorithm redesign is a subsequent task. This document records the chosen scope; the original audit remains historical evidence.

## Design

Preserve the existing CLI, MoviePy/FFmpeg renderers and local web reviewer. Add explicit boundaries for validated media, automatic approval, transactional publication state and job-owned files. Repair each audited root cause with isolated regression evidence. A wholesale rewrite would increase migration risk; symptom-only guards would leave incorrect content/state reachable.

- Canonical Quran text and complete verse audio are authoritative. Bind word timings to the exact downloaded recording. Missing expected timings, clipped text or incomplete requested coverage stop the job. Overlong verses fail with an actionable format recommendation, never truncated recitation.
- Automatically published final packages require explicit reviewer identity, intended account identity and approval bound to media/metadata/privacy. Test mode generates only. No live credentials, messages, paid AI or uploads are needed for validation.
- Generation records its own state. Only confirmed publication advances the sequential cursor. Thematic selections have separate state. Preserve remote receipts before committing completion and never retry an uncertain transfer blindly.
- One local publishing job and one web render run at a time. Kernel locks and transactional reservations provide crash-safe ownership; per-job files prevent cleanup interference.
- CI is a serialized verified runner with durable state restored from successful run artifacts. It must fail closed on missing/corrupt state or an unresolved run; it does not merge or push binary SQLite changes. Run artifacts retain media/manifests/receipts for recovery.
- Unknown analytics remain null. Uncalibrated feedback is advisory and experiments remain explicitly unavailable until real reviewed variants and exposure contracts exist. Documentary components remain explicitly unavailable pending a defined complete feature brief; fix concrete validation/import safety without inventing that feature.
- Web is loopback-only by default. External metadata is text, output paths are server-owned, requests have limits and attribution requires confirmation.
- Preserve Quran marks, remove audible recitation fades, record asset provenance and distinguish unchecked background detection from verified content. Qualified authentic typography/listening and separately authorized platform checks remain final operational gates.

## Implementation tasks

1. **Runtime and isolation:** `core/runtime_safety.py`, validated `config/settings.py`, copied-source regression runner under `outputs/remediation/`. Verify atomic-write crash behavior, real concurrent lock exclusion, unchanged production DB hash, and no import-time store creation.
2. **Media:** Quran fetch/timing/audio/render modules and longform compiler. Reproduce cache collision, intro mismatch, timing fallback, overflow and omitted verses; fix and run synthetic real mux/browser checks.
3. **Publishing/state:** models/migrations/jobs, scheduler, Telegram policy, OAuth/uploaders and CLI. Test all approval/test-mode transitions, singleton/reservations, cursor overrides, lock recovery, receipts and processing outcomes against mocked transports/disposable SQLite.
4. **Web/documentary:** native local backend, frontend, strict requests/paths, ownership/status/error flows and unavailable feature gates. Exercise synthetic fetch/select/order/render/poll/download at desktop/mobile; retain screenshots.
5. **Growth/automation/assets:** true read-only dry-run, truthful coverage titles, nullable metrics/advisory feedback, safe serialized workflows/artifact persistence, bounded verified downloads/history/provenance and supported dependency gates.
6. **Integration/review:** full isolated baseline plus defect regressions, safe broad discovery, source/workflow checks, real FFmpeg/Chromium fixtures, and audit-ID disposition ledger. Commit only intended source/tests/docs after verified completion; never push unless asked.

The published cursor migration must be explicit: existing generated history is not proof of publication. Preserve a backup and do not infer or overwrite production progression during implementation.
