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
        except Exception as e:
            logger.error(f"Manual compilation failed: {e}")
            print(f"\n❌ Error: {e}")
            
    elif args.lf_command == 'auto':
        from longform.scheduler import get_next_compilation, record_compilation, update_compilation_youtube
        from longform.compiler import generate_longform
        from longform.visual_randomizer import generate_compilation_style
        from youtube.uploader import upload_video
        from youtube.auth import check_authentication_status
        from config.settings import DEFAULT_RECITER, RECITERS, VERSE_COUNTS
        import os
        import random
        
        # Check authentication first
        auth_status = check_authentication_status()
        if auth_status['status'] != 'valid':
            print(f"❌ YouTube authentication is not valid: {auth_status['message']}")
            print("Please run 'python main.py setup-youtube' first.")
            return
            
        # 1. Get next compilation
        group = get_next_compilation()
        if not group:
            print("\n🎉 All longform videos have been compiled!")
            return
            
        reciter = args.reciter
        if not reciter:
            # Pick a random reciter from the available list to make it diverse
            reciter = random.choice(list(RECITERS.keys()))
            logger.info(f"Randomly selected reciter for long-form: {reciter}")
            
        # Determine total ayahs to compile in this group
        total_ayahs = 0
        for s in range(group["surah_start"], group["surah_end"] + 1):
            if s == group["surah_start"] and group["ayah_start"] is not None:
                sa = group["ayah_start"]
            else:
                sa = 1
            if s == group["surah_end"] and group["ayah_end"] is not None:
                ea = group["ayah_end"]
            else:
                ea = VERSE_COUNTS[s]
            total_ayahs += ea - sa + 1
            
        styles = generate_compilation_style(total_ayahs)
        
        # 2. Render
        print(f"\n🚀 Rendering: {group['title']}")
        print(f"   Reciter: {reciter}")
        print(f"   Est. Duration: {group['estimated_duration']/60:.1f} mins\n")
        
        try:
            metadata = generate_longform(
                surah_start=group["surah_start"],
                surah_end=group["surah_end"],
                reciter_key=reciter,
                compilation_styles=styles,
                ayah_start=group["ayah_start"],
                ayah_end=group["ayah_end"]
            )
            
            bg_id = None
            
            # 3. Record in DB
            history_id = record_compilation(
                title=metadata["recommended_title"],
                surah_start=group["surah_start"],
                surah_end=group["surah_end"],
                num_clips=total_ayahs,
                source_clip_ids=[],
                duration_seconds=metadata["duration_seconds"],
                video_path=metadata["output_path"],
                background_video_id=bg_id,
                ayah_start=group["ayah_start"],
                ayah_end=group["ayah_end"]
            )
            
            # 4. Upload to YouTube as Unlisted
            privacy = 'private' if args.test else 'unlisted'
            
            youtube_meta = {
                'title': metadata["recommended_title"],
                'description': metadata["description"],
                'tags': metadata["tags"]
            }
            
            print(f"\n📤 Uploading to YouTube as {privacy.upper()}...")
            video_path = Path(metadata["output_path"])
            
            upload_result = upload_video(
                video_path,
                youtube_meta,
                privacy_status=privacy
            )
            
            # 5. Upload custom thumbnail if generated
            thumbnail_path_str = metadata.get("thumbnail_path")
            if thumbnail_path_str:
                try:
                    from youtube.uploader import upload_thumbnail
                    upload_thumbnail(upload_result['video_id'], Path(thumbnail_path_str))
                except Exception as e:
                    logger.error(f"Failed to upload custom thumbnail: {e}")
            
            # 6. Update DB record with YouTube ID
            update_compilation_youtube(history_id, upload_result['video_id'])
            
            print(f"\n🎉 Successfully completed!")
            print(f"   YouTube URL: {upload_result['url']}")
            
        except Exception as e:
            logger.error(f"Auto long-form flow failed: {e}")
            print(f"\n❌ Flow failed: {e}")


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
        
    elif args.ge_command == 'list':
        from core.growth_engine import get_mecca_time, get_slot_format
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
            
            # Simple slot checks matching get_current_slot logic
            weekday = future_time.weekday()
            hour = future_time.hour
            slot_name = None
            
            if weekday == 4 and 20 <= hour <= 23:
                if hour == 21:
                    slot_name = "friday_long"
            elif weekday == 5 and 21 <= hour <= 23:
                if hour == 22:
                    slot_name = "saturday_sleep"
            elif hour == 5:
                slot_name = "morning_short"
            elif hour == 20:
                slot_name = "evening_short"
                
            if slot_name:
                fmt = get_slot_format(slot_name)
                print(f"   - {future_time.strftime('%Y-%m-%d %I:%M %p (%a)')} | Slot: {slot_name:<15} | Format: {fmt}")
                printed += 1
                
        print("="*70 + "\n")


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
    auto_lf_parser.add_argument('--test', action='store_true', help='Upload as private/test')
    
    # Growth Engine commands subparser
    ge_parser = subparsers.add_parser('growth-engine', help='DailyQuran Growth Engine automation')
    ge_subparsers = ge_parser.add_subparsers(dest='ge_command', help='Growth Engine subcommands')
    
    # Growth Engine run
    run_parser = ge_subparsers.add_parser('run', help='Execute a scheduled growth engine slot')
    run_parser.add_argument('--slot', type=str, choices=['morning_short', 'evening_short', 'friday_long', 'saturday_sleep'], help='Force a specific slot')
    run_parser.add_argument('--dry-run', action='store_true', help='Execute all selection and scoring rules without actual rendering or uploading')
    
    # Growth Engine list
    ge_subparsers.add_parser('list', help='List the upcoming growth engine slot schedule')
    
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
        'tiktok': cmd_tiktok,
        'longform': cmd_longform,
        'growth-engine': cmd_growth_engine
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
