"""Transactional Shorts surah rotation; all database files are isolated fixtures."""
import datetime
import sqlite3

import pytest
from sqlalchemy import text


@pytest.fixture
def rotation(tmp_path, monkeypatch):
    from database import models, jobs
    from config import settings
    path = tmp_path / 'rotation.sqlite'
    monkeypatch.setattr(models, 'DATABASE_PATH', path)
    monkeypatch.setattr(jobs, 'DATABASE_PATH', path)
    monkeypatch.setattr(models, '_engine', None)
    monkeypatch.setattr(models, '_SessionLocal', None)
    monkeypatch.setattr(settings, 'SHORTS_RECITERS', ('minshawi_mujawwad', 'banna', 'yasser_dossari'))
    models.init_database()
    yield models, jobs, path
    models.get_engine().dispose()


def reserve_current(rotation, key, verses_count=3):
    _, jobs, _ = rotation
    selection = jobs.get_next_shorts_selection(verses_count=verses_count)
    return jobs.reserve_job(key, shorts_rotation=True, **selection), selection


def publish(rotation, job, end=None, status='published', privacy='public'):
    _, jobs, _ = rotation
    receipt = dict(video_id=('id' + job['id'].replace('-', ''))[:11], status=status, privacy_status=privacy)
    jobs.record_upload_receipt(job['id'], 'youtube', receipt)
    jobs.finalize_published_job(job['id'], dict(surah=job['surah'], start_ayah=job['start_ayah'],
        end_ayah=job['end_ayah'] if end is None else end, reciter_key=job['reciter_key']), receipt)


def seed_history(models, surah, start, end, reciter='banna', status='uploaded', youtube_id='REALvideo01'):
    session = models.get_db_session()
    try:
        session.add(models.ReelHistory(surah=surah, start_ayah=start, end_ayah=end,
            reciter_key=reciter, status=status, youtube_id=youtube_id, uploaded_at=datetime.datetime.utcnow()))
        session.commit()
    finally:
        session.close()


def test_all_114_surahs_rotate_and_preserve_individual_continuations(rotation):
    models, jobs, _ = rotation
    visited, reciters = [], []
    for number in range(1, 115):
        job, selection = reserve_current(rotation, f'rotation-{number}')
        visited.append(selection['surah'])
        reciters.append(selection['reciter_key'])
        publish(rotation, job)
    assert visited == list(range(1, 115))
    assert reciters == ['minshawi_mujawwad', 'banna', 'yasser_dossari'] * 38
    selection = jobs.get_next_shorts_selection()
    assert (selection['surah'], selection['start_ayah'], selection['cycle']) == (1, 4, 0)
    session = models.get_db_session()
    try:
        assert session.query(models.SurahShortsProgress).count() == 114
        assert session.query(models.VerseProgress).count() == 0
        assert session.query(models.SurahShortsProgress).filter_by(surah=108).one().cycle == 1
    finally:
        session.close()


def test_kawthar_completion_moves_to_different_surah_and_retains_cycle(rotation):
    models, jobs, _ = rotation
    models.set_setting('shorts_next_surah', '108')
    job, selection = reserve_current(rotation, 'kawthar')
    assert (selection['start_ayah'], selection['end_ayah']) == (1, 3)
    publish(rotation, job)
    assert jobs.get_next_shorts_selection()['surah'] == 109
    models.set_setting('shorts_next_surah', '108')
    assert jobs.get_next_shorts_selection()['cycle'] == 1
    assert jobs.get_next_shorts_selection()['start_ayah'] == 1


def test_existing_uploaded_history_seeds_surah_and_each_individual_ayah(rotation):
    models, jobs, _ = rotation
    seed_history(models, 2, 7, 9, 'minshawi_mujawwad')
    seed_history(models, 108, 1, 3, 'banna')
    selection = jobs.get_next_shorts_selection()
    assert (selection['surah'], selection['reciter_key']) == (109, 'yasser_dossari')
    models.set_setting('shorts_next_surah', '2')
    assert jobs.get_next_shorts_selection(verses_count=5)['start_ayah'] == 10
    assert jobs.get_next_shorts_selection(verses_count=5)['end_ayah'] == 14
    models.set_setting('shorts_next_surah', '108')
    assert jobs.get_next_shorts_selection()['cycle'] == 1
    seed_history(models, 108, 1, 3, 'yasser_dossari', status='generated')
    seed_history(models, 108, 1, 3, 'yasser_dossari', youtube_id='fake')
    assert jobs.get_next_shorts_selection()['reciter_key'] == 'yasser_dossari'


@pytest.mark.parametrize('status,privacy', [('processing','public'), ('failed','public'), ('published','private'), ('published','unlisted')])
def test_failed_incomplete_and_private_uploads_do_not_advance(rotation, status, privacy):
    models, jobs, _ = rotation
    job, selection = reserve_current(rotation, 'pending')
    with pytest.raises(ValueError):
        publish(rotation, job, status=status, privacy=privacy)
    assert jobs.get_next_shorts_selection() == selection
    assert not jobs.get_job(job['id'])['finalized']
    session = models.get_db_session()
    try:
        assert session.query(models.ReelHistory).count() == 0
        assert session.query(models.SurahShortsProgress).count() == 0
    finally:
        session.close()


def test_exact_rendered_end_advances_individual_state_and_leaves_legacy_cursor(rotation):
    models, jobs, _ = rotation
    session = models.get_db_session()
    session.add(models.VerseProgress(current_surah=103, current_ayah=2, total_reels_generated=9))
    session.commit()
    session.close()
    job, _ = reserve_current(rotation, 'actual-range')
    publish(rotation, job, end=2)
    session = models.get_db_session()
    try:
        progress = session.query(models.SurahShortsProgress).filter_by(surah=1).one()
        assert (progress.next_ayah, progress.cycle) == (3, 0)
        legacy = session.query(models.VerseProgress).one()
        assert (legacy.current_surah, legacy.current_ayah, legacy.total_reels_generated) == (103, 2, 9)
    finally:
        session.close()
    publish(rotation, job, end=2)
    assert jobs.get_next_shorts_selection()['surah'] == 2


def test_legacy_gate_and_changed_selection_fail_closed(rotation):
    models, jobs, _ = rotation
    models.set_setting('publication_cursor_verified', 'false')
    selection = jobs.get_next_shorts_selection()
    with pytest.raises(RuntimeError, match='Legacy cursor'):
        jobs.reserve_job('unverified', shorts_rotation=True, **selection)
    models.set_setting('publication_cursor_verified', 'true')
    job, _ = reserve_current(rotation, 'changed')
    models.set_setting('shorts_next_surah', '2')
    with pytest.raises(ValueError, match='rotation changed'):
        publish(rotation, job)
    assert jobs.get_next_shorts_selection()['surah'] == 2


def test_reservation_retry_is_stable_and_remote_uncertainty_blocks_other_slots(rotation):
    models, jobs, _ = rotation
    job, selection = reserve_current(rotation, 'retry')
    assert jobs.reserve_job('retry', shorts_rotation=True, **selection)['id'] == job['id']
    jobs.begin_upload_attempt(job['id'], 'youtube')
    models.set_setting('shorts_next_surah', '2')
    different = jobs.get_next_shorts_selection()
    with pytest.raises(RuntimeError, match='Unfinalized remote'):
        jobs.reserve_job('later-slot', shorts_rotation=True, **different)
    assert jobs.reserve_job('retry', shorts_rotation=True, **selection)['id'] == job['id']


def test_rotation_rejects_non_pool_reciter_and_conflicting_modes(rotation):
    _, jobs, _ = rotation
    selection = jobs.get_next_shorts_selection()
    with pytest.raises(ValueError, match='reciter pool'):
        jobs.reserve_job('bad-reader', shorts_rotation=True, **dict(selection, reciter_key='alafasy'))
    with pytest.raises(ValueError, match='sequential'):
        jobs.reserve_job('two-modes', sequential=True, shorts_rotation=True, **selection)
    with pytest.raises(ValueError, match='rotation changed'):
        jobs.reserve_job('wrong-reader', shorts_rotation=True, **dict(selection, reciter_key='banna'))


def test_fresh_selection_is_read_only_and_does_not_create_database(rotation, monkeypatch):
    _, jobs, path = rotation
    absent = path.parent / 'absent' / 'never-created.sqlite'
    monkeypatch.setattr(jobs, 'DATABASE_PATH', absent)
    selection = jobs.get_next_shorts_selection(verses_count=5)
    assert selection == dict(surah=1, start_ayah=1, end_ayah=5, reciter_key='minshawi_mujawwad', cycle=0)
    assert not absent.parent.exists()


def reserve_policy_pair(rotation, prior_rotation):
    _, jobs, _ = rotation
    selection = jobs.get_next_shorts_selection()
    legacy = dict(surah=108, start_ayah=1, end_ayah=3, reciter_key='alafasy', sequential=True)
    rotated = dict(selection, shorts_rotation=True)
    first = jobs.reserve_job('first-policy', **(rotated if prior_rotation else legacy))
    second_args = legacy if prior_rotation else rotated
    return first, second_args


@pytest.mark.parametrize('prior_rotation', [False, True])
@pytest.mark.parametrize('uncertainty', ['attempt', 'receipt'])
def test_policy_transition_blocks_uncertain_opposite_mode(rotation, prior_rotation, uncertainty):
    _, jobs, _ = rotation
    first, second_args = reserve_policy_pair(rotation, prior_rotation)
    if uncertainty == 'attempt':
        jobs.begin_upload_attempt(first['id'], 'youtube')
    else:
        jobs.record_upload_receipt(first['id'], 'youtube', dict(video_id='REALvideo01', status='published', privacy_status='public'))
    with pytest.raises(RuntimeError, match='Unfinalized remote'):
        jobs.reserve_job('second-policy', **second_args)


@pytest.mark.parametrize('prior_rotation', [False, True])
def test_preexisting_cross_policy_reservations_recheck_before_transfer(rotation, prior_rotation):
    _, jobs, _ = rotation
    first, second_args = reserve_policy_pair(rotation, prior_rotation)
    second = jobs.reserve_job('second-policy', **second_args)
    jobs.begin_upload_attempt(first['id'], 'youtube')
    with pytest.raises(RuntimeError, match='Unfinalized remote'):
        jobs.begin_upload_attempt(second['id'], 'youtube')
    assert not jobs._attempt_path(second['id'], 'youtube').exists()


@pytest.mark.parametrize('missing', [('shorts_rotation','shorts_cycle'), ('shorts_cycle',)])
def test_schema_migration_backs_up_and_preserves_existing_job(rotation, missing):
    models, jobs, path = rotation
    job = jobs.reserve_job('old-mode', surah=1, start_ayah=1, end_ayah=3, reciter_key='banna')
    with models.get_engine().begin() as connection:
        for column in missing:
            connection.execute(text(f'ALTER TABLE publishing_jobs DROP COLUMN {column}'))
    models.init_database()
    migrated = jobs.get_job(job['id'])
    assert migrated['shorts_rotation'] == 0
    assert migrated['shorts_cycle'] is None
    assert migrated['reciter_key'] == 'banna'
    backup = path.with_suffix('.pre-shorts-rotation.sqlite')
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute('SELECT id FROM publishing_jobs').fetchone()[0] == job['id']
        assert not set(missing) & {row[1] for row in connection.execute('PRAGMA table_info(publishing_jobs)')}
