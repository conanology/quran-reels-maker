import sys
import os
import subprocess
import json

sys.path.append(os.path.abspath("backend"))
import compiler

def create_dummy_video(filename, duration):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", str(duration),
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-r", "30", "-ar", "44100", "-ac", "2",
        filename
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def main():
    print("Preparing dummy downloads...")
    downloads_dir = r"C:\Users\acona\.gemini\antigravity\scratch\quran_compiler\data\downloads"
    
    clips_info = [
        {"id": "c1", "duration": 4, "reciter": "القارئ ياسر الدوسري", "surah": "سورة الملك"},
        {"id": "c2", "duration": 5, "reciter": "القارئ ماهر المعيقلي", "surah": "سورة الرحمن"},
        {"id": "c3", "duration": 6, "reciter": "القارئ عبد الباسط عبد الصمد", "surah": "سورة يس"}
    ]
    
    clips = []
    for info in clips_info:
        path = os.path.join(downloads_dir, f"{info['id']}.mp4")
        if not os.path.exists(path):
            print(f"Creating {path} ({info['duration']}s)...")
            create_dummy_video(path, info['duration'])
        clips.append({
            "video_id": info['id'],
            "reciter_name": info['reciter'],
            "surah_name": info['surah']
        })
        
    print("\nRunning compiler.compile_longform...")
    try:
        metadata = compiler.compile_longform(
            clips,
            output_filename="test_compilation_output.mp4",
            transition_duration=1.0,
            progress_callback=lambda curr, tot, msg: print(f"Progress [{curr}/{tot}]: {msg}")
        )
        print("\nSUCCESS! Compilation completed.")
        print(f"Output Video Path: {metadata['output_path']}")
        print(f"Total Duration: {metadata['duration_formatted']} ({metadata['duration_seconds']}s)")
        print("\nChapters generated:")
        for ch in metadata['chapters']:
            print(f"  {ch['timestamp']} - {ch['title']}")
            
        print("\nGenerated SEO Description preview:")
        print("-----------------------------------")
        print(metadata['description'])
        print("-----------------------------------")
        
        # Verify final files exist
        out_v = metadata['output_path']
        out_j = out_v + ".json"
        
        if os.path.exists(out_v) and os.path.getsize(out_v) > 0:
            print(f"Output MP4 verified: {os.path.getsize(out_v)} bytes.")
        else:
            print("ERROR: Output MP4 missing or empty.")
            
        if os.path.exists(out_j):
            print(f"Output JSON Metadata verified.")
        else:
            print("ERROR: Output JSON Metadata missing.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Compilation failed: {e}")

if __name__ == "__main__":
    main()
