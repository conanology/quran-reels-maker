// Application State
let shortsData = [];
let statusPollInterval = null;

// DOM Elements
const channelInput = document.getElementById('channel-input');
const btnFetch = document.getElementById('btn-fetch');
const fetchSpinner = document.getElementById('fetch-spinner');
const fetchProgressMsg = document.getElementById('fetch-progress-msg');

const transitionInput = document.getElementById('transition-input');
const transitionValue = document.getElementById('transition-value');
const filenameInput = document.getElementById('filename-input');
const btnCompile = document.getElementById('btn-compile');

const selectedCount = document.getElementById('selected-count');
const estDuration = document.getElementById('est-duration');

const emptyState = document.getElementById('empty-state');
const workspaceContent = document.getElementById('workspace-content');
const shortsGrid = document.getElementById('shorts-grid');

const progressPanel = document.getElementById('progress-panel');
const progressTitle = document.getElementById('progress-title');
const progressPercent = document.getElementById('progress-percent');
const progressBarFill = document.getElementById('progress-bar-fill');
const progressStatusText = document.getElementById('progress-status-text');
const consoleLogs = document.getElementById('console-logs');

const outputPanel = document.getElementById('output-panel');
const outputVideoPlayer = document.getElementById('output-video-player');
const outputFilePath = document.getElementById('output-file-path');
const outputTitle = document.getElementById('output-title');
const outputDescription = document.getElementById('output-description');

const globalStatusDot = document.getElementById('global-status-dot');
const globalStatusText = document.getElementById('global-status-text');

// Init
window.addEventListener('DOMContentLoaded', () => {
    // Sync slider display
    transitionInput.addEventListener('input', (e) => {
        transitionValue.textContent = `${e.target.value}s`;
    });

    // Check if we already have cached shorts
    loadCachedShorts();

    // Event listeners
    btnFetch.addEventListener('click', fetchChannelShorts);
    btnCompile.addEventListener('click', startCompilationProcess);
    document.getElementById('btn-sort-quranic').addEventListener('click', sortShortsQuranicAndRender);
    document.getElementById('btn-select-all').addEventListener('click', () => toggleAllClips(true));
    document.getElementById('btn-deselect-all').addEventListener('click', () => toggleAllClips(false));
});

// Load cache on load
async function loadCachedShorts() {
    try {
        const res = await fetch('/api/shorts');
        if (res.ok) {
            const data = await res.json();
            if (data && data.length > 0) {
                shortsData = data;
                sortShortsQuranic(); // Automatically sort Quranic order on load
                renderShortsGrid();
            }
        }
    } catch (e) {
        console.error("Error loading cached shorts:", e);
    }
}

// Fetch Channel Shorts
async function fetchChannelShorts() {
    const channel = channelInput.value.strip ? channelInput.value.strip() : channelInput.value.trim();
    if (!channel) {
        alert("Please enter a YouTube channel URL or handle.");
        return;
    }

    // UI Updates
    btnFetch.disabled = true;
    fetchSpinner.classList.remove('hidden');
    fetchProgressMsg.textContent = "Requesting YouTube metadata scan...";
    setGlobalStatus('fetching', 'Fetching Channel Shorts...');

    try {
        const res = await fetch('/api/fetch-shorts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_url: channel })
        });
        
        if (res.ok) {
            // Start polling status
            startPollingStatus('fetch');
        } else {
            const error = await res.json();
            throw new Error(error.detail || "Server error");
        }
    } catch (e) {
        btnFetch.disabled = false;
        fetchSpinner.classList.add('hidden');
        fetchProgressMsg.textContent = `Error: ${e.message}`;
        setGlobalStatus('failed', 'Fetch failed');
    }
}

// Set global status badge
function setGlobalStatus(status, text) {
    globalStatusDot.className = `status-indicator-dot ${status}`;
    globalStatusText.textContent = text;
}

// Polling status from FastAPI
function startPollingStatus(mode) {
    if (statusPollInterval) clearInterval(statusPollInterval);

    statusPollInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/status');
            if (!res.ok) return;
            const progress = await res.json();

            if (mode === 'fetch') {
                const downloader = progress.downloader;
                fetchProgressMsg.textContent = downloader.message;
                
                if (downloader.status === 'completed') {
                    clearInterval(statusPollInterval);
                    btnFetch.disabled = false;
                    fetchSpinner.classList.add('hidden');
                    fetchProgressMsg.textContent = downloader.message;
                    setGlobalStatus('completed', 'Shorts fetched successfully');
                    
                    // Reload and render
                    await loadCachedShorts();
                } else if (downloader.status === 'failed') {
                    clearInterval(statusPollInterval);
                    btnFetch.disabled = false;
                    fetchSpinner.classList.add('hidden');
                    fetchProgressMsg.textContent = downloader.message;
                    setGlobalStatus('failed', 'Fetch failed');
                }
            } else if (mode === 'compile') {
                const downloader = progress.downloader;
                const compiler = progress.compiler;
                
                if (downloader.status === 'downloading') {
                    setGlobalStatus('downloading', 'Downloading clips...');
                    progressTitle.textContent = "Downloading Clip Assets...";
                    
                    const pct = Math.round((downloader.current / downloader.total) * 100);
                    progressPercent.textContent = `${pct}%`;
                    progressBarFill.style.width = `${pct}%`;
                    progressStatusText.textContent = downloader.message;
                    appendLog(`[Download] ${downloader.message}`);
                } 
                else if (compiler.status === 'compiling') {
                    setGlobalStatus('compiling', 'Compiling long-form video...');
                    progressTitle.textContent = "Compiling Long-Form Video...";
                    
                    // Concat takes final step, so total is length + 1
                    const total = compiler.total || 1;
                    const pct = Math.round((compiler.current / total) * 100);
                    progressPercent.textContent = `${pct}%`;
                    progressBarFill.style.width = `${pct}%`;
                    progressStatusText.textContent = compiler.message;
                    appendLog(`[Compile] ${compiler.message}`);
                }
                else if (compiler.status === 'completed') {
                    clearInterval(statusPollInterval);
                    setGlobalStatus('completed', 'Video generation ready');
                    
                    progressPercent.textContent = `100%`;
                    progressBarFill.style.width = `100%`;
                    progressStatusText.textContent = "Done!";
                    
                    // Show Output
                    showOutputPanel(compiler.result);
                }
                else if (compiler.status === 'failed') {
                    clearInterval(statusPollInterval);
                    setGlobalStatus('failed', 'Compilation failed');
                    progressTitle.textContent = "Compilation Failed";
                    progressStatusText.textContent = compiler.message;
                    appendLog(`[ERROR] ${compiler.message}`);
                    btnCompile.disabled = false;
                }
            }
        } catch (e) {
            console.error("Error polling status:", e);
        }
    }, 1000);
}

function appendLog(message) {
    const date = new Date().toLocaleTimeString();
    consoleLogs.textContent += `\n[${date}] ${message}`;
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

// Render the Shorts list
function renderShortsGrid() {
    if (shortsData.length === 0) {
        emptyState.classList.remove('hidden');
        workspaceContent.classList.add('hidden');
        return;
    }

    emptyState.classList.add('hidden');
    workspaceContent.classList.remove('hidden');
    shortsGrid.innerHTML = '';

    shortsData.forEach((short, idx) => {
        const card = document.createElement('div');
        card.className = 'short-card glass selected';
        card.id = `short-card-${short.id}`;
        card.dataset.index = idx;

        const durationFormatted = formatDuration(short.duration);
        
        card.innerHTML = `
            <input type="checkbox" class="card-select-checkbox" checked id="checkbox-${short.id}" onchange="updateSelectedStats()">
            <div class="thumbnail-container">
                <img src="${short.thumbnail}" alt="${short.title}" onerror="this.src='https://placehold.co/320x180/0d1713/10b981?text=Thumbnail'">
                <span class="clip-duration-badge">${durationFormatted}</span>
            </div>
            <div class="card-form-body">
                <h4 class="card-video-title" title="${short.title}">${short.title}</h4>
                
                <div class="card-inputs-row">
                    <div class="mini-input-group">
                        <label>Reciter Name (Arabic)</label>
                        <input type="text" class="arabic-font" id="reciter-${short.id}" value="${short.reciter_ar || 'ياسر الدوسري'}">
                    </div>
                    <div class="mini-input-group">
                        <label>Surah Name</label>
                        <input type="text" id="surah-${short.id}" value="${short.surah_ar || short.surah_en || 'سورة الملك'}">
                    </div>
                </div>
                
                <div class="card-order-controls">
                    <span class="order-label">Position: #${idx + 1}</span>
                    <div class="reorder-btns">
                        <button class="btn-secondary" onclick="moveItem(${idx}, -1)" ${idx === 0 ? 'disabled' : ''}>▲</button>
                        <button class="btn-secondary" onclick="moveItem(${idx}, 1)" ${idx === shortsData.length - 1 ? 'disabled' : ''}>▼</button>
                    </div>
                </div>
            </div>
        `;
        
        shortsGrid.appendChild(card);
    });

    updateSelectedStats();
}

// Sort shorts by Quranic order (Surah index, then starting Ayah)
function sortShortsQuranic() {
    shortsData.sort((a, b) => {
        const surahA = a.surah_num || 999;
        const surahB = b.surah_num || 999;
        if (surahA !== surahB) {
            return surahA - surahB;
        }
        const ayahA = a.ayah_start || 0;
        const ayahB = b.ayah_start || 0;
        return ayahA - ayahB;
    });
}

function sortShortsQuranicAndRender() {
    syncEditedValues();
    sortShortsQuranic();
    renderShortsGrid();
}

// Move item up/down in sorting list
function moveItem(index, direction) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= shortsData.length) return;

    // Save edited values first
    syncEditedValues();

    // Swap items
    const temp = shortsData[index];
    shortsData[index] = shortsData[newIndex];
    shortsData[newIndex] = temp;

    renderShortsGrid();
}

// Sync DOM values back to state before sorting/compiling
function syncEditedValues() {
    shortsData.forEach((short) => {
        const reciterInput = document.getElementById(`reciter-${short.id}`);
        const surahInput = document.getElementById(`surah-${short.id}`);
        const checkbox = document.getElementById(`checkbox-${short.id}`);

        if (reciterInput) short.reciter_ar = reciterInput.value;
        if (surahInput) short.surah_ar = surahInput.value;
        if (checkbox) short.selected = checkbox.checked;
    });
}

// Toggle all checkboxes
function toggleAllClips(val) {
    shortsData.forEach((short) => {
        const checkbox = document.getElementById(`checkbox-${short.id}`);
        if (checkbox) {
            checkbox.checked = val;
        }
    });
    updateSelectedStats();
}

// Recalculate duration stats in sidebar
function updateSelectedStats() {
    let count = 0;
    let totalSecs = 0;

    shortsData.forEach((short) => {
        const checkbox = document.getElementById(`checkbox-${short.id}`);
        if (checkbox && checkbox.checked) {
            count++;
            totalSecs += short.duration || 30; // Fallback to 30s
            
            // visually add highlight class
            document.getElementById(`short-card-${short.id}`).classList.add('selected');
        } else if (checkbox) {
            document.getElementById(`short-card-${short.id}`).classList.remove('selected');
        }
    });

    selectedCount.textContent = count;
    
    // Add transition overhead between clips (e.g. 3s fade)
    const transitionSec = parseFloat(transitionInput.value);
    // There are (count - 1) transitions, but we also have fades on start and end.
    // In our compiler.py, each clip has a transition_duration fade out to black,
    // which overlaps with nothing (direct concatenation).
    // So the total duration is exactly the sum of clip durations.
    const m = Math.floor(totalSecs / 60);
    const s = Math.round(totalSecs % 60);
    estDuration.textContent = `${m}m ${s}s`;

    btnCompile.disabled = count === 0;
}

// Start compilation process
async function startCompilationProcess() {
    // 1. Sync all edited values in cards to the state
    syncEditedValues();

    // 2. Filter selected clips
    const selectedClips = shortsData.filter(s => s.selected !== false).map(s => {
        return {
            video_id: s.id,
            reciter_name: s.reciter_ar || "ياسر الدوسري",
            surah_name: s.surah_ar || "سورة الملك"
        };
    });

    if (selectedClips.length === 0) {
        alert("Please select at least one clip to compile.");
        return;
    }

    // Disable compile button, show progress
    btnCompile.disabled = true;
    progressPanel.classList.remove('hidden');
    outputPanel.classList.add('hidden');
    consoleLogs.textContent = "Starting compile execution...";
    
    setGlobalStatus('downloading', 'Starting assets downloading...');
    progressTitle.textContent = "Checking assets...";
    progressPercent.textContent = "0%";
    progressBarFill.style.width = "0%";

    // Scroll progress panel into view
    progressPanel.scrollIntoView({ behavior: 'smooth' });

    try {
        // Step A: Trigger downloading of required clips
        appendLog(`Initiating download for ${selectedClips.length} selected videos...`);
        const dlRes = await fetch('/api/download-selected', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(selectedClips)
        });

        if (!dlRes.ok) {
            const err = await dlRes.json();
            throw new Error(err.detail || "Download trigger failed");
        }

        // Start compiling polling
        startPollingStatus('compile');

        // Periodically check if download finishes. Once download is complete in polling,
        // we call the compilation endpoint.
        // Wait, main.py is set up such that download-selected runs in the background.
        // Once downloading status changes to completed, the compiler starts compiling?
        // Wait, main.py downloader and compiler are separate background runs.
        // Let's check how main.py handles it. In main.py, we have download-selected API.
        // If we want compilation to follow automatically, we should wait until the downloader status is 'completed'
        // and then trigger the compiler, OR we can make a single workflow in main.py.
        // In our main.py:
        // /api/download-selected downloads videos in background, then downloader status becomes "completed".
        // Let's modify our polling/trigger to wait for downloader to finish and then call /api/compile automatically!
        // This keeps the backend endpoints extremely clean and simple.
        
        let checkedDownload = false;
        const watchInterval = setInterval(async () => {
            const res = await fetch('/api/status');
            if (!res.ok) return;
            const progress = await res.json();
            
            if (progress.downloader.status === 'completed' && !checkedDownload) {
                checkedDownload = true;
                clearInterval(watchInterval);
                
                appendLog("Downloads finished. Launching FFmpeg compilation engine...");
                
                // Step B: Trigger compilation
                const compileRes = await fetch('/api/compile', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        clips: selectedClips,
                        transition_duration: parseFloat(transitionInput.value),
                        output_filename: filenameInput.value || "final_compilation.mp4"
                    })
                });
                
                if (!compileRes.ok) {
                    const err = await compileRes.json();
                    throw new Error(err.detail || "Compilation trigger failed");
                }
            } else if (progress.downloader.status === 'failed') {
                clearInterval(watchInterval);
                throw new Error("Downloader failed: " + progress.downloader.message);
            }
        }, 1000);

    } catch (e) {
        appendLog(`[ERROR] Process terminated: ${e.message}`);
        setGlobalStatus('failed', 'Process failed');
        btnCompile.disabled = false;
    }
}

// Show output panel when done
function showOutputPanel(result) {
    progressPanel.classList.add('hidden');
    outputPanel.classList.remove('hidden');
    btnCompile.disabled = false;

    // Load video player source
    // FastAPI mounts "data" on "/data".
    // Output path in result is absolute (e.g. C:\...\data\output\final.mp4).
    // Let's get the file name from output path.
    const parts = result.output_path.split(/[\\/]/);
    const filename = parts[parts.length - 1];
    
    outputVideoPlayer.src = `/data/output/${filename}`;
    outputVideoPlayer.load();
    
    outputFilePath.textContent = result.output_path;
    outputTitle.value = result.recommended_title;
    outputDescription.value = result.description;

    outputPanel.scrollIntoView({ behavior: 'smooth' });
}

// Helpers
function formatDuration(seconds) {
    if (!seconds) return "0:30";
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function copyToClipboard(elementId) {
    const copyText = document.getElementById(elementId);
    copyText.select();
    copyText.setSelectionRange(0, 99999); /* For mobile devices */
    
    navigator.clipboard.writeText(copyText.value)
        .then(() => {
            alert("Copied text to clipboard!");
        })
        .catch(err => {
            console.error("Could not copy text: ", err);
        });
}
