"""
TikTok Uploader - Upload videos to TikTok using either cookies.txt or Content Posting API
"""
from pathlib import Path
from typing import Dict, Any, Optional
import os
import requests
import time
from loguru import logger

from config.settings import TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_TOKEN_PATH
from tiktok.auth import get_tiktok_token


class _FileChunk:
    """A sized stream prevents requests from adding ambiguous chunked encoding."""
    def __init__(self,stream,length):
        self.stream,self.length=stream,length
    def __len__(self):
        return self.length
    def __iter__(self):
        remaining=self.length
        while remaining:
            block=self.stream.read(min(64*1024,remaining))
            if not block:
                raise ValueError('Video changed during transfer')
            remaining-=len(block)
            yield block


def is_configured() -> bool:
    """Check if TikTok uploading is configured via either cookies.txt or Developer API."""
    if Path("cookies.txt").exists():
        logger.warning('Cookie posting disabled; configure an identity-bound API token')
    token = get_tiktok_token()
    return token is not None


def generate_tiktok_metadata(
    surah_name_ar: str,
    surah_name_en: str,
    surah_num: int,
    start_ayah: int,
    end_ayah: int,
    reciter_name_ar: str
) -> Dict[str, Any]:
    """Generate metadata for TikTok upload."""
    verse_range = f"{start_ayah}" if start_ayah == end_ayah else f"{start_ayah}-{end_ayah}"
    
    caption = f"""🕌 سورة {surah_name_ar} | آية {verse_range}
📖 Surah {surah_name_en} ({surah_num})
🎙️ {reciter_name_ar}

#Quran #القرآن #Islam #QuranRecitation #Islamic #Muslim #Deen #Allah #QuranVerses #QuranDaily"""

    return {
        "caption": caption,
        "description": f"Surah {surah_name_en} Ayah {verse_range}",
    }


def upload_to_tiktok_api(video_path: Path, caption: str, *, privacy_status='SELF_ONLY',
                         expected_open_id=None, job_id=None, timeout=120) -> Optional[Dict[str, Any]]:
    """Upload using the official Content Posting API."""
    token = get_tiktok_token()
    if not token:
        return {"status": "failed", "error": "TikTok API not authenticated."}
    from tiktok.auth import load_token_data
    identity=load_token_data() or {}
    expected_open_id=expected_open_id or os.getenv('TIKTOK_EXPECTED_OPEN_ID','')
    if not expected_open_id or identity.get('open_id') != expected_open_id:
        return {'status':'failed','error':'TikTok token does not attest intended account'}
    if privacy_status not in ('SELF_ONLY','PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR'):
        return {'status':'failed','error':'Unsupported TikTok privacy'}
        
    video_size = video_path.stat().st_size
    chunk_size = video_size if video_size <= 64*1024*1024 else 32*1024*1024
    chunk_count = max(1,video_size//chunk_size) if chunk_size else 0
    if not 0 < chunk_count <= 1000:
        return {'status':'failed','error':'Invalid or oversized media'}
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8"
    }
    
    payload = {
        "post_info": {
            "title": caption,
            "privacy_level": privacy_status,
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": chunk_count
        }
    }
    
    try:
        creator=requests.post('https://open.tiktokapis.com/v2/post/publish/creator_info/query/',
                              headers=headers,json={},timeout=20)
        creator_data=creator.json()
        if creator.status_code!=200 or creator_data.get('error',{}).get('code')!='ok' or privacy_status not in creator_data.get('data',{}).get('privacy_level_options',[]):
            return {'status':'failed','error':'Intended TikTok privacy is unavailable for creator'}
        if job_id:
            from database.jobs import read_upload_receipts,record_upload_receipt,assert_transfer_retry_safe,begin_upload_attempt
            prior=read_upload_receipts(job_id).get('tiktok')
            if prior:
                return _wait_for_tiktok_status(token,prior,privacy_status,timeout,
                    lambda r:record_upload_receipt(job_id,'tiktok',r))
            assert_transfer_retry_safe(job_id,'tiktok')
            begin_upload_attempt(job_id,'tiktok')
        init_res = requests.post(init_url, headers=headers, json=payload, timeout=20)
        if init_res.status_code != 200:
            return {"status": "failed", "error": f"Init HTTP {init_res.status_code}"}
            
        res_data = init_res.json()
        error_info = res_data.get("error", {})
        if error_info.get("code") != "ok":
            return {"status": "failed", "error": 'TikTok initialization rejected'}
            
        data = res_data.get("data", {})
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        if not upload_url or not publish_id:
            return {'status':'failed','error':'Missing TikTok transfer identity'}
        receipt={'status':'transferred','publish_id':publish_id,'privacy_status':privacy_status}
        save=lambda r:record_upload_receipt(job_id,'tiktok',r) if job_id else None
        save(receipt)
        
        # PUT request
        put_headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(video_size),
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}"
        }
        
        with open(video_path,'rb') as stream:
            offset=0
            for idx in range(chunk_count):
                length=chunk_size if idx < chunk_count-1 else video_size-offset
                put_headers.update({'Content-Length':str(length),
                    'Content-Range':f'bytes {offset}-{offset+length-1}/{video_size}'})
                put_res=requests.put(upload_url,headers=put_headers,data=_FileChunk(stream,length),timeout=30)
                if put_res.status_code != (206 if idx<chunk_count-1 else 201):
                    return dict(receipt,status='failed',error='Media chunk transfer rejected')
                offset+=length
        return _wait_for_tiktok_status(token,receipt,privacy_status,timeout,save)
    except Exception as e:
        return {"status": "failed", "error": type(e).__name__}


def _wait_for_tiktok_status(token,receipt,privacy_status,timeout,save):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        response=requests.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
            json={'publish_id':receipt['publish_id']},timeout=20)
        body=response.json()
        if response.status_code!=200 or body.get('error',{}).get('code')!='ok':
            return dict(receipt,status='processing',error='Status unavailable; reconcile existing transfer')
        data=body.get('data',{})
        if data.get('status')=='FAILED':
            final=dict(receipt,status='failed',error='TikTok processing failed');save(final);return final
        if data.get('status')=='PUBLISH_COMPLETE':
            ids=data.get('publicaly_available_post_id',[])
            if privacy_status=='PUBLIC_TO_EVERYONE' and not ids:
                time.sleep(2);continue
            final=dict(receipt,status='published' if privacy_status=='PUBLIC_TO_EVERYONE' else 'processed',
                       post_ids=ids);save(final);return final
        time.sleep(2)
    final=dict(receipt,status='processing',error='Processing deadline elapsed');save(final);return final


def upload_to_tiktok_cookies(video_path: Path, caption: str) -> Optional[Dict[str, Any]]:
    """Browser posting cannot attest identity, privacy or a real final receipt."""
    return {'status':'failed','error':'Browser posting disabled: identity, visibility and real post receipt cannot be attested'}


def upload_to_tiktok(video_path: Path, metadata: Dict[str, Any], **kwargs) -> Optional[Dict[str, Any]]:
    """
    Upload a video to TikTok using either the cookies.txt method or the official API.
    """
    video_path = Path(video_path)
    if kwargs.pop('test',False):
        return {'status':'skipped','error':'Test mode suppresses all external publication'}
    automatic=kwargs.pop('automatic',False)
    approval=kwargs.pop('approval',None)
    if automatic:
        from notifications.publishing_policy import package_digest
        expected=kwargs.get('expected_open_id') or os.getenv('TIKTOK_EXPECTED_OPEN_ID','')
        if not approval or not kwargs.get('job_id'):
            return {'status':'failed','error':'TikTok automatic upload requires independent final review'}
        digest,_=package_digest(video_path,metadata,platform='tiktok',
            privacy_status=kwargs.get('privacy_status','SELF_ONLY'),expected_account=expected)
        if approval.get('job_id')!=kwargs['job_id'] or approval.get('package_hash')!=digest:
            return {'status':'failed','error':'TikTok approval does not match final package'}
    if not video_path.exists():
        return {"status": "failed", "error": "Video file not found"}
        
    caption = metadata.get("caption", "Beautiful Quran Recitation")
    if len(caption) > 2200:
        caption = caption[:2197] + "..."
        
    # Method 1: cookies.txt (prioritized for simplicity)
        
    # Method 2: Official Developer API
    if get_tiktok_token():
        return upload_to_tiktok_api(video_path, caption, **kwargs)
        
    return {"status": "failed", "error": "No TikTok upload method configured. Add cookies.txt or developer keys."}


def get_tiktok_status() -> Dict[str, Any]:
    """Inspect cached configuration without refreshing credentials or contacting APIs."""
    from tiktok.auth import load_token_data
    cached=load_token_data() or {}
    expected=os.getenv('TIKTOK_EXPECTED_OPEN_ID','')
    keys=bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET)
    identity_matches=bool(expected and cached.get('open_id')==expected)
    valid=bool(cached.get('access_token') and time.time()+300<cached.get('expires_at',0))
    refreshable=bool(cached.get('refresh_token'))
    configured=keys and identity_matches and (valid or refreshable)
    if configured:
        message='Developer API identity configured; cached token valid' if valid else 'Developer API identity configured; token refresh needed on upload'
    else:
        message='Configure Developer API keys, explicit OAuth authorization and matching TIKTOK_EXPECTED_OPEN_ID. Browser cookie posting is disabled.'
    return dict(enabled=keys,configured=configured,library_installed=True,message=message)
