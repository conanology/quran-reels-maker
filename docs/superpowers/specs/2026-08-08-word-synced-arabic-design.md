# Word-synced Arabic recitation display

Date: 2026-08-08
Status: approved

## Problem

The whole ayah appears on screen at once for the duration of its audio. With a
long verse that is a dense block of text with nothing tying it to what is being
recited, which reads as cluttered and gives the viewer no way to follow along.
The English translation compounded it: long verses were wrapped into two very
wide lines and then scaled down to roughly a 16px effective font, so it was
unreadable.

## Goal

Highlight each Arabic word as it is recited, using real per-word timings.
Remove the English translation from the rendered frame entirely.

Non-goal: word-level English. Arabic and English word order differ, so there is
no meaningful per-word correspondence, and no published English word timings
exist. Translation moves to the video description.

## What already exists

`core/quran_v4_api.py` fetches word timings and Uthmani word text, and
`core/ayah_fetcher.py` already returns `word_segments` and `word_texts` per
ayah. The renderer discards both and draws the whole verse.

Two upstream defects make that data unusable today.

### Defect 1 — the timings endpoint stopped honouring `segments=true`

`get_verse_audio_with_timings()` calls:

    /recitations/{id}/by_chapter/{surah}?segments=true

That returns `audio_files` with no segments. Verified 2026-08-08: every call
returns zero segments, and the code falls back to `build_heuristic_segments()`
with only a `logger.info`, so the failure is invisible.

Segments are still available from a different endpoint:

    /verses/by_key/{surah}:{ayah}?audio={reciter_id}&words=true&word_fields=text_uthmani
    -> verse.audio.segments = [[index, position, start_ms, end_ms], ...]

Verified aligned, monotonic and non-overlapping for every mapped reciter:

| verse | reciter | segments | words | aligned |
|---|---|---|---|---|
| 2:255 | Alafasy | 50 | 50 | yes |
| 55:13 | Sudais | 4 | 4 | yes |
| 2:79 | (id 6) | 24 | 24 | yes |
| 112:3 | Abdul Basit | 4 | 4 | yes |
| 18:60 | (id 10) | 13 | 13 | yes |

Two parsing hazards: the tuple has **four** elements, not the three the current
parser expects, and values arrive as `int` for some reciters and `str` for
others (Sudais returns `['0','1','140','1000']`). Coerce with `int()`.

### Defect 2 — three reciter IDs point at the wrong person

Checked against `/resources/recitations`:

| key | current id | who that actually is | correct id |
|---|---|---|---|
| `husary` | 5 | Hani ar-Rifai | **6** |
| `shuraym` | 6 | Mahmoud Khalil Al-Husary | **10** |
| `minshawi_mujawwad` | 10 | Sa'ud ash-Shuraym | **8** |

`alafasy` (7), `sudais` (3) and `abdul_basit_murattal` (2) are correct.

This is currently masked because the broken endpoint returns no audio URL, so
the pipeline falls back to everyayah with the right reciter. The working
endpoint **also supplies the audio URL**, so adopting it without this fix would
serve the wrong reciter's audio under the right reciter's name. Misattributing
Quranic recitation is not acceptable, so this is fixed first.

Two reciters can additionally gain timings: `abdul_basit_mujawwad` -> 1 and
`shaatree` -> 4. `banna`, `hudhaify` and `maher_muaiqly` do not exist upstream
and will legitimately have no timings.

## Approach

Render the Arabic text layer in Chromium via Playwright, which is already a
project dependency.

Each word is a `<span>`; the highlighted word gets a CSS class. Chrome performs
the RTL layout and shaping itself, so the highlight is positioned exactly by
construction rather than by measuring substring widths, which is unreliable in
Arabic because shaping is contextual.

Rejected alternatives:

- **PIL re-render per word.** Requires measuring where each word starts inside a
  shaped RTL line. Contextual shaping makes that approximate, so the highlight
  drifts off the word. Also keeps the existing silent Windows/Linux divergence.
- **ASS/libass karaoke tags.** `\kf` fills left-to-right, which is backwards for
  Arabic; only instant-snap `\k` is directionally safe. The `ass` filter cannot
  output alpha, so all compositing would have to move into FFmpeg.

Chromium also renders tashkeel correctly on Windows and Linux alike, which
removes the existing platform split where local renders silently degrade to
`arabic_reshaper` and produce detached marks.

## Design

### `core/word_timings.py` (new)

Owns fetching and validating per-word timings.

    get_word_timings(reciter_key, surah, ayah) -> WordTiming | None

Returns `None` only when the reciter has no upstream mapping (a known, legitimate
case for Banna, Hudhaify and Muaiqly). Raises `WordTimingError` when a mapped
reciter returns unusable data, so a regression is loud rather than silent.

Validates: segment count equals word count, timings are monotonic and
non-overlapping, and values coerce to int.

### `core/karaoke_renderer.py` (new)

    render_word_states(words, highlight_style, layout) -> list[Path]

Launches one Chromium page, builds the verse as spans once, then for each word
index toggles the highlight class and screenshots with `omit_background=True`.
Returns one RGBA PNG per word state. Reusing the page avoids a browser launch
per word; a render measured ~123 ms.

### `core/video_generator.py` (changed)

For each ayah: if timings exist, build one `ImageClip` per word state with
`start`/`duration` from its segment, concatenated over the ayah's span. If they
do not, fall back to the current whole-ayah clip.

The translation clip is no longer composited.

### Data flow

    ayah_fetcher
      -> word_timings.get_word_timings()      (segments + word text)
      -> karaoke_renderer.render_word_states() (one PNG per word)
      -> video_generator                       (sequence by segment timing)

### Error handling

| condition | behaviour |
|---|---|
| reciter has no upstream mapping | fall back to whole-ayah render, log info |
| mapped reciter returns no segments | raise `WordTimingError` |
| segment count != word count | raise `WordTimingError` |
| non-monotonic or overlapping timings | raise `WordTimingError` |
| Chromium unavailable | raise; do not silently degrade |

The distinction matters: "this reciter has no timings" is expected, while
"timings were expected and are missing" is the regression that hid for months.

### Testing

- `get_word_timings` returns `None` for an unmapped reciter.
- `get_word_timings` raises on count mismatch, on overlap, and on empty segments.
- String-valued segments coerce to int (the Sudais case).
- Every entry in `RECITER_MAPPING_V4` resolves to a reciter whose canonical name
  matches its key, so a wrong ID cannot regress silently.
- `render_word_states` returns one image per word, each with real transparency.
- A verse with timings produces clips whose durations sum to the ayah duration.
- A reciter without timings still produces a whole-ayah clip.

## Out of scope

Long-form compiler changes, thumbnails, and the `arabic_reshaper` removal from
the remaining PIL paths. Those are tracked separately.
