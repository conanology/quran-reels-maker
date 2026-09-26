"""One fail-closed review boundary for every automatic publishing route."""
import hashlib
import html
import json
import os
from pathlib import Path
import secrets
from notifications import telegram_bot


class PublishingPolicyError(RuntimeError):
    def __init__(self, message, decision='failed'):
        super().__init__(message)
        self.decision = decision


def validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise PublishingPolicyError('Metadata must be an object')
    for field, limit in [('title', 100), ('description', 5000)]:
        if not isinstance(metadata.get(field), str) or not metadata[field].strip() or len(metadata[field]) > limit:
            raise PublishingPolicyError(f'Invalid final {field}')
    tags = metadata.get('tags', [])
    if not isinstance(tags,list) or any(not isinstance(t,str) or not t.strip() for t in tags):
        raise PublishingPolicyError('Metadata tags must be a list of nonempty strings')
    if sum(len(t) for t in tags) > 450:
        raise PublishingPolicyError('Metadata tags exceed conservative platform bound')


def thumbnail_digest(thumbnail_path):
    if thumbnail_path is None:
        return None
    return hashlib.sha256(Path(thumbnail_path).read_bytes()).hexdigest()


def package_digest(video_path, metadata, *, platform, privacy_status, expected_account, manifest=None,
                   thumbnail_path=None):
    from core.utils import load_media_manifest
    validate_metadata(metadata)
    verified = load_media_manifest(Path(video_path))
    if manifest is not None and manifest != verified:
        raise PublishingPolicyError('Supplied manifest differs from verified media')
    if not verified.get('verified') or not verified.get('coverage_complete'):
        raise PublishingPolicyError('Automatic publication requires complete verified coverage')
    package = dict(metadata=metadata, manifest=verified, platform=platform,
                   privacy_status=privacy_status, expected_account=expected_account,
                   thumbnail_sha256=thumbnail_digest(thumbnail_path))
    digest=hashlib.sha256(json.dumps(package,ensure_ascii=False,sort_keys=True,
                                   separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
    return digest, verified


def require_automatic_approval(video_path, metadata, *, job_id, platform='youtube',
                               privacy_status='public', expected_account=None, test=False, manifest=None,
                               thumbnail_path=None):
    """Return a bound approval record; all missing/unavailable/error states stop."""
    if test:
        raise PublishingPolicyError('Test mode suppresses all external publication', 'test')
    expected_account = expected_account or os.getenv(
        'YOUTUBE_EXPECTED_CHANNEL_ID' if platform=='youtube' else 'TIKTOK_EXPECTED_OPEN_ID','')
    if not expected_account:
        raise PublishingPolicyError('Expected publishing account must be configured')
    if not telegram_bot.is_configured() or not os.getenv('TELEGRAM_APPROVER_ID'):
        raise PublishingPolicyError('Automatic publishing requires configured review chat and approver')
    digest,verified=package_digest(video_path,metadata,platform=platform,privacy_status=privacy_status,
                                   expected_account=expected_account,manifest=manifest,thumbnail_path=thumbnail_path)
    nonce=secrets.token_hex(8)
    # Capture cursor BEFORE delivering the request, preserving immediate replies.
    updates=telegram_bot.get_updates()
    offset=updates[-1]['update_id']+1 if updates else None
    package_text=json.dumps(dict(job_id=job_id,platform=platform,privacy=privacy_status,
        expected_account=expected_account,metadata=metadata,coverage=verified.get('coverage'),
        package_hash=digest),ensure_ascii=False,indent=2)
    for start in range(0,len(package_text),3000):
        response=telegram_bot.send_message('<pre>'+html.escape(package_text[start:start+3000])+'</pre>')
        if not response or not response.get('ok'):
            raise PublishingPolicyError('Final package review delivery failed')
    caption=(f'Review job {job_id}\nReply to this video with:\n'
             f'approve {nonce} {digest}\nOr reject/regenerate with the same nonce and hash.')
    if thumbnail_path is not None:
        response=telegram_bot.send_photo(Path(thumbnail_path),f'Thumbnail for job {job_id}; package {digest}')
        if not response or not response.get('ok'):
            raise PublishingPolicyError('Thumbnail review delivery failed')
    response=telegram_bot.send_video(Path(video_path),caption)
    if not response or not response.get('ok'):
        raise PublishingPolicyError('Video review delivery failed')
    message_id=response['result']['message_id']
    decision=telegram_bot.wait_for_approval(request_message_id=message_id,nonce=nonce,
        package_hash=digest,job_id=job_id,initial_offset=offset)
    if decision!='approved':
        raise PublishingPolicyError('Final package not approved: '+decision,decision)
    current,_=package_digest(video_path,metadata,platform=platform,privacy_status=privacy_status,
                             expected_account=expected_account,thumbnail_path=thumbnail_path)
    if not secrets.compare_digest(current,digest):
        raise PublishingPolicyError('Package changed after review')
    record=dict(job_id=job_id,package_hash=digest,nonce=nonce,request_message_id=message_id,
                approver_id=os.getenv('TELEGRAM_APPROVER_ID'),chat_id=telegram_bot.TELEGRAM_CHAT_ID,
                platform=platform,privacy_status=privacy_status,expected_account=expected_account,
                thumbnail_path=str(Path(thumbnail_path).resolve()) if thumbnail_path else None,
                thumbnail_sha256=thumbnail_digest(thumbnail_path))
    from database.jobs import mark_job
    if platform=='youtube':
        mark_job(job_id,'approved',package_hash=digest,approval=json.dumps(record))
    else:
        from core.runtime_safety import atomic_write_json
        from config.settings import DATABASE_PATH
        import uuid
        safe_id=str(uuid.UUID(job_id))
        atomic_write_json(DATABASE_PATH.parent/'approvals'/f'{safe_id}-{platform}.json',record,private=True)
    return record
