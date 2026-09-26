"""Transactional reservations and durable receipts for automatic publishing.

Remote transfers cannot participate in SQLite transactions. Write their receipts
to a durable sidecar before the DB update; resume reconciles instead of reposting.
"""
import datetime
import json
from pathlib import Path
import uuid
from sqlalchemy import text
from database.models import get_engine, init_database, PublishingJob, ReelHistory, get_db_session
from config.settings import DATABASE_PATH, VERSE_COUNTS, RECITERS
from core.runtime_safety import exclusive_lock, atomic_write_json


def writer_lock(timeout=30.0):
    return exclusive_lock(Path(DATABASE_PATH).with_suffix('.writer.lock'), timeout=timeout)


def _job_dict(row):
    return dict(row._mapping) if row is not None else None


def get_job(job_id):
    with get_engine().connect() as connection:
        row = connection.execute(text('SELECT * FROM publishing_jobs WHERE id=:id'), {'id': job_id}).first()
        return _job_dict(row)


def reserve_job(idempotency_key, *, surah=None, start_ayah=None, end_ayah=None,
                reciter_key=None, sequential=False, surah_end=None):
    """Return one stable job for a slot/content occurrence; never reserve twice."""
    if not idempotency_key or len(idempotency_key) > 200:
        raise ValueError('A bounded idempotency key is required')
    if surah is not None:
        terminal_surah=surah_end or surah
        if surah not in VERSE_COUNTS or terminal_surah not in VERSE_COUNTS or terminal_surah<surah:
            raise ValueError('Invalid reserved surah coverage')
        if start_ayah is None or end_ayah is None or not 1<=start_ayah<=VERSE_COUNTS[surah] or not 1<=end_ayah<=VERSE_COUNTS[terminal_surah]:
            raise ValueError('Invalid reserved ayah coverage')
        if terminal_surah==surah and end_ayah<start_ayah:
            raise ValueError('Invalid reserved ayah order')
    if reciter_key is not None and reciter_key not in RECITERS:
        raise ValueError('Invalid reserved reciter')
    with writer_lock():
        init_database()
        with get_engine().connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                if sequential:
                    verified=connection.execute(text("SELECT value FROM app_settings WHERE key='publication_cursor_verified'")).scalar()
                    if verified!='true':
                        raise RuntimeError('Legacy cursor is not verified as published; reconcile using set-progress before automatic journey publication')
                existing = connection.execute(text('SELECT * FROM publishing_jobs WHERE idempotency_key=:key'),
                                              {'key': idempotency_key}).first()
                if existing:
                    result = _job_dict(existing)
                else:
                    pending=connection.execute(text('SELECT * FROM publishing_jobs WHERE finalized=0')).all()
                    for row in pending:
                        prior=_job_dict(row)
                        same_content=(prior['surah'],prior['start_ayah'],prior['end_ayah'],prior['reciter_key'],prior.get('surah_end')) == (surah,start_ayah,end_ayah,reciter_key,surah_end)
                        if (sequential and prior['sequential']) or (surah is not None and same_content):
                            receipts=read_upload_receipts(prior['id'])
                            attempts=any(_attempt_path(prior['id'],platform).exists() for platform in ('youtube','tiktok'))
                            if receipts or attempts or prior['status'].startswith('remote_') or prior['status']=='transfer_started':
                                raise RuntimeError('Unfinalized remote publication requires recovery before reserving another occurrence')
                    job_id = str(uuid.uuid4())
                    connection.execute(text('''INSERT INTO publishing_jobs
                        (id,idempotency_key,surah,surah_end,start_ayah,end_ayah,reciter_key,sequential,status,finalized,receipts,created_at)
                        VALUES(:id,:key,:surah,:surah_end,:start,:end,:reciter,:sequential,'reserved',0,'{}',:now)'''),
                        dict(id=job_id,key=idempotency_key,surah=surah,start=start_ayah,end=end_ayah,
                             surah_end=surah_end,reciter=reciter_key,sequential=int(sequential),now=datetime.datetime.utcnow()))
                    result = _job_dict(connection.execute(text('SELECT * FROM publishing_jobs WHERE id=:id'),
                                                         {'id': job_id}).first())
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise


def mark_job(job_id, status, **fields):
    permitted = {'video_path', 'package_hash', 'approval', 'error_message', 'end_ayah', 'start_ayah','metadata_json','manifest'}
    if set(fields) - permitted:
        raise ValueError('Unsupported job field')
    values = dict(fields, status=status, updated_at=datetime.datetime.utcnow(), id=job_id)
    if isinstance(values.get('manifest'),dict):
        values['manifest']=json.dumps(values['manifest'])
    with get_engine().begin() as connection:
        assignments = ','.join(f'{k}=:{k}' for k in values if k != 'id')
        result = connection.execute(text(f'UPDATE publishing_jobs SET {assignments} WHERE id=:id'), values)
        if result.rowcount != 1:
            raise ValueError('Publishing job not found')


def _receipt_path(job_id):
    # Only UUID job identifiers may address the receipt directory.
    safe_id = str(uuid.UUID(job_id))
    return Path(DATABASE_PATH).parent / 'upload_receipts' / (safe_id + '.json')


def _attempt_path(job_id,platform):
    if platform not in ('youtube','tiktok'):
        raise ValueError('Unknown publishing platform')
    return Path(DATABASE_PATH).parent/'upload_attempts'/f'{str(uuid.UUID(job_id))}-{platform}.json'


def assert_transfer_retry_safe(job_id,platform):
    if _attempt_path(job_id,platform).exists() and platform not in read_upload_receipts(job_id):
        raise RuntimeError('Prior transfer has no acknowledgement; explicit remote reconciliation required')


def begin_upload_attempt(job_id,platform):
    """Persist uncertainty before remote mutation, so lost acknowledgements cannot repost."""
    with writer_lock():
        assert_transfer_retry_safe(job_id,platform)
        atomic_write_json(_attempt_path(job_id,platform),dict(job_id=job_id,platform=platform,
            status='transfer_started',started_at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
        mark_job(job_id,'transfer_started')


def read_upload_receipts(job_id):
    path = _receipt_path(job_id)
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('job_id') != job_id or not isinstance(data.get('receipts'), dict):
            raise ValueError('Invalid durable receipt')
        return data['receipts']
    job = get_job(job_id)
    return json.loads(job['receipts']) if job else {}


def record_upload_receipt(job_id, platform, receipt):
    if platform not in ('youtube', 'tiktok') or not receipt.get('video_id', receipt.get('publish_id')):
        raise ValueError('Remote receipt requires a platform and real transfer identifier')
    with writer_lock():
        # Never require the DB to be available before durably recording a new
        # remote acknowledgement. Every receipt starts in this sidecar.
        receipts = read_upload_receipts(job_id) if _receipt_path(job_id).exists() else {}
        receipts[platform] = receipt
        atomic_write_json(_receipt_path(job_id), {'job_id':job_id, 'receipts':receipts})
        with get_engine().begin() as connection:
            status='remote_'+receipt.get('status','transferred')
            connection.execute(text('UPDATE publishing_jobs SET receipts=:receipts,status=CASE WHEN finalized=1 THEN status ELSE :status END WHERE id=:id'),
                               dict(receipts=json.dumps(receipts),status=status,id=job_id))
    return receipts


def finalize_published_job(job_id, history_fields, receipt):
    """Commit confirmed publication and matching sequential cursor in one transaction."""
    if receipt.get('status') not in ('published', 'processed'):
        raise ValueError('Transfer/processing receipt is not completed publication')
    with writer_lock():
        with get_engine().connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            session = get_db_session()
            session.bind = connection
            try:
                job = session.query(PublishingJob).filter_by(id=job_id).one()
                if job.finalized:
                    connection.rollback()
                    return
                fields = dict(history_fields)
                kind=fields.pop('kind','short')
                durable=read_upload_receipts(job_id).get('youtube')
                if not durable or any(durable.get(key)!=receipt.get(key) for key in ('video_id','status','privacy_status')):
                    raise ValueError('Finalization requires the matching durable completed receipt')
                if job.manifest:
                    from core.utils import load_media_manifest
                    verified=load_media_manifest(job.video_path)
                    if verified!=json.loads(job.manifest):
                        raise ValueError('Published media differs from reserved verified manifest')
                    coverage=verified['coverage']
                    if kind=='longform':
                        supplied=(fields.get('surah_start'),fields.get('ayah_start'),fields.get('surah_end'),fields.get('ayah_end'))
                        expected=(coverage[0]['surah'],coverage[0]['start_ayah'],coverage[-1]['surah'],coverage[-1]['end_ayah'])
                    else:
                        supplied=(fields.get('surah'),fields.get('start_ayah'),fields.get('end_ayah'))
                        expected=(coverage[0]['surah'],coverage[0]['start_ayah'],coverage[0]['end_ayah'])
                        if len(coverage)!=1:
                            raise ValueError('Short history cannot omit manifest coverage')
                    if supplied!=expected or fields.get('reciter_key')!=verified['reciter_key']:
                        raise ValueError('History differs from final verified media coverage')
                if kind=='longform' and isinstance(fields.get('source_clip_ids'),list):
                    fields['source_clip_ids']=json.dumps(fields['source_clip_ids'])
                if kind=='longform':
                    if fields.get('reciter_key')!=job.reciter_key or fields.get('surah_start')!=job.surah or fields.get('ayah_start')!=job.start_ayah or fields.get('ayah_end')!=job.end_ayah or fields.get('surah_end')!=(job.surah_end or job.surah):
                        raise ValueError('Longform history differs from reserved coverage')
                    source_ids=json.loads(fields.get('source_clip_ids') or '[]')
                    if not isinstance(source_ids,list) or any(type(value) is not int for value in source_ids):
                        raise ValueError('Longform sources must be real history IDs')
                    if source_ids:
                        sources=session.query(ReelHistory).filter(ReelHistory.id.in_(source_ids)).all()
                        if len(sources)!=len(set(source_ids)) or any(item.reciter_key!=job.reciter_key for item in sources):
                            raise ValueError('Longform history references missing or different-reciter sources')
                if kind!='longform':
                    if (fields.get('surah'),fields.get('start_ayah')) != (job.surah,job.start_ayah):
                        raise ValueError('Publication coverage differs from reserved Quran range')
                    if fields.get('reciter_key') != job.reciter_key:
                        raise ValueError('Publication reciter differs from reservation')
                    from core.verse_scheduler import next_position
                    next_position(fields['surah'],fields['end_ayah'])
                    if fields['end_ayah'] < fields['start_ayah']:
                        raise ValueError('Publication range is empty')
                if job.sequential and receipt.get('privacy_status')!='public':
                    raise ValueError('Sequential public journey cannot advance from a non-public transfer')
                fields.update(youtube_id=receipt['video_id'],youtube_url=receipt.get('url'),
                              status='uploaded',uploaded_at=datetime.datetime.utcnow())
                if kind=='longform':
                    from database.models import LongformHistory
                    session.add(LongformHistory(**fields))
                else:
                    session.add(ReelHistory(**fields))
                if job.sequential:
                    verified=connection.execute(text("SELECT value FROM app_settings WHERE key='publication_cursor_verified'")).scalar()
                    if verified!='true':
                        raise ValueError('Published journey cursor requires explicit legacy recovery')
                    from database.models import VerseProgress
                    from core.verse_scheduler import next_position
                    progress = session.query(VerseProgress).first()
                    if progress is None:
                        progress = VerseProgress(current_surah=1,current_ayah=1,total_reels_generated=0)
                        session.add(progress)
                    if (progress.current_surah,progress.current_ayah) != (job.surah,job.start_ayah):
                        raise ValueError('Journey changed while job was pending; reconcile before publication commit')
                    progress.current_surah,progress.current_ayah = next_position(fields['surah'],fields['end_ayah'])
                    progress.total_reels_generated += 1
                job.status = 'published'
                job.finalized = True
                session.flush()
                connection.commit()
            except BaseException:
                session.rollback()
                connection.rollback()
                raise
            finally:
                session.close()
