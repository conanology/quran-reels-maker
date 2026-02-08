#!/usr/bin/env python3
"""
Quran Reels Maker - Automated Quran Short Videos for YouTube & TikTok

Usage:
    python main.py generate              Generate next reel in sequence
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
from config.settings import LOG_FILE, LOG_LEVEL, LOG_FORMAT, BASE_DIR

# Remove default handler and add custom ones
logger.remove()
logger.add(sys.stderr, level=LOG_LEVEL, format=LOG_FORMAT)
logger.add(LOG_FILE, level=LOG_LEVEL, format=LOG_FORMAT, rotation="10 MB")


def cmd_generate(args):
    """Generate a new Quran reel video."""
    from core.video_generator import generate_reel
    from core.verse_scheduler import (
        get_next_verses,
        advance_progress,
        record_reel_history,
        get_current_progress
    )
    from core.quran_api import get_full_text, get_surah_name
    from config.settings import DEFAULT_RECITER, RECITERS
    import random
    
    # Dynamic reciter selection
    if args.reciter:
        reciter = args.reciter
    else:
        # Pick a random reciter from the available list
        reciter = random.choice(list(RECITERS.keys()))
        logger.info(f"Randomly selected reciter: {reciter}")
    
    if args.surah:
        # Generate specific verses
        surah = args.surah
        start = args.start or 1
        end = args.end or (start + args.verses - 1)
        logger.info(f"Generating specified verses: Surah {surah}, Ayat {start}-{end}")
    else:
        # Check for Friday mode
        from core.verse_scheduler import is_friday, get_friday_verses
        friday_mode = os.getenv("FRIDAY_MODE_ENABLED", "true").lower() == "true"
        
        if friday_mode and is_friday():
            # It's Friday! Post Al-Kahf instead
            surah, start, end = get_friday_verses()
            logger.info(f"🕌 FRIDAY MODE: Surah Al-Kahf, Ayat {start}-{end}")
            print("📿 Friday Mode Activated - Surah Al-Kahf")
        else:
            # Get next verses from scheduler
            surah, start, end = get_next_verses(args.verses)
            logger.info(f"Auto-selected next verses: Surah {surah}, Ayat {start}-{end}")
    
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
        return None
    
    # Generate the reel
    try:
        video_path, actual_start, actual_end = generate_reel(
            surah=surah,
            start_ayah=start,
            end_ayah=end,
            reciter_key=reciter
        )
        
        # Record in history using ACTUAL range (in case it was extended)
        full_text = get_full_text(surah, actual_start, actual_end)
        history_id = record_reel_history(
            surah=surah,
            start_ayah=actual_start,
            end_ayah=actual_end,
            reciter_key=reciter,
            video_path=str(video_path)
        )
        
        # Advance progress (only for auto-selected verses) based on ACTUAL end
        if not args.surah:
            advance_progress(surah, actual_end)
        
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
        logger.error(f"Generation failed: {e}")
        print(f"\n❌ Error: {e}")
        return None


def cmd_upload(args):
    """Upload a video to YouTube."""
    from youtube.uploader import upload_video, upload_as_private, generate_metadata
    from youtube.auth import check_authentication_status
    from core.verse_scheduler import update_reel_youtube_id
    
    # Check authentication
    auth_status = check_authentication_status()
    if auth_status['status'] != 'valid':
        print(f"❌ {auth_status['message']}")
        return None
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"❌ Video file not found: {video_path}")
        return None
    
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
        logger.error(f"Upload failed: {e}")
        print(f"\n❌ Error: {e}")
        return None


def cmd_auto(args):
    """Automatically generate and upload a reel with optional approval."""
    print("\n🚀 AUTOMATIC MODE - Generate & Upload\n")
    
    from notifications.telegram_bot import (
        is_configured as telegram_configured,
        send_approval_request,
        wait_for_approval,
        notify_upload_success,
        notify_upload_failure,
        APPROVAL_REQUIRED
    )
    from youtube.uploader import upload_video, generate_metadata
    from youtube.auth import check_authentication_status
    from core.verse_scheduler import update_reel_youtube_id
    from core.video_generator import get_video_duration
    from config.settings import RECITERS
    import os
    
    max_attempts = 3  # Max regeneration attempts
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        
        if attempt > 1:
            print(f"\n🔄 Regeneration attempt {attempt}/{max_attempts}...")
        
        # Generate video
        gen_result = cmd_generate(args)
        
        if gen_result is None:
            print("❌ Generation failed, aborting")
            return None
        
        # Get video duration for approval message
        video_duration = get_video_duration(gen_result['video_path'])
        
        # Get reciter name for display
        reciter_info = RECITERS.get(gen_result['reciter'], {})
        reciter_name = reciter_info.get('name_ar', gen_result['reciter'])
        
        # === TELEGRAM APPROVAL WORKFLOW ===
        if telegram_configured() and APPROVAL_REQUIRED:
            from core.quran_api import get_surah_name
            surah_name = get_surah_name(gen_result['surah'], "ar")
            
            print("\n📱 Sending video to Telegram for approval...")
            
            message_id = send_approval_request(
                video_path=gen_result['video_path'],
                surah_name=surah_name,
                surah_num=gen_result['surah'],
                start_ayah=gen_result['start_ayah'],
                end_ayah=gen_result['end_ayah'],
                reciter_name=reciter_name,
                duration=video_duration
            )
            
            if message_id:
                print("✅ Video sent! Waiting for your approval...")
                print("   Reply 'approve', 'reject', or 'regenerate' on Telegram")
                
                approval = wait_for_approval()
                
                if approval == 'approved' or approval == 'skip':
                    print("✅ Approved! Proceeding with upload...")
                    break  # Exit loop and upload
                    
                elif approval == 'rejected':
                    print("❌ Rejected. Video deleted.")
                    # Delete the video
                    try:
                        os.remove(gen_result['video_path'])
                    except:
                        pass
                    return None
                    
                elif approval == 'regenerate':
                    print("🔄 Regenerating with new settings...")
                    # Delete current video
                    try:
                        os.remove(gen_result['video_path'])
                    except:
                        pass
                    continue  # Try again
                    
                elif approval == 'timeout':
                    print("⏰ Timeout. Video NOT uploaded (saved locally).")
                    return gen_result
            else:
                print("⚠️ Could not send to Telegram. Proceeding without approval...")
                break
        else:
            # No approval required, proceed directly
            break
    
    # === UPLOAD TO YOUTUBE ===
    auth_status = check_authentication_status()
    if auth_status['status'] != 'valid':
        print(f"\n⚠️ YouTube not configured: {auth_status['message']}")
        print("Video saved locally. Run 'python main.py setup-youtube' to enable uploads.")
        return gen_result
    
    # Generate metadata
    metadata = generate_metadata(
        surah=gen_result['surah'],
        start_ayah=gen_result['start_ayah'],
        end_ayah=gen_result['end_ayah'],
        reciter_key=gen_result['reciter'],
        full_text=gen_result['full_text']
    )
    
    print("\n" + "-"*50)
    print("📤 Uploading to YouTube...")
    print("-"*50)
    
    try:
        privacy = 'private' if args.test else 'public'
        result = upload_video(
            gen_result['video_path'],
            metadata,
            privacy_status=privacy
        )
        
        # Update history
        update_reel_youtube_id(gen_result['history_id'], result['video_id'])
        
        print(f"\n🎉 Complete! Video is now live!")
        print(f"🔗 {result['url']}")
        
        # Notify on Telegram
        if telegram_configured():
            notify_upload_success(result['url'])
        
        return result
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        print(f"\n⚠️ Upload failed: {e}")
        print(f"Video saved locally: {gen_result['video_path']}")
        
        # Notify failure on Telegram
        if telegram_configured():
            notify_upload_failure(str(e))
        
        return gen_result


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
    success = sum(1 for r in results if r and r.get('url'))
    failed = sum(1 for r in results if r is None)
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


def cmd_status(args):
    """Show current progress and statistics."""
    from core.verse_scheduler import get_current_progress, get_statistics, get_reel_history
    from database.models import init_database
    
    init_database()
    
    progress = get_current_progress()
    stats = get_statistics()
    
    print("\n" + "="*50)
    print("📊 QURAN REELS MAKER - STATUS")
    print("="*50)
    
    print(f"\n📍 Current Position:")
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
        print("\nTo configure TikTok:")
        print("1. Log into TikTok in your browser")
        print("2. Open DevTools (F12) → Application → Cookies → tiktok.com")
        print("3. Copy the 'sessionid' value")
        print("4. Add to .env: TIKTOK_SESSION_ID=your_session_id")
        print("5. Set TIKTOK_ENABLED=true")
        return
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"\n❌ Video not found: {video_path}")
        return
    
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
        if result.get('status') == 'uploaded':
            print(f"\n✅ Successfully uploaded to TikTok!")
        elif result.get('status') == 'metadata_saved':
            print(f"\n📄 Metadata saved for manual upload: {result.get('meta_path')}")
        else:
            print(f"\n❌ Upload failed: {result.get('error', 'Unknown error')}")
    else:
        print(f"\n❌ Upload failed - check logs for details")


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
        print(f"\n❌ Authentication failed: {e}")
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


def main():
    parser = argparse.ArgumentParser(
        description="Quran Reels Maker - Automated Quran Short Videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py generate                    # Generate next reel in sequence
  python main.py generate --surah 112        # Generate Surah Al-Ikhlas
  python main.py generate --verses 5         # Generate 5 verses per reel
  python main.py auto                        # Generate and upload
  python main.py auto --test                 # Generate and upload as private
  python main.py status                      # Show progress
  python main.py setup-youtube               # Set up YouTube auth
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate a new reel')
    gen_parser.add_argument('--surah', type=int, help='Specific surah number (1-114)')
    gen_parser.add_argument('--start', type=int, help='Starting ayah')
    gen_parser.add_argument('--end', type=int, help='Ending ayah')
    gen_parser.add_argument('--verses', type=int, default=3, help='Number of verses per reel')
    gen_parser.add_argument('--reciter', type=str, help='Reciter key (e.g., alafasy, sudais)')
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
    auto_parser.add_argument('--reciter', type=str, help='Reciter key')
    auto_parser.add_argument('--test', action='store_true', help='Upload as private for testing')
    auto_parser.add_argument('--surah', type=int, help='Specific surah (optional)')
    auto_parser.add_argument('--start', type=int, help='Starting ayah (optional)')
    auto_parser.add_argument('--end', type=int, help='Ending ayah (optional)')
    auto_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    
    # Batch command
    batch_parser = subparsers.add_parser('batch', help='Generate and upload multiple reels in one run')
    batch_parser.add_argument('--count', type=int, default=3, help='Number of videos to generate (default: 3)')
    batch_parser.add_argument('--delay', type=int, default=30, help='Seconds to wait between videos (default: 30)')
    batch_parser.add_argument('--verses', type=int, default=3, help='Verses per reel')
    batch_parser.add_argument('--reciter', type=str, help='Reciter key')
    batch_parser.add_argument('--test', action='store_true', help='Upload as private for testing')
    batch_parser.add_argument('--surah', type=int, help='Specific surah (optional)')
    batch_parser.add_argument('--start', type=int, help='Starting ayah (optional)')
    batch_parser.add_argument('--end', type=int, help='Ending ayah (optional)')
    batch_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')

    # Status command
    status_parser = subparsers.add_parser('status', help='Show current status')
    
    # Setup YouTube command
    setup_parser = subparsers.add_parser('setup-youtube', help='Set up YouTube authentication')
    setup_parser.add_argument('--test', action='store_true', help='Test authentication after setup')
    
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
    
    args = parser.parse_args()
    
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
        'history': cmd_history,
        'set-position': cmd_set_position,
        'tiktok': cmd_tiktok
    }
    
    if args.command in commands:
        # Initialize database
        from database.models import init_database
        init_database()
        
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
