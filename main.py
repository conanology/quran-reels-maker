#!/usr/bin/env python3
"""
Quran Reels Maker - Automated Quran Short Videos for YouTube & TikTok

Usage:
    python main.py generate              Preview the next rotating Short
    python main.py generate --surah 112  Generate specific surah
    python main.py upload <video_path>   Upload a video to YouTube
    python main.py tiktok <video_path>   Upload a video to TikTok
    python main.py auto                  Generate AND upload (for automation)
    python main.py status                Show current progress
    python main.py setup-youtube         Set up YouTube authentication
    python main.py history               Show recent upload history
"""

import sys
import os
import argparse
from pathlib import Path
from loguru import logger

# Configure logging
from config.settings import LOG_FILE, LOG_LEVEL, LOG_FORMAT, BASE_DIR, OUTPUTS_DIR

def configure_logging(file_logging=True):
    """Only an invoked CLI configures sinks; import and dry-run create no logs."""
    logger.remove()
    logger.add(sys.stderr,level=LOG_LEVEL,format=LOG_FORMAT,diagnose=False,backtrace=False)
    if file_logging:
        logger.add(LOG_FILE,level=LOG_LEVEL,format=LOG_FORMAT,rotation='10 MB',diagnose=False,backtrace=False)


def cmd_generate(args):
    """Generate a new Quran reel video."""
    if args.dry_run:
        print('DRY RUN: generation preview; sequence is read only when generation runs')
        return {'status':'dry_run','requested_surah':getattr(args,'surah',None)}
    from core.video_generator import generate_reel
    from core.verse_scheduler import record_reel_history
    from core.quran_api import get_surah_name
    from config.settings import RECITERS, VERSE_COUNTS
    from core.shorts_policy import require_shorts_reciter
    from database.jobs import get_next_shorts_selection
    if args.reciter:
        try:
            require_shorts_reciter(args.reciter)
        except ValueError as error:
            return {'status':'failed','error':str(error)}
    selection = get_next_shorts_selection() if not args.reciter or not args.surah else None
    reciter = args.reciter or selection['reciter_key']
    
    if args.surah:
        # Generate specific verses
        surah = args.surah
        start = args.start or 1
        end = args.end or (start + args.verses - 1)
        logger.info(f"Generating specified verses: Surah {surah}, Ayat {start}-{end}")
    else:
        surah, start = selection['surah'], selection['start_ayah']
        end = min(start + args.verses - 1, VERSE_COUNTS[surah])
        logger.info("Next rotating Short: Surah {}, Ayat {}-{}", surah, start, end)
    
    # Show what we're generating
    surah_name = get_surah_name(surah, "ar")
    reciter_name = RECITERS.get(reciter, {}).get("name_ar", reciter)
    
    print("\n" + "="*50)
    print("🕌 QURAN REELS MAKER")
    print("="*50)
    print(f"📖 Surah: {surah_name} ({surah})")
    print(f"🔢 Verses: {start} - {end}")
    print(f"🎙️ Reciter: {reciter_name}")
    print("="*50 + "\n")
    
    if args.dry_run:
        print("🔍 DRY RUN - No video will be generated")
        return {'status':'dry_run'}
    
    # Generate the reel
    try:
        video_path, actual_start, actual_end = generate_reel(
            surah=surah,
            start_ayah=start,
            end_ayah=end,
            reciter_key=reciter,
            **({'output_path': Path(OUTPUTS_DIR) / 'jobs' / args._job_id / 'reel.mp4'}
               if getattr(args,'_job_id',None) else {})
        )
        
        # Record in history using ACTUAL range (in case it was extended)
        from core.utils import load_media_manifest
        manifest=load_media_manifest(video_path)
        full_text=' '.join(verse.get('text','') for verse in manifest['verses']).strip()
        history_id = None if getattr(args,'_job_id',None) or getattr(args,'test',False) else record_reel_history(
            surah=surah,
            start_ayah=actual_start,
            end_ayah=actual_end,
            reciter_key=reciter,
            video_path=str(video_path)
        )
        
        # Generation reserves no published coverage. Only a verified platform
        # receipt and atomic finalization may advance the publication journey.
        
        print(f"\n✅ Video generated successfully!")
        print(f"📂 Output: {video_path}")
        print(f"Verses: {actual_start}-{actual_end}")
        
        return {
            'video_path': video_path,
            'history_id': history_id,
            'surah': surah,
            'start_ayah': actual_start,
            'end_ayah': actual_end,
            'reciter': reciter,
            'full_text': full_text
        }
        
    except Exception as e:
        logger.error(f"Generation failed: {type(e).__name__}")
        print(f"\n❌ Error: {type(e).__name__}")
        return {'status':'failed','error':type(e).__name__}


def cmd_upload(args):
    """Upload a video to YouTube."""
    from youtube.uploader import upload_video, upload_as_private, generate_metadata
    from youtube.auth import check_authentication_status
    from core.verse_scheduler import update_reel_youtube_id
    
    # Check authentication
    auth_status = check_authentication_status()
    if auth_status['status'] not in ('valid','expired'):
        print(f"❌ {auth_status['message']}")
        return {'status':'failed','error':'Authentication unavailable'}
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"❌ Video file not found: {video_path}")
        return {'status':'failed','error':'Video file not found'}
    
    # Generate or use provided metadata
    if args.title:
        metadata = {
            'title': args.title,
            'description': args.description or "",
            'tags': args.tags.split(',') if args.tags else []
        }
    else:
        # Try to parse from filename
        metadata = {
            'title': video_path.stem + " #Shorts",
            'description': "Quran Recitation #Shorts",
            'tags': ['Quran', 'Islam', 'Shorts']
        }
    
    print("\n" + "="*50)
    print("📤 UPLOADING TO YOUTUBE")
    print("="*50)
    print(f"📹 Video: {video_path.name}")
    print(f"📝 Title: {metadata['title']}")
    print(f"🔒 Privacy: {args.privacy}")
    print("="*50 + "\n")
    
    try:
        if args.privacy == 'private':
            result = upload_as_private(video_path, metadata)
        else:
            result = upload_video(video_path, metadata, privacy_status=args.privacy)
        
        print(f"\n✅ Upload successful!")
        print(f"🎬 Video ID: {result['video_id']}")
        print(f"🔗 URL: {result['url']}")
        
        # Update history if we have a history ID
        if args.history_id:
            update_reel_youtube_id(args.history_id, result['video_id'])
        
        return result
        
    except Exception as e:
        logger.error(f"Upload failed: {type(e).__name__}")
        print(f"\n❌ Upload failed: {type(e).__name__}")
        return {'status':'failed','error':type(e).__name__}


def cmd_auto(args):
    """Generate, review the final package, then publish one reserved job."""
    from config.settings import DATABASE_PATH
    from core.runtime_safety import exclusive_lock, LockTimeoutError
    if args.dry_run:
        return {'status':'dry_run'}
    if args.test:
        result=cmd_generate(args)
        if result and result.get('status') != 'failed':
            result['status']='generated_test'
        return result
    try:
        with exclusive_lock(DATABASE_PATH.parent / 'publishing.lock', timeout=0):
            return _run_auto_reel(args)
    except LockTimeoutError:
        return {'status':'skipped','reason':'Another automatic job owns the publishing lock'}


def _run_auto_reel(args):
    import copy
    import json
    from config.settings import RECITERS, VERSE_COUNTS
    from database.jobs import reserve_job, mark_job, read_upload_receipts, finalize_published_job, assert_transfer_retry_safe, get_next_shorts_selection
    from core.shorts_policy import require_shorts_reciter
    from notifications.publishing_policy import require_automatic_approval, PublishingPolicyError
    from youtube.uploader import upload_video, generate_metadata
    from core.utils import load_media_manifest, require_manifest_coverage
    selected=copy.copy(args)
    rotation=True
    if args.reciter:
        try:
            require_shorts_reciter(args.reciter)
        except ValueError as error:
            return {'status':'failed','error':str(error)}
    selection=get_next_shorts_selection()
    if args.surah:
        surah,start,end=args.surah,args.start or 1,args.end or ((args.start or 1)+args.verses-1)
        if (surah,start)!=(selection['surah'],selection['start_ayah']):
            return {'status':'failed','error':'Automatic Shorts must follow the next surah/ayah in the rotation; use generate for a specific preview'}
    else:
        surah,start=selection['surah'],selection['start_ayah']
        end=min(start+args.verses-1,VERSE_COUNTS[surah])
    reciter=args.reciter or selection['reciter_key']
    if rotation and reciter!=selection['reciter_key']:
        return {'status':'failed','error':'Automatic Shorts must use the next reader in the rotation; omit --reciter'}
    key=f"shorts-rotation:{surah}:{start}:{selection['cycle']}"
    job=reserve_job(key,surah=surah,start_ayah=start,end_ayah=end,reciter_key=reciter,
                    shorts_rotation=rotation,cycle=selection['cycle'] if rotation else None)
    require_shorts_reciter(job['reciter_key'])
    if job.get('finalized'):
        return dict(read_upload_receipts(job['id']).get('youtube',{}),status='skipped')
    selected.surah,selected.start,selected.end=job['surah'],job['start_ayah'],job['end_ayah']
    selected.reciter=job['reciter_key']
    selected._job_id=job['id']
    completed_receipt=None
    try:
        existing_receipt=read_upload_receipts(job['id']).get('youtube')
        if not existing_receipt:
            assert_transfer_retry_safe(job['id'],'youtube')
        for attempt in range(3):
            if existing_receipt:
                if not job.get('video_path') or not job.get('metadata_json') or not job.get('approval'):
                    raise RuntimeError('Existing remote receipt needs explicit reconciliation; retransfers are forbidden')
                metadata=json.loads(job['metadata_json'])
                approval=json.loads(job['approval'])
                video_path=Path(job['video_path'])
                manifest=load_media_manifest(video_path)
                require_manifest_coverage(manifest,surah_start=job['surah'],start_ayah=job['start_ayah'],
                    surah_end=job['surah'],end_ayah=job['end_ayah'],reciter_key=job['reciter_key'])
                coverage=manifest['coverage'][0]
                generated=dict(video_path=video_path,surah=coverage['surah'],start_ayah=coverage['start_ayah'],
                               end_ayah=coverage['end_ayah'],reciter=job['reciter_key'])
            else:
                generated=cmd_generate(selected)
                if not generated or generated.get('status')=='failed':
                    raise RuntimeError('Video generation failed')
                video_path=Path(generated['video_path'])
                manifest=load_media_manifest(video_path)
                if (generated['surah'],generated['start_ayah'],generated['reciter'])!=(job['surah'],job['start_ayah'],job['reciter_key']):
                    raise ValueError('Generated range or reciter differs from reserved publication')
                require_manifest_coverage(manifest,surah_start=generated['surah'],start_ayah=generated['start_ayah'],
                    surah_end=generated['surah'],end_ayah=generated['end_ayah'],reciter_key=generated['reciter'])
                metadata=generate_metadata(surah=generated['surah'],start_ayah=generated['start_ayah'],
                    end_ayah=generated['end_ayah'],reciter_key=generated['reciter'],full_text=generated['full_text'])
                mark_job(job['id'],'generated',video_path=str(video_path),metadata_json=json.dumps(metadata),
                         manifest=manifest,end_ayah=generated['end_ayah'])
                try:
                    approval=require_automatic_approval(video_path,metadata,job_id=job['id'],manifest=manifest)
                except PublishingPolicyError as error:
                    mark_job(job['id'],error.decision,error_message=str(error))
                    if error.decision=='regenerate' and attempt<2:
                        continue
                    return {'status':'failed','decision':error.decision,'job_id':job['id'],'error':str(error)}
            receipt=upload_video(video_path,metadata,privacy_status='public',automatic=True,
                                 job_id=job['id'],approval=approval)
            finalize_published_job(job['id'],dict(surah=generated['surah'],start_ayah=generated['start_ayah'],
                end_ayah=generated['end_ayah'],reciter_key=generated['reciter'],
                video_path=str(video_path)),receipt)
            completed_receipt=dict(receipt)
            # Crossposting is a separate reviewed publishing operation. It is off
            # by default and has its own identity, privacy and final package hash.
            if os.getenv('ENABLE_TIKTOK_AUTOPUBLISH','false').lower()=='true':
                from tiktok.uploader import upload_to_tiktok, generate_tiktok_metadata
                from config.settings import SURAH_NAMES_AR, SURAH_NAMES_EN
                s=generated['surah']
                tt=generate_tiktok_metadata(SURAH_NAMES_AR[s-1],SURAH_NAMES_EN[s-1],s,
                    generated['start_ayah'],generated['end_ayah'],RECITERS[generated['reciter']]['name_ar'])
                tt.update(title=metadata['title'],description=tt['caption'],tags=[])
                review=require_automatic_approval(video_path,tt,job_id=job['id'],platform='tiktok',
                    privacy_status='PUBLIC_TO_EVERYONE',manifest=manifest)
                tt_result=upload_to_tiktok(video_path,tt,automatic=True,job_id=job['id'],approval=review,
                                          privacy_status='PUBLIC_TO_EVERYONE')
                receipt['tiktok_status']=tt_result.get('status')
                if tt_result.get('status')!='published':
                    return dict(receipt,status='partial',error='YouTube published; TikTok requires recovery')
            print(f"Publication confirmed ({receipt['privacy_status']}): {receipt['url']}")
            return receipt
        return {'status':'failed','error':'Regeneration attempts exhausted','job_id':job['id']}
    except Exception as error:
        if completed_receipt is not None:
            logger.error(f'Post-publication step failed: {type(error).__name__}; confirmed YouTube publication retained')
            return dict(completed_receipt,status='partial',error=type(error).__name__,job_id=job['id'])
        mark_job(job['id'],'failed',error_message=type(error).__name__)
        logger.error(f'Automatic job failed: {type(error).__name__}; media and receipts retained')
        return {'status':'failed','error':type(error).__name__,'job_id':job['id']}


def cmd_batch(args):
    """Generate and upload multiple reels in one run (for scheduled automation)."""
    import time

    count = args.count
    delay = args.delay
    print(f"\n🚀 BATCH MODE - Generating {count} videos\n")

    results = []
    for i in range(1, count + 1):
        print(f"\n{'='*50}")
        print(f"📹 VIDEO {i}/{count}")
        print(f"{'='*50}")

        result = cmd_auto(args)
        results.append(result)

        if result is None:
            print(f"⚠️ Video {i} failed, continuing...")

        # Delay between videos to respect API rate limits
        if i < count:
            print(f"\n⏳ Waiting {delay}s before next video...")
            time.sleep(delay)

    # Summary
    success = sum(1 for r in results if r and r.get('status') in ('published','processed'))
    failed = sum(1 for r in results if r is None or r.get('status') in ('failed','partial'))
    local_only = count - success - failed

    print(f"\n{'='*50}")
    print(f"📊 BATCH COMPLETE")
    print(f"{'='*50}")
    print(f"   ✅ Uploaded: {success}")
    if local_only:
        print(f"   💾 Saved locally: {local_only}")
    if failed:
        print(f"   ❌ Failed: {failed}")
    print(f"{'='*50}\n")
    return {'status':'failed' if failed else 'completed','uploaded':success,'failed':failed,'local_only':local_only}


def cmd_status(args):
    """Show current progress and statistics."""
    from core.verse_scheduler import get_current_progress, get_statistics, get_reel_history
    from database.models import init_database, get_db_session, SurahShortsProgress
    from database.jobs import get_next_shorts_selection
    from config.settings import RECITERS, SURAH_NAMES_AR
    
    init_database()
    
    progress = get_current_progress()
    stats = get_statistics()
    
    print("\n" + "="*50)
    print("📊 QURAN REELS MAKER - STATUS")
    print("="*50)
    
    selection = get_next_shorts_selection()
    with get_db_session() as session:
        saved_surahs = session.query(SurahShortsProgress).count()
    print("\n📍 Next Short (surah rotation):")
    print(f"   Surah: {SURAH_NAMES_AR[selection['surah']-1]} ({selection['surah']})")
    print(f"   Ayat: {selection['start_ayah']}-{selection['end_ayah']}")
    print(f"   Reciter: {RECITERS[selection['reciter_key']]['name_ar']}")
    print(f"   Saved surah positions: {saved_surahs}")
    print(f"\n📍 Legacy sequential position (separate from Shorts rotation):")
    print(f"   Surah: {progress['surah_name']} ({progress['surah']})")
    print(f"   Ayah: {progress['ayah']}")
    print(f"   Progress: {progress['percentage_complete']:.1f}%")
    print(f"   Verses Remaining: {progress['verses_remaining']}")
    
    print(f"\n📈 Statistics:")
    print(f"   Total Reels Generated: {stats['total_reels_in_history']}")
    print(f"   Uploaded to YouTube: {stats['uploaded_reels']}")
    print(f"   Pending Upload: {stats['pending_upload']}")
    
    # Show recent history
    history = get_reel_history(5)
    if history:
        print(f"\n📜 Recent Reels:")
        for h in history:
            status_icon = "✅" if h['status'] == 'uploaded' else "⏳"
            print(f"   {status_icon} {h['surah_name']} {h['start_ayah']}-{h['end_ayah']} ({h['reciter']})")
    
    # YouTube auth status
    from youtube.auth import check_authentication_status
    auth = check_authentication_status()
    
    print(f"\n🔐 YouTube Status:")
    status_icon = "✅" if auth['status'] == 'valid' else "❌"
    print(f"   {status_icon} {auth['message']}")
    
    # TikTok status
    from tiktok.uploader import get_tiktok_status
    tiktok = get_tiktok_status()
    
    print(f"\n🎵 TikTok Status:")
    status_icon = "✅" if tiktok['configured'] and tiktok.get('library_installed') else "⚠️"
    print(f"   {status_icon} {tiktok['message']}")
    
    print("\n" + "="*50 + "\n")


def cmd_tiktok(args):
    """Upload a video to TikTok."""
    from pathlib import Path
    from tiktok.uploader import (
        upload_to_tiktok,
        generate_tiktok_metadata,
        get_tiktok_status,
        is_configured
    )
    from core.quran_api import get_surah_name
    from config.settings import RECITERS
    
    # Check configuration
    status = get_tiktok_status()
    if not status['configured']:
        print(f"\n❌ TikTok not configured: {status['message']}")
        print('Configure Developer API keys, run setup-tiktok, and set TIKTOK_EXPECTED_OPEN_ID.')
        return {'status':'auth_error','error':status['message']}
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"\n❌ Video not found: {video_path}")
        return {'status':'failed','error':'Video not found'}
    
    # Parse video filename to extract metadata
    # Expected format: QuranReel_SURAH_NAME_VERSES_TIMESTAMP.mp4
    try:
        parts = video_path.stem.split('_')
        surah_num = int(parts[1])
        surah_name_ar = parts[2]
        verse_range = parts[3]
        
        if '-' in verse_range:
            start_ayah, end_ayah = map(int, verse_range.split('-'))
        else:
            start_ayah = end_ayah = int(verse_range)
        
        surah_name_en = get_surah_name(surah_num, "en")
        reciter = args.reciter or "Unknown Reciter"
        reciter_name = RECITERS.get(reciter, {}).get("name_ar", reciter)
    except (IndexError, ValueError):
        # Fallback for non-standard filenames
        surah_num = args.surah or 1
        surah_name_ar = get_surah_name(surah_num, "ar")
        surah_name_en = get_surah_name(surah_num, "en")
        start_ayah = args.start or 1
        end_ayah = args.end or 1
        reciter_name = "Quran Recitation"
    
    print(f"\n🎵 Uploading to TikTok: {video_path.name}")
    print(f"   Surah: {surah_name_ar} ({surah_num})")
    print(f"   Verses: {start_ayah}-{end_ayah}")
    
    # Generate metadata
    metadata = generate_tiktok_metadata(
        surah_name_ar=surah_name_ar,
        surah_name_en=surah_name_en,
        surah_num=surah_num,
        start_ayah=start_ayah,
        end_ayah=end_ayah,
        reciter_name_ar=reciter_name
    )
    
    # Upload
    result = upload_to_tiktok(video_path, metadata)
    
    if result:
        if result.get('status') in ('published','processed'):
            print(f"\nTikTok processing confirmed ({result.get('privacy_status','unknown visibility')})")
        elif result.get('status') == 'metadata_saved':
            print(f"\n📄 Metadata saved for manual upload: {result.get('meta_path')}")
        else:
            print(f"\n❌ Upload failed: {result.get('error', 'Unknown error')}")
    else:
        print(f"\n❌ Upload failed - check logs for details")
    return result or {'status':'failed','error':'No platform result'}


def cmd_setup_youtube(args):
    """Set up YouTube authentication."""
    from youtube.auth import (
        authenticate_interactive,
        test_authentication,
        check_authentication_status
    )
    from config.settings import YOUTUBE_CLIENT_SECRETS
    
    print("\n" + "="*50)
    print("🔐 YOUTUBE AUTHENTICATION SETUP")
    print("="*50)
    
    # Check for client secrets
    if not Path(YOUTUBE_CLIENT_SECRETS).exists():
        print(f"""
❌ Client secrets file not found!

To set up YouTube uploads, you need to:

1. Go to Google Cloud Console:
   https://console.cloud.google.com/

2. Create a new project (or select existing)

3. Enable the YouTube Data API v3:
   APIs & Services → Library → Search "YouTube Data API v3" → Enable

4. Create OAuth2 credentials:
   APIs & Services → Credentials → Create Credentials → OAuth Client ID
   - Application type: Desktop app
   - Name: Quran Reels Maker

5. Download the JSON file and save it as:
   {YOUTUBE_CLIENT_SECRETS}

Then run this command again.
""")
        return False
    
    print("\n✅ Client secrets file found!")
    print("\nStarting authentication flow...")
    print("A browser window will open for you to authorize the application.\n")
    
    try:
        authenticate_interactive()
        
        if args.test:
            print("\nTesting authentication...")
            if test_authentication():
                print("✅ Authentication test passed!")
            else:
                print("⚠️ Authentication test failed")
                return False
        
        print("\n✅ YouTube authentication complete!")
        print("You can now use 'python main.py auto' for automated uploads.")
        return True
        
    except Exception as e:
        print(f"\n❌ Authentication failed: {type(e).__name__}")
        return False


def cmd_setup_tiktok(args):
    """Set up TikTok authentication."""
    from tiktok.auth import authenticate_interactive
    print("\n" + "="*50)
    print("🎵 TIKTOK AUTHENTICATION SETUP")
    print("="*50)
    try:
        authenticate_interactive()
        print("\n✅ TikTok authentication complete!")
        return True
    except Exception as e:
        print(f"\n❌ Authentication failed: {type(e).__name__}")
        return False


def cmd_history(args):
    """Show reel generation history."""
    from core.verse_scheduler import get_reel_history
    
    history = get_reel_history(args.limit)
    
    print("\n" + "="*60)
    print("📜 REEL GENERATION HISTORY")
    print("="*60)
    
    if not history:
        print("\nNo reels generated yet.")
        print("Run 'python main.py generate' to create your first reel!\n")
        return
    
    for h in history:
        status_icon = "✅" if h['status'] == 'uploaded' else "⏳"
        created = h['created_at'][:10] if h['created_at'] else "Unknown"
        
        print(f"\n{status_icon} {h['surah_name']} ({h['surah']}) - Ayat {h['start_ayah']}-{h['end_ayah']}")
        print(f"   Reciter: {h['reciter']}")
        print(f"   Created: {created}")
        
        if h['youtube_id']:
            print(f"   YouTube: https://youtube.com/shorts/{h['youtube_id']}")
        else:
            print(f"   Video: {h['video_path']}")
    
    print("\n" + "="*60 + "\n")


def cmd_set_position(args):
    """Manually set the current position in the Quran."""
    from core.verse_scheduler import set_progress
    
    try:
        result = set_progress(args.surah, args.ayah)
        print(f"\n✅ Position set to Surah {result['surah_name']} ({result['surah']}), Ayah {result['ayah']}")
        print(f"   Progress: {result['percentage_complete']:.1f}%\n")
    except Exception as e:
        print(f"\n❌ Error: {e}\n")


def cmd_longform(args):
    """Handler for the 'longform' CLI command."""
    if args.lf_command is None:
        print("Usage: python main.py longform [list|status|compile|auto]")
        return
        
    if args.lf_command == 'list':
        from longform.scheduler import create_compilation_groups_from_scratch, get_already_compiled
        groups = create_compilation_groups_from_scratch()
        already_done = get_already_compiled()
        
        print("\n" + "="*70)
        print("📊 QURAN LONGFORM COMPILATIONS QUEUE")
        print("="*70)
        
        for idx, group in enumerate(groups, 1):
            key = (
                group["surah_start"],
                group["surah_end"],
                group.get("ayah_start"),
                group.get("ayah_end")
            )
            status_icon = "✅" if key in already_done else "⏳"
            ayah_str = ""
            if group["ayah_start"] is not None:
                ayah_str = f" (Ayahs {group['ayah_start']}-{group['ayah_end']})"
            
            print(f"   {idx:3d}. {status_icon} {group['title']}")
            print(f"        Surahs: {group['surah_start']} to {group['surah_end']}{ayah_str} | Est: {group['estimated_duration']/60:.1f} mins")
            
        print("="*70 + "\n")
        
    elif args.lf_command == 'status':
        from longform.scheduler import get_compilation_history
        history = get_compilation_history(15)
        
        print("\n" + "="*70)
        print("📜 QURAN LONGFORM COMPILATION HISTORY")
        print("="*70)
        
        if not history:
            print("\nNo longform compilations generated yet.")
        else:
            for h in history:
                status_icon = "✅" if h['status'] == 'uploaded' else "⏳"
                created = h['created_at'][:10] if h['created_at'] else "Unknown"
                ayah_str = ""
                if h['ayah_start'] is not None:
                    ayah_str = f" ({h['ayah_start']}-{h['ayah_end']})"
                
                print(f"\n{status_icon} {h['title']}")
                print(f"   Surahs: {h['surah_start']}-{h['surah_end']}{ayah_str} | Duration: {h['duration_formatted']}")
                print(f"   Created: {created} | Status: {h['status']}")
                if h['youtube_url']:
                    print(f"   YouTube: {h['youtube_url']}")
                elif h['video_path']:
                    print(f"   Video: {h['video_path']}")
        print("="*70 + "\n")
        
    elif args.lf_command == 'compile':
        from longform.compiler import generate_longform
        from longform.visual_randomizer import generate_compilation_style
        from config.settings import DEFAULT_RECITER, VERSE_COUNTS
        
        reciter = args.reciter or DEFAULT_RECITER
        surah = args.surah
        surah_end = args.surah_end or surah
        start_ayah = args.start
        end_ayah = args.end
        loop_count = args.loop or 1
        
        # Validate surah_end
        if surah_end < surah:
            print(f"❌ Error: --surah-end ({surah_end}) cannot be less than --surah ({surah})")
            return
            
        # Determine how many unique ayahs we are rendering
        total_ayahs = 0
        for s in range(surah, surah_end + 1):
            if s == surah and start_ayah is not None:
                sa = start_ayah
            else:
                sa = 1
            if s == surah_end and end_ayah is not None:
                ea = end_ayah
            else:
                ea = VERSE_COUNTS[s]
            total_ayahs += ea - sa + 1
            
        # Generate styles for each segment
        styles = generate_compilation_style(total_ayahs)
        
        if surah == surah_end:
            range_str = f"Surah {surah} (Ayahs {start_ayah or 1} to {end_ayah or VERSE_COUNTS[surah]})"
        else:
            range_str = f"Surahs {surah} to {surah_end}"
            
        print(f"\n🚀 Compiling {range_str} with reciter: {reciter} (loop count: {loop_count})")
        
        try:
            metadata = generate_longform(
                surah_start=surah,
                surah_end=surah_end,
                reciter_key=reciter,
                compilation_styles=styles,
                ayah_start=start_ayah,
                ayah_end=end_ayah,
                loop_count=loop_count
            )
            print("\n✅ Compilation successful!")
            print(f"   Output: {metadata['output_path']}")
            print(f"   Duration: {metadata['duration_formatted']}")
            return dict(metadata,status='generated')
        except Exception as e:
            logger.error(f"Manual compilation failed: {type(e).__name__}")
            print(f"\n❌ Error: {type(e).__name__}")
            return {'status':'failed','error':type(e).__name__}
            
    elif args.lf_command == 'auto':
        return cmd_auto_longform(args)


def cmd_auto_longform(args):
    import json
    from config.settings import DATABASE_PATH, DEFAULT_RECITER, VERSE_COUNTS
    from core.runtime_safety import exclusive_lock, LockTimeoutError
    from core.utils import load_media_manifest, require_manifest_coverage
    from database.jobs import reserve_job, mark_job, read_upload_receipts, finalize_published_job, assert_transfer_retry_safe
    from notifications.publishing_policy import require_automatic_approval
    from longform.scheduler import get_next_compilation
    from longform.compiler import generate_longform
    from youtube.uploader import upload_video, upload_thumbnail
    # Test mode is a local-only preview; it never initializes auth, sends review,
    # transfers bytes, or consumes the compilation/publication queue.
    if args.test:
        return {'status':'skipped','reason':'Test mode suppresses automatic publication'}
    try:
        with exclusive_lock(DATABASE_PATH.parent / 'publishing.lock',timeout=0):
            group=get_next_compilation()
            if not group:return {'status':'skipped','reason':'All compilation groups published'}
            reciter=args.reciter or DEFAULT_RECITER
            key=f"longform:{group['surah_start']}:{group['surah_end']}:{group.get('ayah_start')}:{group.get('ayah_end')}"
            job=reserve_job(key,surah=group['surah_start'],start_ayah=group.get('ayah_start') or 1,
                end_ayah=group.get('ayah_end') or VERSE_COUNTS[group['surah_end']],reciter_key=reciter,
                surah_end=group['surah_end'])
            if job.get('finalized'):
                return {'status':'skipped','reason':'Compilation job already finalized'}
            try:
                prior=read_upload_receipts(job['id']).get('youtube')
                if prior:
                    if not job.get('video_path') or not job.get('metadata_json') or not job.get('approval'):
                        raise RuntimeError('Existing receipt requires reconciliation; transfer will not repeat')
                    video_path=Path(job['video_path'])
                    metadata=json.loads(job['metadata_json'])
                    approval=json.loads(job['approval'])
                    thumbnail_path=approval.get('thumbnail_path')
                    manifest=load_media_manifest(video_path)
                    require_manifest_coverage(manifest,surah_start=job['surah'],start_ayah=job['start_ayah'],
                        surah_end=job['surah_end'] or job['surah'],end_ayah=job['end_ayah'],reciter_key=job['reciter_key'])
                else:
                    assert_transfer_retry_safe(job['id'],'youtube')
                    video_path=Path(OUTPUTS_DIR)/'jobs'/job['id']/'longform.mp4'
                    video_path.parent.mkdir(parents=True,exist_ok=True)
                    generated=generate_longform(surah_start=group['surah_start'],surah_end=group['surah_end'],
                        reciter_key=job['reciter_key'],ayah_start=group.get('ayah_start'),ayah_end=group.get('ayah_end'),
                        output_filename=str(video_path))
                    video_path=Path(generated['output_path'])
                    manifest=load_media_manifest(video_path)
                    require_manifest_coverage(manifest,surah_start=job['surah'],start_ayah=job['start_ayah'],
                        surah_end=job['surah_end'] or job['surah'],end_ayah=job['end_ayah'],reciter_key=job['reciter_key'])
                    metadata=dict(title=generated['recommended_title'],description=generated['description'],tags=generated['tags'])
                    thumbnail_path=generated.get('thumbnail_path')
                    mark_job(job['id'],'generated',video_path=str(video_path),metadata_json=json.dumps(metadata),manifest=manifest)
                    approval=require_automatic_approval(video_path,metadata,job_id=job['id'],privacy_status='unlisted',manifest=manifest,
                        thumbnail_path=thumbnail_path)
                receipt=upload_video(video_path,metadata,privacy_status='unlisted',automatic=True,job_id=job['id'],approval=approval,
                    thumbnail_path=thumbnail_path)
                if thumbnail_path and not upload_thumbnail(receipt['video_id'],Path(thumbnail_path),automatic=True,approval=approval):
                    raise RuntimeError('Reviewed custom thumbnail update failed; reconcile existing video')
                coverage=manifest['coverage']
                finalize_published_job(job['id'],dict(kind='longform',title=metadata['title'],
                    surah_start=coverage[0]['surah'],surah_end=coverage[-1]['surah'],
                    ayah_start=coverage[0]['start_ayah'],ayah_end=coverage[-1]['end_ayah'],
                    num_clips=len(manifest.get('verses',[])),source_clip_ids='[]',
                    duration_seconds=int(manifest['duration_seconds']),video_path=str(video_path),reciter_key=job['reciter_key']),receipt)
                return receipt
            except Exception as error:
                mark_job(job['id'],'failed',error_message=type(error).__name__)
                logger.error(f'Longform automatic job failed: {type(error).__name__}; receipts and media retained')
                return {'status':'failed','error':type(error).__name__,'job_id':job['id']}
    except LockTimeoutError:
        return {'status':'skipped','reason':'Another automatic job owns the publishing lock'}


def cmd_growth_engine(args):
    """Handler for the 'growth-engine' CLI command."""
    import json
    if args.ge_command is None:
        print("Usage: python main.py growth-engine [run|list]")
        return
        
    if args.ge_command == 'run':
        from core.growth_engine import execute_scheduled_slot
        slot = args.slot
        dry_run = args.dry_run
        
        print("\n" + "="*70)
        print(f"🚀 RUNNING DAILYQURAN GROWTH ENGINE SLOT")
        if slot:
            print(f"   Forced Slot: {slot}")
        if dry_run:
            print("   Mode: DRY RUN (No files created, no uploads)")
        print("="*70 + "\n")
        
        result = execute_scheduled_slot(slot_name=slot, dry_run=dry_run)
        
        print("\n" + "="*70)
        print("📊 EXECUTION RESULT:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("="*70 + "\n")

        # execute_scheduled_slot converts every exception into a result dict, so
        # without an explicit exit code a slot that posted nothing still reports
        # success to GitHub Actions. 'suppressed' and 'dry_run' are not failures.
        if result.get("status") in ('failed','partial','auth_error'):
            sys.exit(1)
        return result

    elif args.ge_command == 'list':
        from core.growth_engine import get_mecca_time, get_current_slot
        import datetime
        
        now = get_mecca_time()
        print("\n" + "="*70)
        print("📅 UPCOMING GROWTH ENGINE PUBLISHING CALENDAR (MECCA TIME / UTC+3)")
        print("="*70)
        print(f"Current Mecca Time: {now.strftime('%Y-%m-%d %I:%M %p (%A)')}\n")
        
        # Print slots for the next 7 days
        current = now.replace(minute=0, second=0, microsecond=0)
        printed = 0
        for offset_hours in range(24 * 7):
            future_time = current + datetime.timedelta(hours=offset_hours)
            
            slot_name=get_current_slot(future_time)
            previous_slot=get_current_slot(future_time-datetime.timedelta(hours=1))
            if slot_name and slot_name!=previous_slot:
                format_label={'morning_short':'standard_short','evening_short':'standard_short',
                              'friday_long':'full_surah_long','saturday_sleep':'unavailable (no validated loop builder)'}[slot_name]
                print(f"   - {future_time.strftime('%Y-%m-%d %I:%M %p (%a)')} | Slot: {slot_name:<15} | Format: {format_label}")
                printed += 1

        print("="*70 + "\n")
        
    elif args.ge_command == 'ingest-stats':
        from core.growth_engine import ingest_video_analytics
        res = ingest_video_analytics(
            video_id=args.video_id,
            views=args.views,
            likes=args.likes,
            comments=args.comments,
            retention_rate=args.retention,
            ctr=args.ctr,
            surah=args.surah,
            reciter_key=args.reciter,
            video_type=args.type
        )
        print(f"\n📊 Ingested analytics data: {json.dumps(res, indent=2)}")
        return res
        
    elif args.ge_command == 'auto-ingest-stats':
        from core.growth_engine import auto_ingest_youtube_public_metrics
        print("\n⚙️ Autonomously querying YouTube API for video performance stats...")
        res = auto_ingest_youtube_public_metrics()
        print(f"\n📊 Ingestion result: {json.dumps(res, indent=2)}")
        return res
        
    elif args.ge_command == 'run-feedback':
        from core.growth_engine import run_feedback_loop_analysis
        print("\n⚙️ Running Weekly Performance Feedback Loop Auto-Analysis...")
        res = run_feedback_loop_analysis()
        print(f"\n📊 Feedback Loop execution result: {json.dumps(res, indent=2, ensure_ascii=False)}")
        return res
        
    elif args.ge_command == 'start-ab-test':
        from core.growth_engine import trigger_ab_test_experiment
        res = trigger_ab_test_experiment(variable_type=args.variable)
        print(f"\nA/B experiment availability: {json.dumps(res, indent=2)}")
        return res
        
    elif args.ge_command == 'check-ab-tests':
        from core.growth_engine import evaluate_active_ab_tests
        print("\nChecking experiment availability...")
        res = evaluate_active_ab_tests()
        if res:
            print(f"\n🎉 A/B test results: {json.dumps(res, indent=2)}")
        else:
            print("\nNo active A/B tests completed yet.")
        return res


def main():
    from config.settings import SHORTS_RECITERS
    parser = argparse.ArgumentParser(
        description="Quran Reels Maker - Automated Quran Short Videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py generate                    # Generate next reel in sequence
  python main.py generate --surah 112        # Generate Surah Al-Ikhlas
  python main.py generate --verses 5         # Generate 5 verses per reel
  python main.py auto                        # Generate and upload
  python main.py auto --test                 # Generate locally; no review or upload
  python main.py status                      # Show progress
  python main.py setup-youtube               # Set up YouTube auth
  python main.py longform list               # Show upcoming longform queue
  python main.py longform auto               # Compile next longform and upload
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate a new reel')
    gen_parser.add_argument('--surah', type=int, help='Specific surah number (1-114)')
    gen_parser.add_argument('--start', type=int, help='Starting ayah')
    gen_parser.add_argument('--end', type=int, help='Ending ayah')
    gen_parser.add_argument('--verses', type=int, default=3, help='Number of verses per reel')
    gen_parser.add_argument('--reciter', choices=SHORTS_RECITERS, help='Shorts voice (default: next in rotation)')
    gen_parser.add_argument('--dry-run', action='store_true', help='Show what would be generated without doing it')
    
    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload a video to YouTube')
    upload_parser.add_argument('video_path', help='Path to the video file')
    upload_parser.add_argument('--title', help='Video title')
    upload_parser.add_argument('--description', help='Video description')
    upload_parser.add_argument('--tags', help='Comma-separated tags')
    upload_parser.add_argument('--privacy', choices=['public', 'private', 'unlisted'], default='public')
    upload_parser.add_argument('--history-id', type=int, help='History record ID to update')
    
    # Auto command
    auto_parser = subparsers.add_parser('auto', help='Generate and upload automatically')
    auto_parser.add_argument('--verses', type=int, default=3, help='Number of verses per reel')
    auto_parser.add_argument('--reciter', choices=SHORTS_RECITERS, help='Next voice in the Shorts rotation')
    auto_parser.add_argument('--test', action='store_true', help='Generate locally; never review or upload')
    auto_parser.add_argument('--surah', type=int, help='Specific surah (optional)')
    auto_parser.add_argument('--start', type=int, help='Starting ayah (optional)')
    auto_parser.add_argument('--end', type=int, help='Ending ayah (optional)')
    auto_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    
    # Batch command
    batch_parser = subparsers.add_parser('batch', help='Generate and upload multiple reels in one run')
    batch_parser.add_argument('--count', type=int, default=3, help='Number of videos to generate (default: 3)')
    batch_parser.add_argument('--delay', type=int, default=30, help='Seconds to wait between videos (default: 30)')
    batch_parser.add_argument('--verses', type=int, default=3, help='Verses per reel')
    batch_parser.add_argument('--reciter', choices=SHORTS_RECITERS, help='Next voice in the Shorts rotation')
    batch_parser.add_argument('--test', action='store_true', help='Generate locally; never review or upload')
    batch_parser.add_argument('--surah', type=int, help='Specific surah (optional)')
    batch_parser.add_argument('--start', type=int, help='Starting ayah (optional)')
    batch_parser.add_argument('--end', type=int, help='Ending ayah (optional)')
    batch_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')

    # Status command
    status_parser = subparsers.add_parser('status', help='Show current status')
    
    # Setup YouTube command
    setup_parser = subparsers.add_parser('setup-youtube', help='Set up YouTube authentication')
    setup_parser.add_argument('--test', action='store_true', help='Test authentication after setup')
    
    # Setup TikTok command
    setup_tt_parser = subparsers.add_parser('setup-tiktok', help='Set up TikTok authentication')
    
    # History command
    history_parser = subparsers.add_parser('history', help='Show reel history')
    history_parser.add_argument('--limit', type=int, default=10, help='Number of records to show')
    
    # TikTok command
    tiktok_parser = subparsers.add_parser('tiktok', help='Upload a video to TikTok')
    tiktok_parser.add_argument('video_path', help='Path to the video file')
    tiktok_parser.add_argument('--surah', type=int, help='Surah number (for non-standard filenames)')
    tiktok_parser.add_argument('--start', type=int, help='Start ayah (for non-standard filenames)')
    tiktok_parser.add_argument('--end', type=int, help='End ayah (for non-standard filenames)')
    tiktok_parser.add_argument('--reciter', type=str, help='Reciter name')
    
    # Set position command
    setpos_parser = subparsers.add_parser('set-position', help='Set current Quran position')
    setpos_parser.add_argument('surah', type=int, help='Surah number (1-114)')
    setpos_parser.add_argument('ayah', type=int, help='Ayah number')

    # Longform commands subparser
    lf_parser = subparsers.add_parser('longform', help='Long-form video compilation commands')
    lf_subparsers = lf_parser.add_subparsers(dest='lf_command', help='Longform subcommands')
    
    # Longform list
    lf_subparsers.add_parser('list', help='List all upcoming compilation groups')
    
    # Longform status
    lf_subparsers.add_parser('status', help='Show compilation history')
    
    # Longform compile
    compile_parser = lf_subparsers.add_parser('compile', help='Compile a specific surah range')
    compile_parser.add_argument('--surah', type=int, required=True, help='Surah number to compile')
    compile_parser.add_argument('--surah-end', type=int, help='Ending surah number (optional, for range)')
    compile_parser.add_argument('--start', type=int, help='Starting ayah (for split surahs)')
    compile_parser.add_argument('--end', type=int, help='Ending ayah (for split surahs)')
    compile_parser.add_argument('--reciter', type=str, help='Reciter key (defaults to default)')
    compile_parser.add_argument('--loop', type=int, default=1, help='Number of times to loop/repeat the sequence')
    
    # Longform auto
    auto_lf_parser = lf_subparsers.add_parser('auto', help='Automatically compile next group and upload')
    auto_lf_parser.add_argument('--reciter', type=str, help='Reciter key')
    auto_lf_parser.add_argument('--test', action='store_true', help='Skip automatic publishing in test mode')
    
    # Growth Engine commands subparser
    ge_parser = subparsers.add_parser('growth-engine', help='DailyQuran Growth Engine automation')
    ge_subparsers = ge_parser.add_subparsers(dest='ge_command', help='Growth Engine subcommands')
    
    # Growth Engine run
    run_parser = ge_subparsers.add_parser('run', help='Execute a scheduled growth engine slot')
    run_parser.add_argument('--slot', type=str, choices=['morning_short', 'evening_short', 'friday_long', 'saturday_sleep'], help='Force a specific slot')
    run_parser.add_argument('--dry-run', action='store_true', help='Execute all selection and scoring rules without actual rendering or uploading')
    
    # Growth Engine list
    ge_subparsers.add_parser('list', help='List the upcoming growth engine slot schedule')
    
    # Growth Engine ingest-stats
    ingest_parser = ge_subparsers.add_parser('ingest-stats', help='Ingest performance metrics for a video')
    ingest_parser.add_argument('--video-id', type=str, required=True, help='YouTube Video ID')
    ingest_parser.add_argument('--views', type=int, required=True, help='Views count')
    ingest_parser.add_argument('--likes', type=int, default=0, help='Likes count')
    ingest_parser.add_argument('--comments', type=int, default=0, help='Comments count')
    ingest_parser.add_argument('--retention', type=float, default=None, help='Measured retention rate (0.0 to 1.0), omitted when unavailable')
    ingest_parser.add_argument('--ctr', type=float, default=None, help='Measured click-through rate (0.0 to 1.0), omitted when unavailable')
    ingest_parser.add_argument('--surah', type=int, required=True, help='Surah number')
    ingest_parser.add_argument('--reciter', type=str, required=True, help='Reciter key')
    ingest_parser.add_argument('--type', type=str, choices=['short', 'long'], required=True, help='Video type')
    
    # Growth Engine run-feedback
    ge_subparsers.add_parser('run-feedback', help='Run weekly performance feedback loop auto-analysis')
    
    # Growth Engine start-ab-test
    ab_parser = ge_subparsers.add_parser('start-ab-test', help='Trigger an A/B test controlled experiment')
    ab_parser.add_argument('--variable', type=str, choices=['reciter', 'ayah_length', 'thumbnail_style'], required=True, help='Variable to test')
    
    # Growth Engine check-ab-tests
    ge_subparsers.add_parser('check-ab-tests', help='Evaluate active A/B tests and determine winners')
    
    # Growth Engine auto-ingest-stats
    ge_subparsers.add_parser('auto-ingest-stats', help='Autonomously query YouTube API and ingest stats')
    
    args = parser.parse_args()
    configure_logging(file_logging=not getattr(args,'dry_run',False))
    
    if args.command is None:
        parser.print_help()
        return
    
    # Route to appropriate command
    commands = {
        'generate': cmd_generate,
        'upload': cmd_upload,
        'auto': cmd_auto,
        'batch': cmd_batch,
        'status': cmd_status,
        'setup-youtube': cmd_setup_youtube,
        'setup-tiktok': cmd_setup_tiktok,
        'history': cmd_history,
        'set-position': cmd_set_position,
        'tiktok': cmd_tiktok,
        'longform': cmd_longform,
        'growth-engine': cmd_growth_engine
    }
    
    if args.command in commands:
        # Initialize database
        from database.models import init_database
        if not getattr(args,'dry_run',False):
            init_database()
        
        result=commands[args.command](args)
        if result is False or (isinstance(result,dict) and result.get('status') in ('failed','partial','auth_error')):
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
