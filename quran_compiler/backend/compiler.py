import os
import subprocess
import json
import shutil

# Folder setup
BASE_DIR = r"C:\Users\acona\.gemini\antigravity\scratch\quran_compiler"
TEMP_DIR = os.path.join(BASE_DIR, "data", "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "output")
FONTS_DIR = os.path.join(BASE_DIR, "backend", "assets", "fonts")
FONT_PATH = os.path.join(FONTS_DIR, "Amiri-Regular.ttf")

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_video_duration(video_path):
    """
    Retrieves the duration of a video file using ffprobe.
    """
    cmd = [
        "ffprobe", "-v", "error", 
        "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        video_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"Error getting duration for {video_path}: {e}")
        return 0.0

def format_timestamp(seconds):
    """
    Formats seconds into MM:SS or HH:MM:SS.
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"

def process_single_clip(input_path, output_path, reciter_name, transition_duration=1.5):
    """
    Processes a single 9:16 video:
    - Creates a 16:9 1920x1080 canvas.
    - Scales and blurs the background.
    - Scales and overlays the original video in the center.
    - Adds Arabic reciter text overlay in the bottom third.
    - Applies fade-in and fade-out to video and audio.
    - Standardizes format to 30fps, 44100Hz stereo audio.
    """
    duration = get_video_duration(input_path)
    if duration == 0:
        raise ValueError(f"Could not retrieve duration for {input_path}")
    
    # Write reciter name to a temporary UTF-8 text file to avoid encoding issues with FFmpeg CLI arguments
    text_file_path = output_path + ".txt"
    with open(text_file_path, "w", encoding="utf-8") as f:
        f.write(reciter_name)
    
    # Convert absolute paths to relative paths or format properly for FFmpeg drawtext on Windows.
    # To bypass escaping bugs, we copy the text file to the current execution directory or escape properly.
    # In FFmpeg drawtext on Windows, we escape the path colons, e.g. "C\:/path/to/file.txt".
    # Or, we can just use relative path since we run it in a specific working directory.
    # Let's write the text file in the same directory as the script, and pass relative paths.
    rel_font_path = "backend/assets/fonts/Amiri-Regular.ttf"
    # Fallback to local copy if run from scratch
    if not os.path.exists(FONT_PATH):
        # If font doesn't exist, we will use default Arial/system font (but Amiri is downloaded during setup)
        font_filter = "fontcolor=white:fontsize=54"
    else:
        # Escape colons and backslashes in absolute path for FFmpeg filter on Windows
        escaped_font_path = FONT_PATH.replace("\\", "/").replace(":", "\\:")
        escaped_text_path = text_file_path.replace("\\", "/").replace(":", "\\:")
        font_filter = f"fontfile='{escaped_font_path}':textfile='{escaped_text_path}'"

    fade_in_start = 0
    fade_out_start = max(0.0, duration - transition_duration)
    
    # Build filter complex
    # 1. Background: Scale to 1920 width, crop center 1920x1080, apply boxblur (40px, power 3)
    # 2. Foreground: Scale height to 1080, width proportionally, and center overlay
    # 3. Text: Overlay reciter name
    # 4. Fades: Apply fade-in and fade-out on both video and audio
    filter_complex = (
        f"[0:v]scale=1920:-1,crop=1920:1080:(in_w-1920)/2:(in_h-1080)/2,boxblur=40:5[bg]; "
        f"[0:v]scale=-2:1080[fg]; "
        f"[bg][fg]overlay=(W-w)/2:0[ov]; "
        f"[ov]drawtext={font_filter}:fontcolor=white:fontsize=50:borderw=3:bordercolor=black@0.8:x=(w-text_w)/2:y=h-160,"
        f"fade=t=in:st={fade_in_start}:d={transition_duration},"
        f"fade=t=out:st={fade_out_start}:d={transition_duration}[v]; "
        f"[0:a]afade=t=in:st={fade_in_start}:d={transition_duration},"
        f"afade=t=out:st={fade_out_start}:d={transition_duration}[a]"
    )

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-r", "30", "-ar", "44100", "-ac", "2",
        output_path
    ]
    
    print(f"Executing FFmpeg for {input_path}...")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Clean up the text file
    if os.path.exists(text_file_path):
        try:
            os.remove(text_file_path)
        except Exception:
            pass

    if result.returncode != 0:
        print(f"FFmpeg Error output:\n{result.stderr}")
        raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}")
        
    return duration

def compile_longform(clips, output_filename="final_compilation.mp4", transition_duration=1.5, progress_callback=None):
    """
    Compiles a list of clips into a single long-form video.
    clips is a list of dicts: [{'video_id': '...', 'reciter_name': '...', 'surah_name': '...'}]
    
    Returns a dict containing output path and chapter list metadata.
    """
    # Clean temp folder
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    processed_paths = []
    chapters = []
    accumulated_time = 0.0
    
    total_clips = len(clips)
    
    for idx, clip in enumerate(clips):
        video_id = clip['video_id']
        reciter_name = clip['reciter_name']
        surah_name = clip['surah_name']
        
        raw_path = os.path.join(BASE_DIR, "data", "downloads", f"{video_id}.mp4")
        if not os.path.exists(raw_path):
            raise FileNotFoundError(f"Raw video file not found: {raw_path}")
            
        temp_out_path = os.path.join(TEMP_DIR, f"processed_{idx:03d}.mp4")
        
        if progress_callback:
            progress_callback(idx, total_clips, f"Processing clip {idx+1}/{total_clips} ({surah_name})...")
            
        # Process individual clip with blur, overlays, and fades
        duration = process_single_clip(raw_path, temp_out_path, reciter_name, transition_duration)
        
        processed_paths.append(temp_out_path)
        
        # Chapter title front-loads reciter name and surah name
        chapter_title = f"{surah_name} - {reciter_name}"
        chapters.append({
            "timestamp": format_timestamp(accumulated_time),
            "seconds": accumulated_time,
            "title": chapter_title
        })
        
        accumulated_time += duration
        
    # Concatenate using FFmpeg concat demuxer
    concat_txt_path = os.path.join(TEMP_DIR, "concat_list.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for path in processed_paths:
            # Escape path for FFmpeg concat file (Windows format requires double backslashes or forward slashes)
            escaped_path = path.replace("\\", "/")
            f.write(f"file '{escaped_path}'\n")
            
    final_output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    if progress_callback:
        progress_callback(total_clips, total_clips, "Concatenating final video...")
        
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt_path, "-c", "copy",
        final_output_path
    ]
    
    result = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"FFmpeg Concat Error:\n{result.stderr}")
        raise RuntimeError(f"FFmpeg concat failed with exit code {result.returncode}")
        
    # Generate metadata description
    description_lines = [
        "📖 Beautiful Quran Recitations Compilation",
        "",
        "Timestamps / Chapters:",
    ]
    for ch in chapters:
        description_lines.append(f"{ch['timestamp']} - {ch['title']}")
        
    description_lines.extend([
        "",
        "Category: Education (27)",
        "Aspect Ratio: 16:9 (1920x1080) optimized for long-form viewing.",
        "Transitions: 3-second clean black fade handoffs between reciters.",
        "Backgrounds: Premium blurred vertical frames.",
        "",
        "If you enjoyed this recitation, please like, subscribe, and share for more spiritual content."
    ])
    
    metadata = {
        "output_path": final_output_path,
        "duration_seconds": accumulated_time,
        "duration_formatted": format_timestamp(accumulated_time),
        "chapters": chapters,
        "description": "\n".join(description_lines),
        "recommended_title": f"{clips[0]['surah_name']} to {clips[-1]['surah_name']} | Beautiful Quran Recitations Compilation"
    }
    
    # Save metadata as JSON next to the output video
    meta_path = final_output_path + ".json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
        
    # Clean temp folder
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    return metadata

if __name__ == "__main__":
    # Test run
    # process_single_clip("input.mp4", "output.mp4", "القارئ ياسر الدوسري")
    pass
