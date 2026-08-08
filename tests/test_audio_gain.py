"""
Tests the ambient bed gain conversion.

The original expression subtracted `20 * sqrt(ratio)` from 20, which is not a
dB conversion. At the default 0.12 it left the bed roughly 1.85x too loud
underneath the recitation.
"""
import math

import pytest

from core.audio_processor import amplitude_ratio_to_db


class TestAmplitudeRatioToDb:
    @pytest.mark.parametrize(
        "ratio, expected_db",
        [
            (1.0, 0.0),        # unchanged
            (0.5, -6.02),      # halving amplitude is about -6 dB
            (0.12, -18.42),    # the project default
            (0.1, -20.0),
        ],
    )
    def test_known_conversions(self, ratio, expected_db):
        assert amplitude_ratio_to_db(ratio) == pytest.approx(expected_db, abs=0.01)

    def test_round_trips_back_to_the_ratio(self):
        for ratio in (0.05, 0.12, 0.33, 0.8):
            db = amplitude_ratio_to_db(ratio)

            assert 10 ** (db / 20) == pytest.approx(ratio, rel=1e-6)

    def test_zero_and_negative_are_silent_not_infinite(self):
        """log10(0) would raise, so it must be clamped rather than crash"""
        assert amplitude_ratio_to_db(0) <= -100
        assert amplitude_ratio_to_db(-1) <= -100

    def test_is_quieter_than_the_old_expression(self):
        """Guards the regression: the old maths was 5+ dB too loud at 0.12"""
        ratio = 0.12
        old_applied = -(20 - 20 * math.sqrt(ratio))

        assert amplitude_ratio_to_db(ratio) < old_applied - 5
