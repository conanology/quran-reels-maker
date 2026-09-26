"""Publishing clients and review transports are mocked; no network/real tokens."""
import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest


@pytest.fixture
def manifest_video(tmp_path,monkeypatch):
    from core import utils
    from core.utils import write_media_manifest
    monkeypatch.setattr(utils,'verify_media_streams',lambda *a:dict(width=1080,height=1920,video_duration=3,audio_duration=3))
    video=tmp_path/'synthetic.mp4';video.write_bytes(b'synthetic media bytes')
    manifest=write_media_manifest(video,dict(reciter_key='alafasy',coverage=[dict(surah=1,start_ayah=1,end_ayah=3)],
        verses=[dict(surah=1,ayah=a,reciter_key='alafasy',text='Synthetic text',
            text_source=dict(provider='synthetic',verse_key=f'1:{a}',text_sha256=hashlib.sha256(b'Synthetic text').hexdigest()),
            timing_source=dict(status='not_available',word_count=2),
            audio_sha256='0'*64,audio_duration=1,recording_url='https://example.invalid') for a in range(1,4)],
        duration_seconds=3,loop_count=1,streams=dict(width=1080,height=1920)))
    return video,manifest


META=dict(title='Synthetic Quran range 1:1-3',description='Synthetic verified content for local test',tags=['Quran'])


def test_missing_review_configuration_stops(manifest_video,monkeypatch):
    from notifications.publishing_policy import require_automatic_approval,PublishingPolicyError
    from notifications import telegram_bot
    monkeypatch.setattr(telegram_bot,'is_configured',lambda:False)
    with pytest.raises(PublishingPolicyError):
        require_automatic_approval(manifest_video[0],META,job_id='synthetic',expected_account='synthetic')


def test_test_mode_stops_before_media_or_transport(monkeypatch):
    from notifications.publishing_policy import require_automatic_approval,PublishingPolicyError
    with pytest.raises(PublishingPolicyError) as caught:
        require_automatic_approval(Path('nonexistent'),META,job_id='synthetic',test=True)
    assert caught.value.decision=='test'


def test_review_delivery_error_fails_closed(manifest_video,monkeypatch):
    from notifications.publishing_policy import require_automatic_approval,PublishingPolicyError
    from notifications import telegram_bot
    monkeypatch.setenv('TELEGRAM_APPROVER_ID','42')
    monkeypatch.setattr(telegram_bot,'is_configured',lambda:True)
    monkeypatch.setattr(telegram_bot,'get_updates',lambda:[])
    monkeypatch.setattr(telegram_bot,'send_message',lambda *a:None)
    with pytest.raises(PublishingPolicyError,match='delivery failed'):
        require_automatic_approval(manifest_video[0],META,job_id='synthetic',expected_account='synthetic')


@pytest.mark.parametrize('bad_sender,bad_message,bad_nonce,bad_hash',[
    (True,False,False,False),(False,True,False,False),(False,False,True,False),(False,False,False,True)])
def test_approval_binds_sender_request_nonce_and_hash(monkeypatch,bad_sender,bad_message,bad_nonce,bad_hash):
    from notifications import telegram_bot as bot
    monkeypatch.setenv('TELEGRAM_APPROVER_ID','42');monkeypatch.setattr(bot,'TELEGRAM_CHAT_ID','7')
    monkeypatch.setattr(bot,'is_configured',lambda:True);monkeypatch.setattr(bot,'send_message',lambda *a:None)
    message=dict(text=f"approve {'bad' if bad_nonce else 'nonce'} {'bad' if bad_hash else 'hash'}",
        chat=dict(id=7),**{'from':dict(id=99 if bad_sender else 42)},
        reply_to_message=dict(message_id=99 if bad_message else 10))
    good=dict(message,text='approve nonce hash',**{'from':dict(id=42)},reply_to_message=dict(message_id=10))
    polls=iter([[dict(update_id=1,message=message)],[dict(update_id=2,message=good)]])
    monkeypatch.setattr(bot,'get_updates',lambda **kw:next(polls))
    monkeypatch.setattr(bot.time,'sleep',lambda *a:None)
    assert bot.wait_for_approval(timeout_seconds=1,request_message_id=10,nonce='nonce',package_hash='hash',job_id='job')=='approved'


def test_video_change_invalidates_package(manifest_video):
    from notifications.publishing_policy import package_digest
    path,_=manifest_video
    package_digest(path,META,platform='youtube',privacy_status='public',expected_account='synthetic')
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):
        package_digest(path,META,platform='youtube',privacy_status='public',expected_account='synthetic')


def test_oauth_preserves_expiry_and_local_disconnect(tmp_path,monkeypatch):
    from youtube import auth
    from google.oauth2.credentials import Credentials
    monkeypatch.setattr(auth,'YOUTUBE_TOKEN_PATH',tmp_path/'token.pickle')
    credential=Credentials('synthetic',refresh_token='synthetic',token_uri='https://example.invalid',
        client_id='synthetic',client_secret='synthetic',expiry=datetime.datetime(2000,1,1))
    auth.save_credentials(credential)
    loaded=auth.get_credentials(refresh=False)
    assert loaded.expired and loaded.expiry==credential.expiry
    assert auth.revoke_credentials() and not (tmp_path/'token.json').exists()


def test_automatic_auth_never_opens_browser(monkeypatch):
    from youtube import auth
    monkeypatch.setattr(auth,'get_credentials',lambda:None)
    interactive=MagicMock(side_effect=AssertionError('browser'))
    monkeypatch.setattr(auth,'authenticate_interactive',interactive)
    with pytest.raises(auth.YouTubeAuthError):auth.get_authenticated_service()
    interactive.assert_not_called()


def test_wrong_youtube_identity_stops_before_transfer(manifest_video,monkeypatch):
    from youtube import uploader
    service=MagicMock();service.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'wrong'}]}
    monkeypatch.setattr(uploader,'get_authenticated_service',lambda:service)
    with pytest.raises(uploader.YouTubeUploadError,match='identity'):
        uploader.upload_video(manifest_video[0],META,expected_channel_id='expected')
    service.videos.assert_not_called()


def test_processed_private_not_announced_public(monkeypatch):
    from youtube import uploader
    service=MagicMock();service.videos.return_value.list.return_value.execute.return_value={'items':[
        dict(status=dict(privacyStatus='private',uploadStatus='processed'),processingDetails=dict(processingStatus='succeeded'),
             snippet=dict(channelId='synthetic'))]}
    saved=[]
    result=uploader._wait_for_processing(service,dict(video_id='synthetic'), 'private','synthetic',1,saved.append)
    assert result['status']=='processed' and result['privacy_status']=='private'


def test_tiktok_test_and_browser_never_post(tmp_path,monkeypatch):
    from tiktok import uploader
    video=tmp_path/'synthetic.mp4';video.write_bytes(b'x')
    token=MagicMock(side_effect=AssertionError('auth'))
    monkeypatch.setattr(uploader,'get_tiktok_token',token)
    assert uploader.upload_to_tiktok(video,{},test=True)['status']=='skipped'
    assert uploader.upload_to_tiktok_cookies(video,'x')['status']=='failed'
    token.assert_not_called()


def test_auto_test_does_not_import_or_call_uploader(monkeypatch):
    import main
    monkeypatch.setattr(main,'cmd_generate',lambda args:dict(video_path='synthetic'))
    args=SimpleNamespace(test=True,dry_run=False)
    assert main.cmd_auto(args)['status']=='generated_test'


def test_immediate_review_reply_is_preserved(manifest_video,monkeypatch):
    from notifications import telegram_bot as bot
    from notifications.publishing_policy import require_automatic_approval
    import database.jobs as jobs
    monkeypatch.setenv('TELEGRAM_APPROVER_ID','42');monkeypatch.setattr(bot,'TELEGRAM_CHAT_ID','7')
    monkeypatch.setattr(bot,'is_configured',lambda:True)
    monkeypatch.setattr(bot,'send_message',lambda *a:{'ok':True})
    marked=MagicMock();monkeypatch.setattr(jobs,'mark_job',marked)
    sent={};offsets=[]
    def send(video,caption):
        sent['command']=caption.splitlines()[2]
        return {'ok':True,'result':{'message_id':10}}
    monkeypatch.setattr(bot,'send_video',send)
    def updates(offset=None):
        offsets.append(offset)
        if 'command' not in sent:return [{'update_id':9}]
        return [dict(update_id=10,message=dict(text=sent['command'],chat={'id':7},
            **{'from':{'id':42}},reply_to_message={'message_id':10}))]
    monkeypatch.setattr(bot,'get_updates',updates)
    approval=require_automatic_approval(manifest_video[0],META,job_id='synthetic',expected_account='expected')
    assert approval['approver_id']=='42' and offsets==[None,10]
    marked.assert_called_once()


def test_youtube_resume_never_reinserts_existing_receipt(manifest_video,monkeypatch):
    from youtube import uploader
    from database import jobs
    receipt=dict(video_id='synthetic',status='transferred',privacy_status='private')
    monkeypatch.setattr(jobs,'read_upload_receipts',lambda job:{'youtube':receipt})
    monkeypatch.setattr(jobs,'record_upload_receipt',lambda *a:None)
    service=MagicMock()
    service.videos.return_value.list.return_value.execute.return_value={'items':[
        dict(status=dict(privacyStatus='private',uploadStatus='processed'),processingDetails=dict(processingStatus='succeeded'))]}
    monkeypatch.setattr(uploader,'get_authenticated_service',lambda:service)
    result=uploader.upload_video(manifest_video[0],META,privacy_status='private',job_id='synthetic',processing_timeout=1)
    assert result['status']=='processed'
    service.videos.return_value.insert.assert_not_called()


def test_youtube_processing_failure_retains_receipt():
    from youtube import uploader
    service=MagicMock();service.videos.return_value.list.return_value.execute.return_value={'items':[
        dict(status=dict(privacyStatus='public',uploadStatus='failed'),processingDetails=dict(processingStatus='failed'))]}
    saved=[]
    with pytest.raises(uploader.YouTubeUploadError):
        uploader._wait_for_processing(service,dict(video_id='synthetic'),'public',None,1,saved.append)
    assert saved[0]['status']=='failed' and saved[0]['video_id']=='synthetic'


def test_tiktok_wrong_oauth_state_rejected_before_token_exchange(monkeypatch):
    from tiktok import auth
    monkeypatch.setattr(auth,'TIKTOK_CLIENT_KEY','synthetic');monkeypatch.setattr(auth,'TIKTOK_CLIENT_SECRET','synthetic')
    monkeypatch.setattr(auth,'TIKTOK_REDIRECT_URI','https://localhost:8080/')
    monkeypatch.setattr(auth.webbrowser,'open',lambda *a:None)
    monkeypatch.setattr(auth.secrets,'token_urlsafe',lambda *a:'expected')
    monkeypatch.setattr('builtins.input',lambda *a:'https://localhost:8080/?code=synthetic&state=wrong')
    transport=MagicMock(side_effect=AssertionError('token exchange'))
    monkeypatch.setattr(auth.requests,'post',transport)
    with pytest.raises(auth.TikTokAuthError,match='state'):auth.authenticate_interactive()
    transport.assert_not_called()


def test_tiktok_large_video_streams_valid_chunks_and_waits_for_final_id(tmp_path,monkeypatch):
    from tiktok import uploader,auth
    video=tmp_path/'sparse.mp4'
    with video.open('wb') as stream:stream.truncate(65*1024*1024)
    monkeypatch.setattr(uploader,'get_tiktok_token',lambda:'synthetic')
    monkeypatch.setattr(auth,'load_token_data',lambda:{'open_id':'expected'})
    chunks=[];payloads=[]
    def response(data,status=200):return SimpleNamespace(status_code=status,json=lambda:data)
    def post(url,**kw):
        payloads.append((url,kw.get('json')))
        if 'creator_info' in url:return response({'error':{'code':'ok'},'data':{'privacy_level_options':['PUBLIC_TO_EVERYONE']}})
        if 'status/fetch' in url:return response({'error':{'code':'ok'},'data':{'status':'PUBLISH_COMPLETE','publicaly_available_post_id':['real-synthetic-post-id']}})
        return response({'error':{'code':'ok'},'data':{'upload_url':'https://example.invalid','publish_id':'synthetic-publish-id'}})
    def put(url,**kw):
        assert hasattr(kw['data'],'__len__')
        sizes=[len(block) for block in kw['data']]
        assert max(sizes)<=64*1024
        chunks.append((kw['headers']['Content-Range'],sum(sizes)))
        return response({},206 if len(chunks)==1 else 201)
    monkeypatch.setattr(uploader.requests,'post',post);monkeypatch.setattr(uploader.requests,'put',put)
    result=uploader.upload_to_tiktok_api(video,'synthetic',privacy_status='PUBLIC_TO_EVERYONE',expected_open_id='expected',timeout=1)
    assert result['status']=='published' and result['post_ids']==['real-synthetic-post-id']
    assert len(chunks)==2 and sum(length for _,length in chunks)==65*1024*1024
    assert payloads[1][1]['source_info']['total_chunk_count']==2


def test_three_regenerations_keep_same_verses_and_never_upload(manifest_video,monkeypatch):
    import main
    from database import jobs
    from notifications import publishing_policy as policy
    from core import verse_scheduler as scheduler
    from youtube import uploader
    video,manifest=manifest_video
    monkeypatch.setenv('FRIDAY_MODE_ENABLED','false')
    monkeypatch.setattr(scheduler,'get_next_verses',lambda *a:(1,1,3))
    job=dict(id='synthetic',surah=1,start_ayah=1,end_ayah=3,reciter_key='alafasy',status='reserved')
    monkeypatch.setattr(jobs,'reserve_job',lambda *a,**kw:job)
    monkeypatch.setattr(jobs,'mark_job',lambda *a,**kw:None)
    monkeypatch.setattr(jobs,'read_upload_receipts',lambda *a:{})
    monkeypatch.setattr(jobs,'assert_transfer_retry_safe',lambda *a:None)
    ranges=[]
    def generate(args):
        ranges.append((args.surah,args.start,args.end))
        return dict(video_path=video,surah=1,start_ayah=1,end_ayah=3,reciter='alafasy',full_text='synthetic')
    monkeypatch.setattr(main,'cmd_generate',generate)
    monkeypatch.setattr(uploader,'generate_metadata',lambda **kw:META)
    review=MagicMock(side_effect=policy.PublishingPolicyError('regenerate','regenerate'))
    monkeypatch.setattr(policy,'require_automatic_approval',review)
    upload=MagicMock(side_effect=AssertionError('unapproved publication'))
    monkeypatch.setattr(uploader,'upload_video',upload)
    args=SimpleNamespace(surah=None,start=None,end=None,verses=3,reciter='alafasy',test=False,dry_run=False)
    result=main._run_auto_reel(args)
    assert result['status']=='failed' and ranges==[(1,1,3)]*3
    upload.assert_not_called()


def test_thumbnail_change_stops_before_youtube_auth(manifest_video,tmp_path,monkeypatch):
    from notifications.publishing_policy import package_digest,thumbnail_digest
    from youtube import uploader
    thumbnail=tmp_path/'thumbnail.jpg';thumbnail.write_bytes(b'original-thumbnail')
    digest,_=package_digest(manifest_video[0],META,platform='youtube',privacy_status='public',
                            expected_account='expected',thumbnail_path=thumbnail)
    approval=dict(job_id='synthetic',package_hash=digest,thumbnail_path=str(thumbnail.resolve()),thumbnail_sha256=thumbnail_digest(thumbnail))
    thumbnail.write_bytes(b'changed-thumbnail')
    auth=MagicMock(side_effect=AssertionError('unapproved mutation'))
    monkeypatch.setattr(uploader,'get_authenticated_service',auth)
    with pytest.raises(uploader.YouTubeUploadError,match='Approval'):
        uploader.upload_video(manifest_video[0],META,automatic=True,job_id='synthetic',approval=approval,
            thumbnail_path=thumbnail,expected_channel_id='expected')
    auth.assert_not_called()


def test_thumbnail_delivery_failure_stops_before_video_review(manifest_video,tmp_path,monkeypatch):
    from notifications import telegram_bot as bot
    from notifications.publishing_policy import require_automatic_approval,PublishingPolicyError
    thumbnail=tmp_path/'thumbnail.jpg';thumbnail.write_bytes(b'synthetic')
    monkeypatch.setenv('TELEGRAM_APPROVER_ID','42')
    monkeypatch.setattr(bot,'is_configured',lambda:True)
    monkeypatch.setattr(bot,'get_updates',lambda:[])
    monkeypatch.setattr(bot,'send_message',lambda *a:{'ok':True})
    monkeypatch.setattr(bot,'send_photo',lambda *a:None)
    video=MagicMock(side_effect=AssertionError('incomplete review'))
    monkeypatch.setattr(bot,'send_video',video)
    with pytest.raises(PublishingPolicyError,match='Thumbnail review delivery'):
        require_automatic_approval(manifest_video[0],META,job_id='synthetic',expected_account='expected',thumbnail_path=thumbnail)
    video.assert_not_called()


def test_telegram_video_and_photo_send_exact_separate_files(manifest_video,tmp_path,monkeypatch):
    from notifications import telegram_bot as bot
    monkeypatch.setattr(bot,'is_configured',lambda:True)
    sent=[]
    def post(url,**kw):
        sent.append((url,{key:value.read() for key,value in kw['files'].items()}))
        return SimpleNamespace(status_code=200,json=lambda:{'ok':True})
    monkeypatch.setattr(bot.requests,'post',post)
    thumbnail=tmp_path/'thumbnail.jpg';thumbnail.write_bytes(b'image')
    assert bot.send_video(manifest_video[0],'video')['ok']
    assert bot.send_photo(thumbnail,'photo')['ok']
    assert sent[0][0].endswith('/sendVideo') and sent[0][1]=={'video':manifest_video[0].read_bytes()}
    assert sent[1][0].endswith('/sendPhoto') and sent[1][1]=={'photo':b'image'}
