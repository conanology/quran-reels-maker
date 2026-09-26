import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from core import growth_engine as growth


def test_dry_run_never_reads_or_writes_stores_or_auth(mocker):
    for target in ["database.models.get_db_session", "database.models.get_setting",
                   "database.models.set_setting", "youtube.auth.check_authentication_status"]:
        mocker.patch(target, side_effect=AssertionError("dry-run side effect"))
    mocker.patch("core.growth_engine.get_db_session", side_effect=AssertionError("store"))
    result = growth.execute_scheduled_slot("morning_short", dry_run=True)
    assert result["status"] == "dry_run"


@pytest.mark.parametrize("mode", ["arabic_short_core", "arabic_short_gulf", "unknown"])
def test_partial_titles_never_claim_full(mode):
    title = growth.generate_engine_title(mode, 1, "minshawi_mujawwad")
    assert "full" not in title.lower() and "كاملة" not in title


def test_outside_schedule_skips_without_generation(mocker):
    mocker.patch("youtube.auth.check_authentication_status", return_value={"status": "authenticated"})
    mocker.patch.object(growth, "get_mecca_time", return_value=datetime.datetime(2026, 9, 28, 12))
    render = mocker.patch.object(growth, "generate_reel", side_effect=AssertionError("unexpected render"))
    result = growth.execute_scheduled_slot()
    assert result["status"] == "skipped"
    render.assert_not_called()


def test_feedback_never_changes_selection_settings(mocker):
    session = MagicMock()
    session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [
        SimpleNamespace(video_id="v", surah=1, reciter_key="minshawi_mujawwad", video_type="short",
                        views=1000, engagement_rate=0.05, retention_rate=None, ctr=None, comments=3,
                        created_at=datetime.datetime.now() - datetime.timedelta(days=3))]
    mocker.patch("database.models.get_db_session", return_value=session)
    mocker.patch("database.models.get_setting", return_value=None)
    write = mocker.patch("database.models.set_setting")
    first = growth.run_feedback_loop_analysis()
    second = growth.run_feedback_loop_analysis()
    assert first == second
    write.assert_not_called()


def test_placeholder_experiment_cannot_fabricate_video_ids(mocker):
    store = mocker.patch("database.models.get_db_session")
    result = growth.trigger_ab_test_experiment("reciter")
    assert result["status"] == "unavailable"
    assert "video_id_a" not in result
    store.assert_not_called()


@pytest.mark.parametrize("field,value", [("views", -1), ("ctr", 1.5), ("retention_rate", float("nan"))])
def test_invalid_analytics_rejected_before_store(field, value, mocker):
    store = mocker.patch("database.models.get_db_session")
    values = dict(video_id="v", views=100, likes=2, comments=1, retention_rate=None, ctr=None,
                  surah=1, reciter_key="minshawi_mujawwad", video_type="short")
    values[field] = value
    with pytest.raises(ValueError):
        growth.ingest_video_analytics(**values)
    store.assert_not_called()


@pytest.fixture
def publishing_fixture(tmp_path, monkeypatch, mocker):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import database.models as models
    import database.jobs as jobs
    from core.utils import write_media_manifest
    import core.utils as utils
    import hashlib
    mocker.patch.object(utils, "verify_media_streams", return_value=dict(
        width=1080, height=1920, video_duration=3, audio_duration=3))
    database = tmp_path / "state.db"
    engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(models, "_engine", engine)
    monkeypatch.setattr(models, "_SessionLocal", sessionmaker(bind=engine, class_=models.RetryingSession))
    monkeypatch.setattr(models, "DATABASE_PATH", database)
    monkeypatch.setattr(jobs, "DATABASE_PATH", database)
    models.init_database()
    for name in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_APPROVER_ID", "YOUTUBE_EXPECTED_CHANNEL_ID"]:
        monkeypatch.setenv(name, "fixture")
    monkeypatch.delenv("ENABLE_TIKTOK_AUTOPUBLISH", raising=False)
    mocker.patch("youtube.auth.check_authentication_status", return_value={"status": "valid"})
    mocker.patch.object(growth, "get_mecca_time", return_value=datetime.datetime(2026, 9, 28, 5))
    mocker.patch.object(growth, "pick_reciter", return_value="minshawi_mujawwad")
    mocker.patch.object(growth, "pick_surah", return_value=1)
    video = tmp_path / "fixture.mp4"
    video.write_bytes(b"synthetic bytes")
    write_media_manifest(video, {"coverage": [{"surah": 1, "start_ayah": 1, "end_ayah": 3}],
                                "verses": [{"surah": 1, "ayah": ayah, "reciter_key": "minshawi_mujawwad",
                                            "recording_url": "https://example.invalid/audio",
                                            "audio_sha256": "0" * 64, "audio_duration": 1.0,
                                            "text": "Synthetic text",
                                            "text_source": {"provider": "synthetic", "verse_key": f"1:{ayah}",
                                                "text_sha256": hashlib.sha256(b"Synthetic text").hexdigest()},
                                            "timing_source": {"status": "not_available", "word_count": 2}}
                                           for ayah in range(1, 4)], "reciter_key": "minshawi_mujawwad",
                                "duration_seconds": 3, "loop_count": 1,
                                "streams": {"width": 1080, "height": 1920}})
    render = mocker.patch.object(growth, "generate_reel", return_value=(video, 1, 3))
    approve = mocker.patch("notifications.publishing_policy.require_automatic_approval", return_value={})
    def upload_with_receipt(*args, **kwargs):
        receipt={"status": "published", "privacy_status": "public", "video_id": "fixture0001", "url": "https://example.invalid/fixture"}
        jobs.record_upload_receipt(kwargs['job_id'],'youtube',receipt)
        return receipt
    upload = mocker.patch("youtube.uploader.upload_video", side_effect=upload_with_receipt)
    yield models, render, approve, upload
    engine.dispose()


def test_growth_success_commits_published_cursor_and_skips_repeat(publishing_fixture):
    models, render, approve, upload = publishing_fixture
    first = growth.execute_scheduled_slot("morning_short")
    second = growth.execute_scheduled_slot("morning_short")
    assert first["status"] == "success", first
    assert second["status"] == "skipped"
    assert render.call_count == approve.call_count == upload.call_count == 1
    with models.get_db_session() as session:
        progress = session.query(models.SurahShortsProgress).one()
        assert (progress.surah, progress.next_ayah) == (1, 4)
        assert session.query(models.ReelHistory).count() == 1


def test_different_slots_share_surah_and_reciter_rotation(publishing_fixture, mocker):
    """Exercise reservation, rendered coverage, receipts and finalization together."""
    import json
    import database.jobs as jobs
    from config.settings import SHORTS_RECITERS
    from core.utils import write_media_manifest
    models, render, approve, upload = publishing_fixture
    video = render.return_value[0]
    template = json.loads(video.with_suffix('.mp4.manifest.json').read_text())
    selected = []

    def render_selected(**kwargs):
        surah, start, end, reciter = (kwargs[key] for key in
            ('surah', 'start_ayah', 'end_ayah', 'reciter_key'))
        selected.append((surah, start, end, reciter))
        manifest = dict(template, reciter_key=reciter,
                        coverage=[dict(surah=surah, start_ayah=start, end_ayah=end)])
        verse = template['verses'][0]
        manifest['verses'] = [dict(verse, surah=surah, ayah=ayah, reciter_key=reciter,
            text_source=dict(verse['text_source'], verse_key=f'{surah}:{ayah}'))
            for ayah in range(start, end + 1)]
        write_media_manifest(video, manifest)
        return video, start, end

    def publish_selected(*args, **kwargs):
        receipt = dict(status='published', privacy_status='public',
                       video_id=f'fixture{len(selected):04d}', url='https://example.invalid/fixture')
        jobs.record_upload_receipt(kwargs['job_id'], 'youtube', receipt)
        return receipt

    render.side_effect = render_selected
    upload.side_effect = publish_selected
    for day, hour, slot in [(28, 5, 'morning_short'), (28, 21, 'evening_short'),
                            (29, 5, 'morning_short')]:
        mocker.patch.object(growth, 'get_mecca_time', return_value=datetime.datetime(2026, 9, day, hour))
        result = growth.execute_scheduled_slot(slot)
        assert result['status'] == 'success', result
    assert selected == [(surah, 1, 3, reciter) for surah, reciter in enumerate(SHORTS_RECITERS, 1)]
    assert render.call_count == approve.call_count == upload.call_count == 3
    with models.get_db_session() as session:
        assert sorted((row.surah, row.next_ayah) for row in session.query(models.SurahShortsProgress)) == [
            (1, 4), (2, 4), (3, 4)]
        assert session.query(models.ReelHistory).count() == 3
        assert session.query(models.VerseProgress).count() == 0
    assert jobs.get_next_shorts_selection()['reciter_key'] == SHORTS_RECITERS[0]
    assert jobs.get_next_shorts_selection()['surah'] == 4


def test_growth_rejection_does_not_upload_or_advance(publishing_fixture):
    from notifications.publishing_policy import PublishingPolicyError
    models, render, approve, upload = publishing_fixture
    approve.side_effect = PublishingPolicyError("rejected", "rejected")
    result = growth.execute_scheduled_slot("morning_short")
    assert result["status"] == "failed"
    upload.assert_not_called()
    with models.get_db_session() as session:
        assert session.query(models.SurahShortsProgress).count() == 0
        assert session.query(models.ReelHistory).count() == 0


def test_growth_cannot_change_reserved_start(publishing_fixture):
    models, render, approve, upload = publishing_fixture
    render.return_value = (render.return_value[0], 2, 3)
    assert growth.execute_scheduled_slot("morning_short")["status"] == "failed"
    approve.assert_not_called()
    upload.assert_not_called()


def test_post_publication_failure_preserves_confirmed_job(publishing_fixture, monkeypatch):
    from notifications.publishing_policy import PublishingPolicyError
    models, render, approve, upload = publishing_fixture
    monkeypatch.setenv("ENABLE_TIKTOK_AUTOPUBLISH", "true")
    approve.side_effect = [{}, PublishingPolicyError("TikTok review rejected", "rejected")]
    result = growth.execute_scheduled_slot("morning_short")
    assert result["status"] == "partial", result
    with models.get_db_session() as session:
        job = session.query(models.PublishingJob).one()
        assert job.finalized and job.status == "published"
        assert session.query(models.ReelHistory).count() == 1
        assert session.query(models.SurahShortsProgress).one().next_ayah == 4


def test_longform_wrong_coverage_stops_before_review_or_transfer(publishing_fixture, mocker):
    models, render, approve, upload = publishing_fixture
    video = render.return_value[0]
    mocker.patch.object(growth, "generate_longform", return_value={
        "output_path": str(video), "recommended_title": "Synthetic full Fatihah",
        "description": "Synthetic recording", "tags": [], "duration_seconds": 3})
    result = growth.execute_scheduled_slot("friday_long")
    assert result["status"] == "failed", result
    approve.assert_not_called()
    upload.assert_not_called()


def test_longform_uses_complete_coverage_and_recommended_title(publishing_fixture, mocker):
    from core.utils import write_media_manifest
    import json
    models, render, approve, upload = publishing_fixture
    video = render.return_value[0]
    manifest = json.loads(video.with_suffix(".mp4.manifest.json").read_text())
    template = manifest["verses"][0]
    manifest["coverage"] = [{"surah": 1, "start_ayah": 1, "end_ayah": 7}]
    manifest["verses"] = []
    for ayah in range(1, 8):
        verse = dict(template, ayah=ayah, text_source=dict(template["text_source"], verse_key=f"1:{ayah}"))
        manifest["verses"].append(verse)
    write_media_manifest(video, manifest)
    mocker.patch.object(growth, "generate_longform", return_value={
        "output_path": str(video), "recommended_title": "Synthetic complete Fatihah",
        "description": "Synthetic recording", "tags": [], "duration_seconds": 3})
    result = growth.execute_scheduled_slot("friday_long")
    assert result["status"] == "success", result
    assert upload.call_args.args[1]["title"] == "Synthetic complete Fatihah"
    with models.get_db_session() as session:
        history = session.query(models.LongformHistory).one()
        assert (history.surah_start, history.surah_end, history.ayah_start, history.ayah_end) == (1, 1, 1, 7)
        assert session.query(models.SurahShortsProgress).count() == 0
