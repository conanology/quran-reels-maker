"""Real disposable SQLite regressions; never use repository progress/history."""
import json
import hashlib
import sqlite3
import threading
import time
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def state(tmp_path, monkeypatch):
    from database import models, jobs
    path=tmp_path/'state.sqlite'
    engine=create_engine('sqlite:///'+path.as_posix(),connect_args={'timeout':0.01,'check_same_thread':False})
    monkeypatch.setattr(models,'DATABASE_PATH',path)
    monkeypatch.setattr(jobs,'DATABASE_PATH',path)
    monkeypatch.setattr(models,'_engine',engine)
    monkeypatch.setattr(models,'_SessionLocal',None)
    models.init_database()
    yield models,jobs,path
    engine.dispose()


@pytest.mark.parametrize('surah,last,target',[(1,7,(2,1)),(114,6,(1,1))])
def test_fresh_progress_rollover(state,surah,last,target):
    from core.verse_scheduler import advance_progress
    result=advance_progress(surah,last)
    assert (result['surah'],result['ayah'])==target


def test_thematic_override_preserves_journey(state):
    models,_,_=state
    session=models.get_db_session()
    session.add(models.VerseProgress(current_surah=1,current_ayah=1,total_reels_generated=0))
    session.commit();session.close()
    from core.verse_scheduler import advance_progress
    result=advance_progress(18,50)
    assert (result['surah'],result['ayah'],result['total_reels'])==(1,1,0)


def test_singleton_enforced_at_database(state):
    models,_,_=state
    session=models.get_db_session()
    session.add_all([models.VerseProgress(),models.VerseProgress()])
    with pytest.raises(IntegrityError):session.commit()
    session.rollback();session.close()


def test_two_threads_get_one_durable_reservation(state):
    models,jobs,_=state
    barrier=threading.Barrier(2)
    ids=[];errors=[]
    def reserve():
        try:
            barrier.wait()
            ids.append(jobs.reserve_job('slot:synthetic',surah=1,start_ayah=1,end_ayah=3,
                                        reciter_key='alafasy',sequential=True)['id'])
        except Exception as error:errors.append(error)
    threads=[threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=3)
    assert not errors and len(ids)==2 and ids[0]==ids[1]
    session=models.get_db_session()
    assert session.query(models.PublishingJob).count()==1
    session.close()


def test_receipt_survives_failed_database_commit(state,monkeypatch):
    _,jobs,_=state
    job=jobs.reserve_job('receipt:synthetic')
    class FailingEngine:
        def begin(self):raise RuntimeError('synthetic database unavailable')
    monkeypatch.setattr(jobs,'get_engine',lambda:FailingEngine())
    receipt=dict(video_id='synthetic',status='transferred',url='https://example.invalid')
    with pytest.raises(RuntimeError):jobs.record_upload_receipt(job['id'],'youtube',receipt)
    assert jobs.read_upload_receipts(job['id'])['youtube']==receipt


def test_finalize_is_atomic_and_idempotent(state):
    models,jobs,_=state
    job=jobs.reserve_job('journey:1:1',surah=1,start_ayah=1,end_ayah=7,reciter_key='alafasy',sequential=True)
    receipt=dict(video_id='synthetic',status='published',privacy_status='public')
    fields=dict(surah=1,start_ayah=1,end_ayah=7,reciter_key='alafasy',video_path='synthetic.mp4')
    jobs.record_upload_receipt(job['id'],'youtube',receipt)
    jobs.finalize_published_job(job['id'],fields,receipt)
    jobs.finalize_published_job(job['id'],fields,receipt)
    session=models.get_db_session();p=session.query(models.VerseProgress).one()
    assert (p.current_surah,p.current_ayah,p.total_reels_generated)==(2,1,1)
    assert session.query(models.ReelHistory).count()==1
    session.close()


def test_transfer_does_not_advance_cursor(state):
    models,jobs,_=state
    job=jobs.reserve_job('pending',surah=1,start_ayah=1,end_ayah=3,sequential=True)
    with pytest.raises(ValueError):jobs.finalize_published_job(job['id'],{},dict(status='transferred'))
    session=models.get_db_session()
    assert session.query(models.VerseProgress).count()==0
    assert session.query(models.ReelHistory).count()==0
    session.close()


def test_locked_flush_replays_after_rollback(state):
    models,_,path=state
    locker=sqlite3.connect(path,check_same_thread=False);locker.execute('BEGIN EXCLUSIVE')
    def unlock():
        time.sleep(0.06);locker.rollback()
    thread=threading.Thread(target=unlock);thread.start()
    session=models.get_db_session();session.add(models.VerseProgress(current_surah=1,current_ayah=1))
    try:
        session.commit()
        assert session.query(models.VerseProgress).count()==1
    finally:
        thread.join();session.close();locker.close()


def test_existing_multi_cursor_refuses_silent_recovery(state):
    models,_,_=state
    with models.get_engine().begin() as conn:
        conn.exec_driver_sql('DROP TRIGGER verse_progress_singleton')
        conn.exec_driver_sql('INSERT INTO verse_progress(current_surah,current_ayah,total_reels_generated) VALUES(1,1,0),(2,1,0)')
    with pytest.raises(RuntimeError,match='Multiple journey'):models.init_database()
    with models.get_engine().connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM verse_progress').scalar()==2


def test_longform_receipt_commits_history_once(state):
    models,jobs,_=state
    job=jobs.reserve_job('longform:synthetic',surah=1,start_ayah=1,end_ayah=7,reciter_key='alafasy')
    receipt=dict(video_id='synthetic-longform',status='processed',privacy_status='unlisted')
    jobs.record_upload_receipt(job['id'],'youtube',receipt)
    assert jobs.get_job(job['id'])['status']=='remote_processed'
    fields=dict(kind='longform',title='Synthetic complete Fatihah',surah_start=1,surah_end=1,
                ayah_start=1,ayah_end=7,num_clips=7,source_clip_ids='[]',duration_seconds=7,
                video_path='synthetic.mp4',reciter_key='alafasy')
    jobs.finalize_published_job(job['id'],fields,receipt)
    jobs.finalize_published_job(job['id'],fields,receipt)
    session=models.get_db_session()
    assert session.query(models.LongformHistory).count()==1
    assert session.query(models.VerseProgress).count()==0
    session.close()


def test_schema_migration_backups_legacy_rates(state):
    models,_,path=state
    with models.get_engine().begin() as conn:
        conn.exec_driver_sql('DROP TABLE video_analytics')
        conn.exec_driver_sql('CREATE TABLE video_analytics(id INTEGER PRIMARY KEY, video_id TEXT, retention_rate FLOAT, ctr FLOAT)')
        conn.exec_driver_sql("INSERT INTO video_analytics VALUES(1,'synthetic',0.5,0.05)")
    models.init_database()
    with models.get_engine().connect() as conn:
        row=conn.exec_driver_sql('SELECT retention_rate,ctr,metrics_source,private_metrics_verified FROM video_analytics').one()
        assert tuple(row)==(None,None,'legacy_unverified',0)
    with sqlite3.connect(path.with_suffix('.pre-safety-migration.sqlite')) as backup:
        assert backup.execute('SELECT retention_rate,ctr FROM video_analytics').fetchone()==(0.5,0.05)


def test_new_occurrence_blocked_by_unfinalized_receipt_even_after_db_failure(state,monkeypatch):
    _,jobs,_=state
    job=jobs.reserve_job('growth:day1',surah=1,start_ayah=1,end_ayah=3,reciter_key='alafasy',sequential=True)
    actual_engine=jobs.get_engine
    class FailingEngine:
        def begin(self):raise RuntimeError('synthetic database unavailable')
    monkeypatch.setattr(jobs,'get_engine',lambda:FailingEngine())
    with pytest.raises(RuntimeError):
        jobs.record_upload_receipt(job['id'],'youtube',dict(video_id='remote',status='published',privacy_status='public'))
    monkeypatch.setattr(jobs,'get_engine',actual_engine)
    with pytest.raises(RuntimeError,match='requires recovery'):
        jobs.reserve_job('growth:day2',surah=1,start_ayah=1,end_ayah=3,reciter_key='alafasy',sequential=True)


def test_uncertain_transfer_blocks_same_and_new_occurrence(state):
    _,jobs,_=state
    job=jobs.reserve_job('growth:day1',surah=1,start_ayah=1,end_ayah=3,reciter_key='alafasy',sequential=True)
    jobs.begin_upload_attempt(job['id'],'youtube')
    jobs.mark_job(job['id'],'failed')
    with pytest.raises(RuntimeError,match='acknowledgement'):
        jobs.assert_transfer_retry_safe(job['id'],'youtube')
    with pytest.raises(RuntimeError,match='requires recovery'):
        jobs.reserve_job('growth:day2',surah=1,start_ayah=1,end_ayah=3,reciter_key='alafasy',sequential=True)


def test_longform_new_occurrence_blocked_pending_receipt(state):
    _,jobs,_=state
    job=jobs.reserve_job('longform:day1',surah=1,surah_end=2,start_ayah=1,end_ayah=286,reciter_key='alafasy')
    jobs.record_upload_receipt(job['id'],'youtube',dict(video_id='remote',status='processing',privacy_status='unlisted'))
    with pytest.raises(RuntimeError,match='requires recovery'):
        jobs.reserve_job('longform:day2',surah=1,surah_end=2,start_ayah=1,end_ayah=286,reciter_key='alafasy')


def test_main_dry_generation_never_opens_fresh_store(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import main
    from database import models
    path=tmp_path/'fresh.sqlite'
    monkeypatch.setattr(models,'get_db_session',lambda:pytest.fail('dry-run opened DB'))
    args=SimpleNamespace(dry_run=True,surah=None)
    assert main.cmd_generate(args)['status']=='dry_run'
    assert not path.exists()


def test_legacy_generated_cursor_requires_explicit_owner_reconciliation(state):
    models,jobs,path=state
    with models.get_engine().begin() as connection:
        connection.exec_driver_sql("DELETE FROM app_settings WHERE key='publication_cursor_verified'")
        connection.exec_driver_sql('INSERT INTO verse_progress(current_surah,current_ayah,total_reels_generated) VALUES(2,42,12)')
    models.init_database()
    with pytest.raises(RuntimeError,match='not verified as published'):
        jobs.reserve_job('journey:legacy',surah=2,start_ayah=42,end_ayah=44,reciter_key='alafasy',sequential=True)
    session=models.get_db_session();progress=session.query(models.VerseProgress).one()
    assert (progress.current_surah,progress.current_ayah,progress.total_reels_generated)==(2,42,12)
    session.close()
    assert path.with_suffix('.pre-safety-migration.sqlite').exists()
    from core.verse_scheduler import set_progress
    set_progress(2,42)
    assert jobs.reserve_job('journey:legacy',surah=2,start_ayah=42,end_ayah=44,reciter_key='alafasy',sequential=True)['status']=='reserved'


@pytest.mark.parametrize('review_available',[True,False,'crosspost_error'])
@pytest.mark.parametrize('actual_end',[2,3])
def test_main_auto_publication_commits_only_after_completed_receipt(state,tmp_path,monkeypatch,review_available,actual_end):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import main
    from core import video_generator,quran_api,utils
    from core.utils import write_media_manifest
    from notifications import publishing_policy
    from youtube import uploader
    models,jobs,_=state
    monkeypatch.setenv('FRIDAY_MODE_ENABLED','false')
    monkeypatch.setenv('ENABLE_TIKTOK_AUTOPUBLISH','true' if review_available=='crosspost_error' or not review_available else 'false')
    monkeypatch.setattr(main,'OUTPUTS_DIR',tmp_path/'custom-output')
    monkeypatch.setattr(quran_api,'get_surah_name',lambda *a:'Synthetic')
    monkeypatch.setattr(utils,'verify_media_streams',lambda *a:dict(width=1080,height=1920,video_duration=3,audio_duration=3))
    def generate(**kw):
        video=Path(kw['output_path']);video.parent.mkdir(parents=True,exist_ok=True);video.write_bytes(b'synthetic')
        write_media_manifest(video,dict(reciter_key='alafasy',coverage=[dict(surah=1,start_ayah=1,end_ayah=actual_end)],
            verses=[dict(surah=1,ayah=a,reciter_key='alafasy',text='rendered Arabic',
                text_source=dict(provider='synthetic',verse_key=f'1:{a}',text_sha256=hashlib.sha256(b'rendered Arabic').hexdigest()),
                timing_source=dict(status='not_available',word_count=2),
                audio_sha256='0'*64,audio_duration=1,recording_url='https://example.invalid') for a in range(1,actual_end+1)],
            duration_seconds=3,loop_count=1,streams=dict(width=1080,height=1920)))
        return video,1,actual_end
    monkeypatch.setattr(video_generator,'generate_reel',generate)
    metadata=dict(title='Synthetic Quran',description='rendered Arabic',tags=[])
    def build_metadata(**kw):
        assert kw['full_text']==' '.join(['rendered Arabic']*actual_end)
        assert kw['end_ayah']==actual_end
        return metadata
    monkeypatch.setattr(uploader,'generate_metadata',build_metadata)
    def review(video,meta,**kw):
        if kw.get('platform')=='tiktok':
            raise publishing_policy.PublishingPolicyError('Crosspost review unavailable')
        session=models.get_db_session()
        assert session.query(models.ReelHistory).count()==0
        progress=session.query(models.VerseProgress).first()
        assert progress is None or progress.current_ayah==1
        session.close()
        if not review_available:
            raise publishing_policy.PublishingPolicyError('Review unavailable')
        approval=dict(job_id=kw['job_id'],package_hash='synthetic')
        jobs.mark_job(kw['job_id'],'approved',approval=json.dumps(approval))
        return approval
    monkeypatch.setattr(publishing_policy,'require_automatic_approval',review)
    def upload(video,meta,**kw):
        assert kw['automatic'] and video.is_relative_to(tmp_path/'custom-output')
        receipt=dict(video_id='synthetic',url='https://example.invalid',status='published',privacy_status='public')
        jobs.record_upload_receipt(kw['job_id'],'youtube',receipt)
        return receipt
    transfer=MagicMock(side_effect=upload);monkeypatch.setattr(uploader,'upload_video',transfer)
    args=SimpleNamespace(surah=None,start=None,end=None,verses=3,reciter='alafasy',test=False,dry_run=False)
    if not review_available:
        from tiktok import uploader as tiktok_uploader
        tiktok=MagicMock(side_effect=AssertionError('unapproved crosspost'))
        monkeypatch.setattr(tiktok_uploader,'upload_to_tiktok',tiktok)
        assert main._run_auto_reel(args)['status']=='failed'
        session=models.get_db_session()
        assert session.query(models.ReelHistory).count()==0
        progress=session.query(models.VerseProgress).first()
        assert progress is None or progress.current_ayah==1
        session.close();transfer.assert_not_called();tiktok.assert_not_called()
        return
    result=main._run_auto_reel(args)
    assert result['status']==('partial' if review_available=='crosspost_error' else 'published')
    session=models.get_db_session();progress=session.query(models.VerseProgress).one()
    assert (progress.current_surah,progress.current_ayah,progress.total_reels_generated)==(1,actual_end+1,1)
    assert session.query(models.ReelHistory).count()==1
    job=session.query(models.PublishingJob).one()
    assert job.finalized and job.status=='published'
    session.close();transfer.assert_called_once()


@pytest.fixture
def verified_fixture_video(tmp_path,monkeypatch):
    from core import utils
    monkeypatch.setattr(utils,'verify_media_streams',lambda *a:dict(width=1080,height=1920,video_duration=3,audio_duration=3))
    video=tmp_path/'verified.mp4';video.write_bytes(b'synthetic-media')
    utils.write_media_manifest(video,dict(reciter_key='alafasy',coverage=[dict(surah=1,start_ayah=1,end_ayah=3)],
        verses=[dict(surah=1,ayah=a,reciter_key='alafasy',text='Synthetic text',audio_sha256='0'*64,
            text_source=dict(provider='synthetic',verse_key=f'1:{a}',text_sha256=hashlib.sha256(b'Synthetic text').hexdigest()),
            timing_source=dict(status='not_available',word_count=2),audio_duration=1,recording_url='https://example.invalid') for a in range(1,4)],
        duration_seconds=3,loop_count=1,streams=dict(width=1080,height=1920)))
    return video


def test_main_longform_wrong_manifest_stops_before_review_and_transfer(state,verified_fixture_video,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import main
    from config import settings
    from longform import scheduler,compiler
    from notifications import publishing_policy
    from youtube import uploader
    models,_,database=state
    monkeypatch.setattr(settings,'DATABASE_PATH',database)
    monkeypatch.setattr(scheduler,'get_next_compilation',lambda:dict(surah_start=1,surah_end=1,ayah_start=1,ayah_end=7))
    monkeypatch.setattr(compiler,'generate_longform',lambda **kw:dict(output_path=str(verified_fixture_video),
        recommended_title='Synthetic full range',description='Synthetic',tags=[],thumbnail_path=None))
    reviewer=MagicMock(side_effect=AssertionError('Wrong coverage reached review'))
    transfer=MagicMock(side_effect=AssertionError('Wrong coverage reached remote transfer'))
    monkeypatch.setattr(publishing_policy,'require_automatic_approval',reviewer)
    monkeypatch.setattr(uploader,'upload_video',transfer)
    result=main.cmd_auto_longform(SimpleNamespace(test=False,reciter='alafasy'))
    assert result['status']=='failed'
    reviewer.assert_not_called();transfer.assert_not_called()
    with models.get_db_session() as session:
        assert session.query(models.LongformHistory).count()==0


def test_main_short_claimed_tuple_must_match_manifest_before_review(state,verified_fixture_video,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import main
    from notifications import publishing_policy
    from youtube import uploader
    monkeypatch.setattr(main,'cmd_generate',lambda args:dict(video_path=verified_fixture_video,
        surah=1,start_ayah=1,end_ayah=4,reciter='alafasy',full_text='Synthetic'))
    reviewer=MagicMock(side_effect=AssertionError('Wrong coverage reached review'))
    transfer=MagicMock(side_effect=AssertionError('Wrong coverage reached remote transfer'))
    monkeypatch.setattr(publishing_policy,'require_automatic_approval',reviewer)
    monkeypatch.setattr(uploader,'upload_video',transfer)
    result=main._run_auto_reel(SimpleNamespace(surah=1,start=1,end=3,verses=3,reciter='alafasy',test=False,dry_run=False))
    assert result['status']=='failed'
    reviewer.assert_not_called();transfer.assert_not_called()
