import os
import sys
import json
import threading

# Dynamically add the current directory (backend) to the Python path to prevent import errors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List

# Import our custom modules
import downloader
import compiler

# Folder setup
BASE_DIR = r"C:\Users\acona\.gemini\antigravity\scratch\quran_compiler"
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_FILE = os.path.join(DATA_DIR, "shorts_cache.json")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

app = FastAPI(title="YouTube Quran Shorts Compiler")

# Global Progress State
PROGRESS = {
    "downloader": {
        "status": "idle",  # "idle", "fetching", "downloading", "completed", "failed"
        "current": 0,
        "total": 0,
        "message": ""
    },
    "compiler": {
        "status": "idle",  # "idle", "compiling", "completed", "failed"
        "current": 0,
        "total": 0,
        "message": "",
        "result": None
    }
}

class FetchRequest(BaseModel):
    channel_url: str

class ClipItem(BaseModel):
    video_id: str
    reciter_name: str
    surah_name: str

class CompileRequest(BaseModel):
    clips: List[ClipItem]
    transition_duration: float = 1.5
    output_filename: str = "final_compilation.mp4"

# Endpoints

@app.get("/api/status")
def get_status():
    """Returns the current downloader and compiler progress."""
    return PROGRESS

@app.get("/api/shorts")
def get_shorts():
    """Retrieves cached shorts metadata."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read cache: {e}")
    return []

@app.post("/api/fetch-shorts")
def fetch_shorts(request: FetchRequest, background_tasks: BackgroundTasks):
    """Triggers metadata fetching in the background."""
    if PROGRESS["downloader"]["status"] == "fetching":
        return {"status": "already fetching"}

    PROGRESS["downloader"]["status"] = "fetching"
    PROGRESS["downloader"]["message"] = "Fetching channel metadata..."
    
    def do_fetch():
        try:
            shorts_list = downloader.fetch_shorts_metadata(request.channel_url)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(shorts_list, f, indent=2, ensure_ascii=False)
            
            PROGRESS["downloader"]["status"] = "completed"
            PROGRESS["downloader"]["message"] = f"Successfully fetched {len(shorts_list)} shorts."
        except Exception as e:
            PROGRESS["downloader"]["status"] = "failed"
            PROGRESS["downloader"]["message"] = f"Error: {str(e)}"

    background_tasks.add_task(do_fetch)
    return {"status": "started"}

def download_task_runner(clips: List[ClipItem]):
    """Background download runner."""
    PROGRESS["downloader"]["status"] = "downloading"
    PROGRESS["downloader"]["total"] = len(clips)
    PROGRESS["downloader"]["current"] = 0
    
    try:
        for idx, clip in enumerate(clips):
            PROGRESS["downloader"]["current"] = idx + 1
            PROGRESS["downloader"]["message"] = f"Downloading short {idx+1}/{len(clips)}: {clip.surah_name}..."
            downloader.download_video(clip.video_id)
            
        PROGRESS["downloader"]["status"] = "completed"
        PROGRESS["downloader"]["message"] = "All downloads completed successfully."
    except Exception as e:
        PROGRESS["downloader"]["status"] = "failed"
        PROGRESS["downloader"]["message"] = f"Download error: {str(e)}"

@app.post("/api/download-selected")
def download_selected(clips: List[ClipItem], background_tasks: BackgroundTasks):
    """Downloads selected shorts in a background thread."""
    if PROGRESS["downloader"]["status"] in ["fetching", "downloading"]:
        return {"status": "busy"}

    background_tasks.add_task(download_task_runner, clips)
    return {"status": "started"}

def compile_task_runner(clips: List[ClipItem], transition_duration: float, output_filename: str):
    """Background compilation runner."""
    PROGRESS["compiler"]["status"] = "compiling"
    PROGRESS["compiler"]["total"] = len(clips)
    PROGRESS["compiler"]["current"] = 0
    PROGRESS["compiler"]["message"] = "Starting compilation process..."
    PROGRESS["compiler"]["result"] = None
    
    def compile_progress_callback(current, total, message):
        PROGRESS["compiler"]["current"] = current
        PROGRESS["compiler"]["total"] = total
        PROGRESS["compiler"]["message"] = message

    try:
        # Convert Pydantic ClipItem models to dictionaries for the compiler
        clips_dict = [
            {
                "video_id": item.video_id,
                "reciter_name": item.reciter_name,
                "surah_name": item.surah_name
            } for item in clips
        ]
        
        # Compile
        result = compiler.compile_longform(
            clips_dict,
            output_filename=output_filename,
            transition_duration=transition_duration,
            progress_callback=compile_progress_callback
        )
        
        PROGRESS["compiler"]["status"] = "completed"
        PROGRESS["compiler"]["message"] = "Compilation completed successfully!"
        PROGRESS["compiler"]["result"] = result
    except Exception as e:
        PROGRESS["compiler"]["status"] = "failed"
        PROGRESS["compiler"]["message"] = f"Compilation failed: {str(e)}"

@app.post("/api/compile")
def start_compile(request: CompileRequest, background_tasks: BackgroundTasks):
    """Triggers the video compilation pipeline in the background."""
    if PROGRESS["compiler"]["status"] == "compiling":
        return {"status": "already compiling"}

    background_tasks.add_task(
        compile_task_runner,
        request.clips,
        request.transition_duration,
        request.output_filename
    )
    return {"status": "started"}

# Serve Frontend

# Mount downloaded output directory for playing/viewing compilation videos
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")

# Route for frontend files
@app.get("/")
def read_root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Mount frontend directory for styles, JS
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
