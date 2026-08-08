"""
Tests for core.word_timings.

The failure this guards against: the old code queried an endpoint that stopped
honouring segments=true, got nothing back, and silently fell back to evenly
estimated timings. A broken sync looked identical to a working one.
"""
import pytest

from core.word_timings import WordTimingError, get_word_timings, parse_segments


def _api_response(segments, words):
    return {
        "verse": {
            "audio": {"url": "Alafasy/mp3/112001.mp3", "segments": segments},
            "words": [
                {"char_type_name": "word", "text_uthmani": w} for w in words
            ]
            + [{"char_type_name": "end", "text_uthmani": "۝"}],
        }
    }


class TestParseSegments:
    def test_extracts_start_and_end_from_four_element_tuples(self):
        starts, ends = parse_segments([[0, 1, 30, 390], [1, 2, 400, 790]])

        assert starts == [30, 400]
        assert ends == [390, 790]

    def test_coerces_string_values(self):
        """Sudais returns ['0','1','140','1000'] rather than ints"""
        starts, ends = parse_segments([["0", "1", "140", "1000"]])

        assert starts == [140]
        assert ends == [1000]

    def test_rejects_overlapping_segments(self):
        with pytest.raises(WordTimingError, match="overlap|monotonic"):
            parse_segments([[0, 1, 0, 900], [1, 2, 500, 1200]])

    def test_rejects_backwards_segment(self):
        with pytest.raises(WordTimingError, match="ends before it starts"):
            parse_segments([[0, 1, 900, 400]])


class TestGetWordTimings:
    def test_returns_none_for_unmapped_reciter(self, mocker):
        """Banna has no upstream recitation; that is expected, not an error"""
        fetch = mocker.patch("core.word_timings._fetch_verse")

        assert get_word_timings("banna", 112, 1) is None
        fetch.assert_not_called()

    def test_returns_aligned_timings(self, mocker):
        mocker.patch(
            "core.word_timings._fetch_verse",
            return_value=_api_response(
                [[0, 1, 30, 390], [1, 2, 400, 790], [2, 3, 800, 1640]],
                ["قُلْ", "هُوَ", "ٱللَّهُ"],
            ),
        )

        timing = get_word_timings("alafasy", 112, 1)

        assert timing.words == ["قُلْ", "هُوَ", "ٱللَّهُ"]
        assert timing.starts_ms == [30, 400, 800]
        assert timing.ends_ms == [390, 790, 1640]
        assert timing.audio_url == "Alafasy/mp3/112001.mp3"

    def test_raises_when_mapped_reciter_returns_no_segments(self, mocker):
        """This is the regression that hid for months - it must be loud"""
        mocker.patch(
            "core.word_timings._fetch_verse",
            return_value=_api_response([], ["قُلْ", "هُوَ"]),
        )

        with pytest.raises(WordTimingError, match="no segments"):
            get_word_timings("alafasy", 112, 1)

    def test_raises_when_counts_disagree(self, mocker):
        mocker.patch(
            "core.word_timings._fetch_verse",
            return_value=_api_response([[0, 1, 30, 390]], ["قُلْ", "هُوَ"]),
        )

        with pytest.raises(WordTimingError, match="1 segments.*2 words|mismatch"):
            get_word_timings("alafasy", 112, 1)

    def test_ignores_non_word_tokens(self, mocker):
        """The trailing ayah-number glyph is not a recited word"""
        mocker.patch(
            "core.word_timings._fetch_verse",
            return_value=_api_response([[0, 1, 30, 390]], ["قُلْ"]),
        )

        timing = get_word_timings("alafasy", 112, 1)

        assert len(timing.words) == 1

    def test_duration_helper_returns_seconds(self, mocker):
        mocker.patch(
            "core.word_timings._fetch_verse",
            return_value=_api_response(
                [[0, 1, 0, 500], [1, 2, 510, 2000]], ["قُلْ", "هُوَ"]
            ),
        )

        timing = get_word_timings("alafasy", 112, 1)

        assert timing.spans_seconds()[0] == pytest.approx((0.0, 0.5))
        assert timing.spans_seconds()[1] == pytest.approx((0.51, 2.0))
