import sys
import os
import subprocess

# Add backend to path
sys.path.append(os.path.abspath("backend"))
import compiler

def main():
    print("Step 1: Creating dummy vertical video...")
    dummy_input = "test_vertical.mp4"
    dummy_output = "test_processed.mp4"
    
    # Clean up old files
    for f in [dummy_input, dummy_output]:
        if os.path.exists(f):
            os.remove(f)
            
    # Generate 5 second dummy video: 1080x1920, 30fps, with sine wave audio
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "5",
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-r", "30", "-ar", "44100", "-ac", "2",
        dummy_input
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Created dummy video: {dummy_input}")
    except Exception as e:
        print(f"Failed to create dummy video: {e}")
        return
        
    print("\nStep 2: Processing dummy video using compiler filter graph...")
    try:
        duration = compiler.process_single_clip(
            dummy_input,
            dummy_output,
            reciter_name="القارئ ياسر الدوسري",
            transition_duration=1.0
        )
        print(f"Compilation succeeded! Duration: {duration} seconds.")
        print(f"Output saved to: {dummy_output}")
        
        # Verify output exists and check its size
        if os.path.exists(dummy_output) and os.path.getsize(dummy_output) > 0:
            print("SUCCESS: Output video file verified.")
        else:
            print("FAILURE: Output video file is empty or missing.")
            
    except Exception as e:
        print(f"Failed during compilation: {e}")
        
if __name__ == "__main__":
    main()
