# Quran Reels Maker — prioritized remediation plan

**Basis:** [audit report](audit-report.md), commit `b9cabd4dcf48320640822436e2cfbef0e0c59a5d`, audit2026-09-26. This plan proposes fixes; none were implemented by the audit.

Effort ranges are approximate engineer-days for one developer familiar with Python, SQLAlchemy, FFmpeg and the current code. They include focused regression tests, exclude platform approval delays and qualified Quran/content review, and assume existing architecture is retained. Overlapping scopes share tests, so estimates should not be added mechanically.

## 1. Must address before unattended publishing

### A. Establish one publishing policy and approval record

**Findings:** QRM-09, QRM-10, QRM-11, QRM-30; identity/OAuth risks in report section5.

**Scope:** central automatic gate used by auto/batch/growth and explicitly configured longform automation. Persist job/media/metadata hash, intended account/platform/privacy, approved sender/request and decision. Fail closed for missing required config or failed review delivery. Obtain review after final metadata exists. Keep explicit manual upload as an intentional separate route. Suppress TikTok in private test mode until that route can guarantee privacy.

**Order/dependencies:** first define route-specific expected account and approval policy with the owner; use reservation/job ID fromB. No real OAuth/posting is needed for implementation tests.

**Acceptance:**

- Matrix of every automatic route × missing config/delivery failure/rejection/timeout/regeneration/private test has zero unauthorized platform calls.
- Immediate valid approval is accepted; wrong sender, another video, stale nonce and concurrent review do not approve current content.
- Final approved artifact hash includes metadata and privacy; changing any invalidates approval.
- Expected YouTube channel/TikTok identity is checked before posting; cookie/API precedence is explicit.
- Private test never issues PUBLIC_TO_EVERYONE or browser Post with unknown privacy.

**Effort:** 2–4days; identity-policy decision needed before authorized integration. Mock contracts first; live account/private upload requires separate authorization.

### B. Separate reservation, generation and publication state; make recovery durable

**Findings:** QRM-12, QRM-13, QRM-14, QRM-15, QRM-20, QRM-21, QRM-24, QRM-29.

**Scope:** transactional job/content/slot reservation with unique idempotency key; single validated journey cursor; thematic overrides keep separate state. Store pending/rejected/failed/transfer/processing/published states and upload receipts. Regeneration retains verse range. Apply rollback/retry to the entire idempotent DB transaction. Add migration and recovery path instead of relying on create_all. Own files by job. Stop excluding failed-upload “compiled” groups from recovery.

**Order/dependencies:** implement source-of-truth reservation/cursor before wiringA, C andG. Start with local transactional state and explicit serialized writer; choose CI durable owner inF before restoring unattended runs.

**Acceptance:**

- Fresh Fatihah completion yields2:1; existing/fresh last Quran verse yields1:1; Kahf override never corrupts another surah.
- Rejection/timeout/regeneration/failed upload leave publication coverage unchanged and recoverable; regeneration exhaustion exits before upload.
- Two synchronized workers reserve once and cannot lose counter updates; singleton constraint enforced.
- Lock released after failed flush results in exactly one intended transaction; persistent lock ends within a bounded deadline.
- Crash after remote transfer receipt and before history commit reconciles that receipt without reposting.
- History/progress changes are atomic; migration/backup restore tested with synthetic previous schema.
- Peer job cleanup cannot delete/read/overwrite another's files or states.

**Effort:** 3–6days for reservation/recovery/schema/files and tests; CI storage selection may add integration work. Avoid redesigning rendering while making this transaction boundary concrete.

### C. Bind recitation, Quran words and timing as one validated media bundle

**Findings:** QRM-01, QRM-04, QRM-17, QRM-37; reciter label/basmala questions.

**Scope:** fetch timing-associated audio from a consistent source; persist requested/resolved reciter, recording source URL/checksum, verse identity, words/positions, decoded duration and transform offsets. Cache key includes recording identity. Expected timing failures stop mapped generation. Validate tuple shape/position/nonempty text/nonnegative finite times/audio bounds. Make optional translation availability explicit. Correct credential serialization so automated preflight knows token expiry.

**Order/dependencies:** B supplies job paths; reciter/domain verification supplies authoritative identity conventions. Do not treat frozen map tests or names in filenames as identity proof.

**Acceptance:**

- Two different synthetic reciters for the same verse keep distinct bytes and frame states.
- Chapter lookup failure cannot combine EveryAyah bytes with unrelated Quran.com timings.
- Missing/invalid expected timing stops output/history/upload; explicitly unmapped reciters use a declared static path.
- Supported numeric strings work; negative/out-of-bounds/misaligned/empty tuples fail.
- Audio transformations preserve impulse/word origin or expose an offset that is applied.
- Translation failure permits independent Arabic generation with truthful availability.
- Expired saved Google JSON reloads expired and refreshes once with mocked transport; automation cannot open interactive auth.
- Source identities and Hudhaify labels verified against recordings; Surah1/9 conventions documented.

**Effort:** 2–4days plus domain/source verification. No authenticated service calls needed for regression tests.

### D. Preserve complete recitation and visible text on one timeline

**Findings:** QRM-02, QRM-03, QRM-05, QRM-38, QRM-36 resource lifecycle.

**Scope:** common intro/audio/text timeline; explicit policy for a verse longer than Shorts target; timing-aware pagination or complete readable height fitting. Preserve reviewed Uthmani codepoints/fonts. Fade visuals or verified silence, rather than audible Quran boundaries. Close clips/readers/processes in exception-safe scopes.

**Order/dependencies:** C validates the recording/timing bundle; B owns temporary artifacts. Domain reviewer decides font/mark/format policy.

**Acceptance:**

- Synthetic cue/impulse remains aligned with intro on/off, padding and transformed audio.
- Overlong verse either renders fully in a declared format or stops visibly; frames/audio/container and metadata agree.
- Longest supported authentic Uthmani verses plus synthetic extremes display every word/mark/current highlight within safe margins.
- Source boundary waveform is preserved outside reviewed silence; short clips cannot receive overlapping destructive audio fades.
- Golden ligature/tashkeel/waqf/marker render checks on Windows/Linux, followed by qualified visual/listening review.
- Injected export/cancel failure leaves no live media reader/process or owned temporary leak.

**Effort:** 2–5days, depending on pagination choice; content review excluded. Keep the existing browser shaping approach and measure rendering bounds instead of replacing the renderer wholesale.

### E. Verify output coverage before claiming “Full” or uploading

**Findings:** QRM-06, QRM-07, QRM-08, QRM-30, QRM-38.

**Scope:** per-verse/per-source manifest; mandatory verse fetch/render errors stop complete-surah jobs. Duration-limited output derives actual ranges and explicitly declares incompleteness. Titles/descriptions/thumbnails/history derive from verified manifest. Web unknown attribution requires review instead of defaults. Deterministic canonical Quran/translation/reciter metadata is authoritative; AI fields remain bounded suggestions.

**Order/dependencies:** C/D produce verified media; B persists manifest and failed jobs; A reviews final package.

**Acceptance:**

- Missing verse, failed segment, early duration stop and corrupt concat output cannot become a successful full-surah upload.
- FFprobe verified streams/duration and verse manifest match title, chapters and history.
- Every reciter/Shorts fallback uses partial coverage text unless full inclusion is verified.
- Unknown web title/cleared fields cannot silently become Yasser/Al-Mulk.
- AI malformed types/tags/unsupported benefits/altered translations cannot pass automatic approval.

**Effort:** 1.5–3days plus content review. Reuse bounded omission/title/attribution fixtures from audit.

### F. Make workflows literal, serialized, truthful and recoverable

**Findings:** QRM-16, QRM-19, QRM-20, QRM-21, QRM-33, QRM-34, QRM-35.

**Scope:** typed choices and environment-to-argument arrays instead of raw input interpolation; literal synthetic secret serialization tests; least required permissions. Gate every mutation/live/paid call in dry-run. Shared cross-workflow publishing/state concurrency. Durable state/receipt/artifact persistence replacing binary DB merge assumptions. Exact outcome exit codes, failure artifacts before owned cleanup, bounded jobs and correct alerts. Derive occurrence from triggering schedule and skip expired/unmatched windows. Add safe test/media/import gates.

**Order/dependencies:** B defines authoritative state/recovery; A–E are functional gates. No workflow dispatch/push/schedule alteration is part of the audit; those are follow-up changes.

**Acceptance:**

- Shell metacharacters/quotes/newlines stay literal or rejected before use; synthetic credential files round-trip correctly.
- Full dry-run has zero credential refresh/auth/API/AI/notifications and no store/output/push/cleanup mutations.
- Two workflow occurrences cannot publish/reserve duplicate jobs or binary-merge divergent state.
- Failed upload/history/persistence exits nonzero and retains receipts/media/manifests accessible for recovery.
- Late weekday/midnight/DST/forced/repeated events follow explicit occurrence policy.
- Windows/local and clean Python3.11/Linux gates run isolated tests and tiny renderer/media checks.
- Failure/suppression/private/processed states are accurately named; alerts trigger on actual failure.

**Effort:** 2–4days plus chosen durable-state backend/recovery integration. A shared concurrency group is an interim guard, not a complete substitute for transactional state/receipts.

### G. Track actual platform lifecycle, identity and privacy

**Findings:** QRM-11, QRM-17, QRM-18, QRM-29; OAuth state and log risks.

**Scope:** expected account assertions, staged YouTube/TikTok transfer/processing/publication records, bounded final-status polling/webhooks, real post IDs, chunked streaming payloads and truthful private/unlisted status. Secure atomic token storage, explicit disconnect formats, TikTok OAuth state/callback timeout and redirect consistency; redact token-bearing URLs/responses.

**Order/dependencies:** B receipt/reconciliation model andA policy. Fix local expiry/state contracts before any authorized platform integration.

**Acceptance:**

- Mocked transfer followed by moderation/transcode failure ends failed, not published.
- Private/unlisted results are never announced as publicly live; browser route cannot claim success from a placeholder ID.
- Synthetic payload exceeding64MB is divided/streamed according to platform contract without reading full file into memory.
- Wrong account or missing creator/privacy capability stops before transfer.
- OAuth wrong state/redirect/timeout rejects; immediate legitimate flow succeeds in a simulated callback.
- Local disconnect removes all loadable formats; crash/concurrent writes retain valid prior token.
- Exception/log fixtures containing token-bearing URLs/responses are redacted.

**Effort:** 2–4days plus authorized platform confirmation. Remote revocation and private posting remain separately authorized external actions.

### H. Close web trust boundaries before using web output in publishing

**Findings:** QRM-08, QRM-22, QRM-23, QRM-24, QRM-28.

**Scope:** safe DOM values/text, strict YouTube identifiers/channel URLs, resolved path containment/server-owned output names, bounded finite request/download/process limits. Reserve before enqueue; per-job polling/results/temp storage; explicit loopback deployment policy or authentication if exposed.

**Order/dependencies:** B/E define jobs/manifests/attribution; web runtime/path work inI can happen independently. This gate applies when the web app runs or its output enters publishing; it is not evidence that inactive web defects currently compromise the CLI.

**Acceptance:**

- Inert title/attribute/XSS fixtures display literally and execute nothing.
- Traversal/drive/UNC/device/separator names rejected before process or sidecar writes.
- Empty/huge/nonfinite/oversized/stalled jobs fail with actionable status inside bounded resource limits.
- Two simultaneous requests are rejected or fully isolated, including multiworker deployment.
- Arbitrary/private-network URLs never reach yt-dlp; redirects constrained if supported.
- All preview/results belong to requesting job; output streams validated before completed.

**Effort:** 2–4days; no redesign necessary.

## 2. Next reliability improvements

### I. Make the web compiler portable and recoverable for reviewers

**Findings:** QRM-25, QRM-26, QRM-27, QRM-28, QRM-39.

**Scope:** repo/config-relative startup paths and bounded web dependencies; working font path/fallback; retain selection across ordering, one caught polling flow, stale-result prevention; explicit retry/cancel/download. Fit mobile controls and add linked/descriptive input/button labels, visible keyboard focus, progress announcements and Arabic direction.

**Dependencies:** H job IDs/trust boundary; can build portability tests before that work.

**Acceptance:** clean Windows/Linux isolated startup without scratch writes; actual fetch→select→order→compile→poll→preview/download with mocked services; failed download/API/process recovers; second job never shows old output; deselection survives all reorder/sort;320/390px has no clipped controls; keyboard actions and accessible names identify the selected clip/job.

**Effort:** 1.5–3days. Compare running screenshots with current UI, preserving its purpose.

### J. Use measured metrics and repeatable feedback

**Findings:** QRM-31, QRM-32, QRM-16.

**Scope:** nullable CTR/retention with source/time/exposure; validated public counts; idempotent feedback on new snapshots; video age/sample-size/format gates; outcome partial/failed semantics. Label local title/CPM scores as heuristics. Keep unused experiment/rotation settings inactive until implemented.

**Dependencies:** B schema migration; F dry-run isolation. Unattended feedback should remain disabled until its gates pass, as a proposed follow-up policy.

**Acceptance:** unavailable is null rather than0/.05/.50; identical ingest/feedback leaves decisions unchanged; negative/out-of-range metrics rejected; comparison uses adequate age/exposure; forced queue remains intentional and deduplicated; no “success” on total ingestion failure.

**Effort:** 1–2.5days. Statistical threshold calibration requires actual authorized data later; do not invent outcome proof.

### K. Make caches, backgrounds and resource cleanup auditable

**Findings:** QRM-14, QRM-36, QRM-38; source/provenance review.

**Scope:** atomic versioned JSON/cache writes or transactional stores, byte completion/checksum/output probes, bounded retry/deadline behavior, job-specific cleanup/finally scopes, cache budgets. Record source/creator/license/recording/translation provenance and review status. Decide whether background repetition history is active; mark detector unavailable as unchecked rather than verified people-free.

**Dependencies:** B ownership andC media identity; E manifest provenance.

**Acceptance:** interrupted/concurrent writes keep valid state; partial media not reused; network failure triggers real bounded retry; all clips/processes close under failure/cancellation; unchecked backgrounds require content review; repeated/cached selections match declared repetition policy; provenance accompanies distributable output.

**Effort:** 1.5–3days, legal/content verification excluded.

### L. Isolate all validation and document supported runtime/configuration

**Findings:** QRM-34, QRM-35; gaps in report section7.

**Scope:** fixtures configure paths/env before first import; move manual live scripts to an explicit integration area and require declared external intent. Replace unscoped deletion/fixed output writes. Validated configuration precedence; startup side effects explicit. Pin/bound web runtime and document optional TikTok/browser/font/platform needs.

**Dependencies:** share tests withA–K; final clean-install gate after source fixes.

**Acceptance:** broad discovery invokes zero production/live clients and preserves production hashes; actual baseline tests and focused defect regressions pass under Windows supported interpreter and CI3.11; fresh install/import/real tiny encoder+Chromium checks succeed; .env.example values reflect effective runtime; no test passes solely by printing an error or swallowing a return value.

**Effort:** 1–2.5days. Test platform contracts with mocks, then explicitly authorized live checks; do not turn root test scripts loose in the production checkout.

## 3. Later improvements

### M. Finish experiments only when the decision contract is defined

**Findings:** QRM-32.

**Scope:** attach real matched variant IDs/configs/exposure windows and define what winner settings control; otherwise label/delete placeholders. Define actual weekly/sleep content separately from current single-surah generation.

**Dependencies:** B/J stable identities/metrics, C–E integrity andG processing evidence.

**Acceptance:** an experiment uses real reviewed variants, adequate exposure and sample gates; winner demonstrably affects subsequent eligible decision; unsupported promises removed from help/docs.

**Effort:** 2–5days for a minimal complete experiment; larger format development needs a separate brief.

### N. Activate documentary components through a clean feature gate

**Findings:** QRM-40, QRM-36.

**Scope:** explicitly keep incomplete subsystem unavailable until correct imports/config/dependencies exist; then require audio/video/manifest/provenance/cost validation. Repair cache provenance and validators that interpret missing checks as success.

**Dependencies:** C/E/K; separate feature authorization. Missing unused components are not a reason to rewrite active Shorts publishing.

**Acceptance:** clean source-only import without stale bytecode; exact Quran payload and full audio verified; missing audio/detector/probe failures cannot pass quality; cached sources retain attribution; costs distinguish cache from paid calls; no global episode race.

**Effort:** 1–3days for import/config/quality gates; completing absent feature scope cannot be estimated from current sources.

### O. Measure rendering costs and reduce retained full-frame state

**Findings:** QRM-05, QRM-36.

**Scope:** profile representative short/long verses after integrity fixes; capture peak RAM, Chromium/FFmpeg process count, open handles, disk growth and failure cleanup. Consider reusable page/session/state loading or bounded compositing only if the measured bottleneck warrants it.

**Dependencies:** D readable complete rendering andK cleanup.

**Acceptance:** published bounded workload budget and reproducible local/CI measurements; no unbounded cache/temp growth or surviving processes after failure; optimization preserves golden text/audio sync and output quality.

**Effort:** 1–2days profiling; optimization estimate follows evidence. The audit's tiny fixtures are not a throughput benchmark.

### P. Align documentation with reachable behavior and review policy

**Findings:** QRM-07, QRM-18, QRM-21, QRM-27, QRM-32, QRM-33, QRM-35, QRM-39, QRM-40.

**Scope:** document CLI/web architecture, generated versus published journey, actual approval/privacy/account precedence, dry-run/test distinction, source/translation rights review, font/runtime paths, recovery and supported formats. Remove stale quota/59s-limit claims, clarify local heuristic scoring and incomplete experiments/documentary.

**Dependencies:** update alongside each fix, consolidate after gates pass.

**Acceptance:** help/.env.example/README/setup/schedules agree with code and tested defaults; recovery instructions work on disposable state; external quota/API guidance links primary sources and is not assumed to equal this project's allocation.

**Effort:** 0.5–1.5days.

## 4. Completion gates for a follow-up implementation

1. **Local safety/integrity:** all applicableA–H acceptance tests pass with isolated stores and no real publication; existing suite plus focused end-to-end defect regressions pass.
2. **Platform portability:** clean supported Windows and CI/Linux installs, actual Chromium render, tiny FFmpeg/FFprobe output, and native mocked web flow pass.
3. **Domain review:** qualified approval of recording identity, verse/text/timing, basmala/marks and full metadata/translation package.
4. **Authorized live integration:** only with explicit permission, verify intended identity/privacy, credential refresh, upload processing and receipt reconciliation. A private upload is still a publication-side mutation.
5. **Scheduling/recovery:** demonstrated idempotent repeated/late/concurrent occurrence and crash/backup restore; enable unattended jobs only after durable state and review policy are established.

The audit already delivered source evidence and bounded reproduction harnesses. They are starting regression fixtures, not a substitute for these completion gates. No automatic job or publishing setting was changed by this plan.
