"""
Tests for analytics ingestion.

Long-form compilations may carry no reciter_key (the column is nullable there),
but VideoAnalytics.reciter_key is NOT NULL. Passing the value straight through
raised IntegrityError, and because the handler wrapped the whole 50-video
chunk, one bad record silently discarded the statistics for every video after
it in that batch.
"""
from unittest.mock import MagicMock

import pytest

from core.growth_engine import ingest_video_analytics

BASE_ARGS = dict(
    video_id="abc123",
    views=1000,
    likes=50,
    comments=5,
    retention_rate=0.5,
    ctr=0.05,
    surah=2,
    video_type="long",
)


@pytest.fixture
def captured_record(mocker):
    """Capture the kwargs used to build a VideoAnalytics row."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    mocker.patch("database.models.get_db_session", return_value=session)

    created = {}

    def _factory(**kwargs):
        created.update(kwargs)
        return MagicMock()

    mocker.patch("database.models.VideoAnalytics", side_effect=_factory)
    return created


class TestReciterKeyNormalisation:
    def test_missing_reciter_key_does_not_write_null(self, captured_record):
        """A long-form row with no reciter must still be ingestible"""
        result = ingest_video_analytics(reciter_key=None, **BASE_ARGS)

        assert result["status"] == "success"
        assert captured_record["reciter_key"] is not None
        assert captured_record["reciter_key"] != ""

    def test_blank_reciter_key_does_not_write_null(self, captured_record):
        ingest_video_analytics(reciter_key="   ", **BASE_ARGS)

        assert captured_record["reciter_key"].strip() != ""

    def test_real_reciter_key_is_preserved(self, captured_record):
        ingest_video_analytics(reciter_key="alafasy", **BASE_ARGS)

        assert captured_record["reciter_key"] == "alafasy"
