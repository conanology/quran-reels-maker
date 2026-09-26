# Audit remediation status

Implementation date: 2026-09-26. The owner authorized repairs and delegated product decisions. The [original audit](audit-report.md) describes the earlier source; this ledger describes the repaired source. Thumbnail selection/rendering redesign remains the next task.

## Decisions delivered

Automatic publication requires a validated complete media manifest and explicit approval of the final media, metadata, intended account, privacy and thumbnail. Test/dry-run routes cannot publish. Generation does not consume the published Quran journey. Transactional reservations, process locks, atomic files and durable transfer evidence protect state; uncertain transfers require reconciliation.

Unsupported features are explicitly unavailable: cookie/browser TikTok posting, synthetic A/B experiments, automatic promotion from unverified feedback, the incomplete sleep/weekly formats and documentary generation. AI metadata/backgrounds are opt-in suggestions with final review. These decisions remove misleading success paths; they do not claim those unfinished features have been built.

## Every audit finding

| Finding | Implemented disposition | Main evidence |
| --- | --- | --- |
| QRM-01 | Timing selects the exact recording; audio caches include reciter and recording identity; recitation is preserved. | `test_media_remediation.py`, `test_word_timings.py` |
| QRM-02 | Intro silence and attached audio share the actual video timeline. | Actual tiny mux/intro regression |
| QRM-03 | An overlong first verse stops with an actionable error; no audio/video duration clipping. | Media duration regression |
| QRM-04 | Expected timing failures fail generation; genuinely unsupported timing is explicit static rendering. | Timing source/error regressions |
| QRM-05 | Measured Arabic pagination and active-word bounds prevent clipped text. | Real Chromium long-verse/page checks |
| QRM-06 | Longform rejects missing/failed verses and incomplete duration/coverage; stream checks and manifest are required. | Longform omission/coverage/stream regressions |
| QRM-07 | Partial Shorts cannot claim full-surah coverage. | Growth title regressions |
| QRM-08 | Unknown imported attribution remains unknown and requires explicit confirmation. | Native web models and browser review flow |
| QRM-09 | Every automatic route uses fail-closed approval, including growth and longform. | Publishing policy + main/growth integrations |
| QRM-10 | Approval binds reviewer/chat/reply, nonce, package hash, account, privacy and exact thumbnail bytes. | Telegram/digest/mutation regressions |
| QRM-11 | Test mode suppresses all platform transfers. | Main test/rejected-review integrations |
| QRM-12 | Generation leaves the cursor unchanged; confirmed public sequential publication commits it once; regeneration retains its reserved range. | Disposable SQLite publication integration |
| QRM-13 | Quran bounds/wrap validated; thematic jobs cannot corrupt sequential progress; old generation-based cursor requires explicit reconciliation. | Scheduler + legacy migration regressions |
| QRM-14 | Shared automatic publication lock, durable job reservation, independent media folders and atomic writer ownership. | Real subprocess lock and reservation tests |
| QRM-15 | Failed flush retry rolls back and replays captured writes with bounded waits. | Actual SQLite lock/flush recovery regression |
| QRM-16 | Dry runs do not read/write stores, authenticate, render or ingest analytics; preview workflows do not save publication state. | Dry-run regressions and workflow assertions |
| QRM-17 | OAuth JSON preserves expiry. | Credentials roundtrip test |
| QRM-18 | Atomic private token writes, complete local disconnect and no pickle deserialization; OAuth state/deadline validated. | Auth/disconnect/state regressions |
| QRM-19 | Typed workflow inputs become literal argument lists; credential JSON never becomes shell code. | Metacharacter/literal credential tests |
| QRM-20 | Serialized workflows restore checksum-verified run artifacts; binary SQLite Git pushes removed; missing/stale/failed checkpoints stop publication. | Checkpoint/restore/workflow tests |
| QRM-21 | Failed/partial outcomes propagate; failed jobs and receipts remain recoverable; only completed history excludes a longform group. | CLI exit, queue and durable receipt tests |
| QRM-22 | External metadata uses safe DOM text; URL/CSP/host/origin/local-peer boundaries. | Benign browser XSS marker + native HTTP tests |
| QRM-23 | Strict IDs/URLs/basenames, resolved containment and opaque server-owned job outputs. | Traversal/path/API tests |
| QRM-24 | Admission precedes enqueue; ownership spans each render; job-specific atomic status, files and cancellation. | Competing stores + browser/native jobs |
| QRM-25 | Sorting/reordering preserves explicit deselection. | Browser selection/order regression |
| QRM-26 | Job-bound bounded polling, caught failures, clear cancellation/retry and stale-output rejection. | Browser failure/retry/cancel checks |
| QRM-27 | Repository-relative/configurable paths, bundled font validation and documented bounded dependencies. | Native server + real Arabic FFmpeg render |
| QRM-28 | Request/clip/job/download/process size and time limits; finite settings; bounded cleanup owned by the job. | Native request/resource/cancel regressions |
| QRM-29 | Transfer, processing and publication remain distinct; real remote IDs/privacy required; streamed TikTok chunks are bounded. | Processing/privacy/65 MB streaming tests |
| QRM-30 | Default canonical metadata; optional AI suggestions have a bounded schema; final package is reviewed after metadata generation. | AI gates/schema + publishing digest tests |
| QRM-31 | Unknown metrics are null with provenance; repeated feedback is advisory and cannot apply repeated penalties. | Analytics validation/read-only feedback tests |
| QRM-32 | Disconnected experiments/promotions and unfinished formats explicitly unavailable. | Unavailable-feature contract tests |
| QRM-33 | Timezone-aware intended slot windows, explicit schedules and late-run skip; no silent slot substitution. | Slot/workflow source + freshness tests |
| QRM-34 | Legacy root/web manual scripts are inert on import; broad discovery uses isolated source/stores and blocked external sockets. | Full broad safe discovery |
| QRM-35 | Validated environment settings, bounded dependencies, no import-time store/log/probe creation; encoder probe encodes a real frame. | Config/import checks and isolated syntax suite |
| QRM-36 | Atomic bounded probed downloads, reciter/source checksums, provenance/review markers, lazy word frames and closed media resources; no automatic eviction of shared assets. | Asset/cache/media lifecycle regressions |
| QRM-37 | Word positions/timings/identity/durations verified; optional translation failures do not break valid recitation. | Strict timing/translation tests |
| QRM-38 | Quran marks preserved; recitation trimming/fades removed. | Mark/audio-boundary regressions |
| QRM-39 | Mobile controls fit 320/390 px; visible labels, keyboard controls and status/error announcements. | Desktop/mobile screenshots + browser checks |
| QRM-40 | Documentary imports/config/quality/cost/source defects repaired; generation explicitly unavailable until its full contract is implemented. | Documentary gate/import regressions |

## Verification record

Final broad isolated run: **259 passed**, 88 Python files parsed, zero syntax failures, production database unchanged; 18.94 seconds including runner startup. Six formerly unsafe root/compiler scripts were included in collection. The native browser flow separately passed 11 checks with zero page errors at desktop and 320/390 px mobile widths. Whitespace diff checks passed. Dependency/legacy datetime deprecation warnings remain; they were not test failures.

```powershell
.\venv\Scripts\python.exe scripts/checks.py tests test_ai_pipeline.py test_growth_engine.py test_longform_thumbnail.py test_tiktok.py quran_compiler/test_compilation.py quran_compiler/test_filters.py -q
```

The final commands and counts are recorded in `outputs/remediation/check-results.json` and `outputs/remediation/pytest-latest.txt`. The safe runner is `scripts/checks.py`. It copies source without production databases, tokens, caches or dotenv, blocks external sockets, runs disposable SQLite/media tests and verifies the original production DB hash.

Additional evidence: `outputs/remediation/web/implementation-evidence.md`, native browser screenshots under `outputs/remediation/web/`, `outputs/remediation/state-publishing-handoff.md`, and `outputs/audit/media/after-fixes/`. Native browser checks exercised fetch/select/order/compile/poll/preview/download/failure/retry/cancel with synthetic content and zero page errors. Actual Chromium, FFmpeg/FFprobe, SQLAlchemy/SQLite, OAuth serialization and cross-process locks were exercised locally.

## Operational acceptance still required

No live posts, approval messages, OAuth authorization, paid model calls or workflow dispatches were performed. The existing production DB was preserved without migration. A qualified reviewer must verify authentic recording/reciter identity, verse/text/basmala alignment, Quran marks/pronunciation and source/asset rights before automatic publication.

The owner must configure the intended accounts and approver, explicitly reconcile legacy published coverage, validate live platform authorization/processing in an approved account, and deliberately enable automation. Ambiguous transfers must be reconciled against their remote IDs before recovery. State artifact expiry or a failed artifact write requires recovery rather than fresh publication. These are explicit operational gates, not locally verified claims.

## Follow-up: Shorts surah and reciter rotation

Owner decision: a different surah for every automatic Short, with each surah's ayah position saved independently. All 114 surahs now rotate in Quran order. The fixed reader sequence is Minshawi Mujawwad → Mahmoud Ali Al-Banna → Yasser Al-Dossari. Local generation/test failures do not consume a turn; confirmed public publication updates history and rotation atomically. Main auto/batch and growth morning/evening slots share selection. Existing uncertain sequential/rotation transfers block a new reservation or upload across policy transitions. Migration backs up the database and retains the legacy sequential cursor. `status` shows the next rotating Short.

Yasser uses EveryAyah's `Yasser_Ad-Dussary_128kbps` verse directory. No Quran.com word timing ID was invented; unsupported readers use static Arabic text. [Arabic explanation and operating examples](shorts-policy.md).

Local diagnosis found the earlier selector stayed on its current surah until completion; the preserved production history is dominated by Al-Baqarah. That local history does not establish why Al-Asr/Al-Kawthar repeated on the owner's live channel. This follow-up verifies the new requested selection policy locally, without claiming remote deployment or inspecting/replacing old posts.

Latest full isolated verification: **284 passed**, **91 Python files parsed**, zero syntax failures, **25.48 seconds**, production database unchanged (SHA256 `cf9c5f8988265438527778d066f838fa0d297e40dd72afa302b3089b3c13ca27`). Includes a complete 114-surah traversal, resumption of Al-Fatihah at ayah4, completed Al-Kawthar wrapping only on its later turn, public/private/failure boundaries, cross-policy uncertainty, migration backups, three successive growth slots using all three readers, and three rejected regenerations retaining their reserved verses. The broad command above remains the verification command. Existing dependency/datetime deprecation warnings remain.

No live publishing, deployment, push, account messages or production migration was performed. Thumbnail refactoring remains deferred.
