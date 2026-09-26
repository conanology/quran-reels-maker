'use strict';
// Source labels are suggestions until a reviewer confirms the recording and coverage.
let shortsData = [];
let activeJob = null;
let busy = false;
let lastOperation = null;
const $ = id => document.getElementById(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(path, {...options, signal: controller.signal});
        const data = await response.json();
        if (!response.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : 'Please check the selected clips, verified labels and filename.';
            throw new Error(detail);
        }
        return data;
    } finally { clearTimeout(timeout); }
}
const post = (path, data) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
function setStatus(status, message) {
    $('global-status-dot').className = `status-indicator-dot ${status}`;
    $('global-status-text').textContent = message;
}
function setBusy(value) {
    busy = value;
    document.querySelectorAll('#workspace-content input, #workspace-content button, #channel-input, #btn-fetch, #transition-input, #filename-input').forEach(el => { el.disabled = value; });
    $('btn-cancel').classList.toggle('hidden', !value);
    $('btn-retry').classList.add('hidden');
    if (!value) renderShortsGrid();
    updateSelectedStats();
}
function log(message) {
    const lines = $('console-logs').textContent.split('\n').slice(-80);
    $('console-logs').textContent = [...lines, message].join('\n');
}
function progress(status) {
    const pct = Math.min(100, Math.max(0, Math.round(100 * status.current / Math.max(status.total, 1))));
    $('progress-title').textContent = status.kind === 'fetch' ? 'Importing source clips' : 'Compiling reviewed clips';
    $('progress-percent').textContent = `${pct}%`;
    $('progress-bar-fill').style.width = `${pct}%`;
    $('progress-bar-bg').setAttribute('aria-valuenow', String(pct));
    $('progress-status-text').textContent = status.message;
    setStatus(status.status, status.message);
    log(status.message);
}
async function pollJob(ident) {
    const deadline = Date.now() + 60 * 60 * 1000;
    let errors = 0;
    while (Date.now() < deadline) {
        let status;
        try { status = await api(`/api/jobs/${ident}`); errors = 0; }
        catch (error) {
            if (++errors >= 3) throw new Error('Connection lost. Cancel the current job before retrying; its status is retained on the server.');
            $('progress-status-text').textContent = 'Connection interrupted. Retrying status…';
            await sleep(1000); continue;
        }
        if (status.job_id !== ident) throw new Error('Server returned a status for a different job.');
        progress(status);
        if (status.status === 'completed') return status.result;
        if (status.status === 'failed' || status.status === 'cancelled') throw new Error(status.message);
        await sleep(700);
    }
    throw new Error('Status deadline reached. Cancel the retained job before retrying.');
}
async function runOperation(kind, body) {
    if (busy) return;
    lastOperation = {kind, body};
    activeJob = null;
    setBusy(true);
    $('progress-panel').classList.remove('hidden');
    $('output-panel').classList.add('hidden');
    $('console-logs').textContent = 'Starting local job…';
    $('progress-status-text').textContent = 'Submitting request…';
    try {
        const accepted = await post(kind === 'fetch' ? '/api/fetch-shorts' : '/api/compile', body);
        if (!/^[a-f0-9]{32}$/.test(accepted.job_id)) throw new Error('Server did not return a valid job identifier.');
        activeJob = accepted.job_id;
        const result = await pollJob(activeJob);
        if (kind === 'fetch') {
            shortsData = result.shorts.map(s => ({...s, selected: true, attribution_verified: false}));
            sortShortsQuranic(); renderShortsGrid();
            $('fetch-progress-msg').textContent = `Imported ${shortsData.length} clips. Review every selected recording and label.`;
            $('progress-panel').classList.add('hidden');
        } else showOutputPanel(result);
        activeJob = null;
        setBusy(false);
        setStatus('completed', 'Ready for review');
    } catch (error) {
        setBusy(false);
        $('progress-title').textContent = 'Job needs attention';
        $('progress-status-text').textContent = error.name === 'AbortError' ? 'Request timed out. Check server status before retrying.' : error.message;
        log($('progress-status-text').textContent);
        setStatus('failed', 'Job needs attention');
        $('btn-retry').classList.remove('hidden');
        $('btn-cancel').classList.toggle('hidden', !activeJob);
    }
}
async function cancelJob() {
    if (!activeJob) return;
    $('btn-cancel').disabled = true;
    try {
        await post(`/api/jobs/${activeJob}/cancel`, {});
        $('progress-status-text').textContent = 'Cancellation requested. The media process is stopping…';
        if (!busy) {
            try { await pollJob(activeJob); } catch (_) { /* cancelled status is expected */ }
            activeJob = null;
            $('btn-cancel').classList.add('hidden');
        }
    } catch (error) { $('progress-status-text').textContent = `Cancel failed: ${error.message}`; }
    finally { $('btn-cancel').disabled = false; }
}
function safeThumbnail(value) {
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && ['i.ytimg.com','img.youtube.com'].includes(url.hostname) && !url.port && !url.username && !url.password ? url.href : '';
    } catch (_) { return ''; }
}
function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
}
function renderShortsGrid() {
    $('empty-state').classList.toggle('hidden', shortsData.length > 0);
    $('workspace-content').classList.toggle('hidden', shortsData.length === 0);
    $('shorts-grid').replaceChildren();
    shortsData.forEach((short, idx) => {
        const card = element('article', `short-card glass${short.selected ? ' selected' : ''}`);
        card.id = `short-card-${short.id}`;
        const check = element('input', 'card-select-checkbox');
        check.type = 'checkbox'; check.checked = short.selected !== false;
        check.setAttribute('aria-label', `Include clip ${idx+1}: ${short.title}`);
        check.addEventListener('change', () => { short.selected = check.checked; card.classList.toggle('selected', check.checked); updateSelectedStats(); });
        card.append(check);
        const thumb = element('div', 'thumbnail-container');
        const url = safeThumbnail(short.thumbnail);
        if (url) { const img = element('img'); img.src = url; img.alt = ''; img.loading = 'lazy'; thumb.append(img); }
        thumb.append(element('span', 'clip-duration-badge', formatDuration(short.duration)));
        card.append(thumb);
        const body = element('div', 'card-form-body');
        const title = element('h3', 'card-video-title', short.title); title.title = short.title; body.append(title);
        const source = element('a', 'source-link', 'Review source recording ↗');
        source.href = `https://www.youtube.com/watch?v=${encodeURIComponent(short.id)}`; source.target = '_blank'; source.rel = 'noopener noreferrer'; body.append(source);
        const inputs = element('div', 'card-inputs-row');
        [['reciter_ar','Reciter name', 'Verified reciter name'], ['surah_ar','Surah and actual verse coverage', 'Verified Surah and verses, e.g. 67:1–4']].forEach(([key, labelText, placeholder]) => {
            const group = element('div', 'mini-input-group');
            const label = element('label', '', labelText); label.htmlFor = `${key}-${short.id}`;
            const input = element('input', 'arabic-font'); input.type = 'text'; input.id = label.htmlFor; input.dir = 'auto'; input.maxLength = key === 'reciter_ar' ? 120 : 180;
            input.value = short[key] || (key === 'surah_ar' ? short.surah_en || '' : ''); input.placeholder = placeholder;
            input.addEventListener('input', () => { short[key] = input.value; short.attribution_verified = false; verified.checked = false; updateSelectedStats(); });
            group.append(label, input); inputs.append(group);
        });
        body.append(inputs);
        const reviewLabel = element('label', 'review-confirm');
        const verified = element('input'); verified.type = 'checkbox'; verified.checked = short.attribution_verified === true;
        verified.addEventListener('change', () => { short.attribution_verified = verified.checked; updateSelectedStats(); });
        reviewLabel.append(verified, document.createTextNode('I checked this recording, reciter and verse coverage.'));
        body.append(reviewLabel);
        const controls = element('div', 'card-order-controls'); controls.append(element('span', 'order-label', `Position: #${idx+1}`));
        const buttons = element('div', 'reorder-btns');
        [-1,1].forEach(direction => {
            const button = element('button', 'btn-secondary', direction < 0 ? '↑' : '↓'); button.type = 'button';
            button.setAttribute('aria-label', `Move clip ${idx+1} ${direction < 0 ? 'earlier' : 'later'}`);
            button.disabled = busy || (direction < 0 ? idx === 0 : idx === shortsData.length-1);
            button.addEventListener('click', () => moveItem(idx, direction)); buttons.append(button);
        });
        controls.append(buttons); body.append(controls); card.append(body); $('shorts-grid').append(card);
    });
    updateSelectedStats();
}
function moveItem(index, direction) {
    if (busy) return;
    const next = index+direction;
    if (next < 0 || next >= shortsData.length) return;
    [shortsData[index], shortsData[next]] = [shortsData[next], shortsData[index]];
    const id = shortsData[next].id;
    renderShortsGrid();
    document.getElementById(`reciter_ar-${id}`).focus();
}
function sortShortsQuranic() {
    shortsData.sort((a,b) => (a.surah_num || 999)-(b.surah_num || 999) || (a.ayah_start || 0)-(b.ayah_start || 0));
}
function toggleAllClips(value) { if (!busy) { shortsData.forEach(s => s.selected = value); renderShortsGrid(); } }
function updateSelectedStats() {
    const selected = shortsData.filter(s => s.selected !== false);
    const seconds = selected.reduce((sum,s) => sum+(Number.isFinite(s.duration) ? s.duration : 0), 0);
    $('selected-count').textContent = selected.length;
    $('est-duration').textContent = `${Math.floor(seconds/60)}m ${Math.round(seconds%60)}s${selected.some(s => !s.duration) ? ' + unknown' : ''}`;
    const incomplete = selected.some(s => !s.attribution_verified || !s.reciter_ar?.trim() || !(s.surah_ar || s.surah_en)?.trim());
    $('review-status').textContent = incomplete ? 'Review and confirm every selected clip before compiling.' : `${selected.length} reviewed clip(s). Maximum 20 clips / 1 hour.`;
    $('btn-compile').disabled = busy || !selected.length || incomplete || selected.length > 20;
}
function startCompilationProcess() {
    const clips = shortsData.filter(s => s.selected !== false).map(s => ({video_id:s.id,reciter_name:s.reciter_ar?.trim() || '',surah_name:(s.surah_ar || s.surah_en || '').trim(),attribution_verified:s.attribution_verified === true}));
    if (!clips.length || clips.some(c => !c.reciter_name || !c.surah_name || !c.attribution_verified)) { $('review-status').textContent = 'Verify the actual recording and labels of each selected clip.'; return; }
    runOperation('compile', {clips,transition_duration:Number($('transition-input').value),output_filename:$('filename-input').value});
}
function showOutputPanel(result) {
    if (!/^\/api\/jobs\/[a-f0-9]{32}\/preview$/.test(result.preview_url) || !/^\/api\/jobs\/[a-f0-9]{32}\/download$/.test(result.download_url)) throw new Error('Invalid output location.');
    $('progress-panel').classList.add('hidden'); $('output-panel').classList.remove('hidden');
    $('output-video-player').src = result.preview_url; $('output-video-player').load();
    $('output-file-path').textContent = result.output_filename;
    $('output-title').value = result.recommended_title;
    $('output-description').value = result.description;
    $('output-download').href = result.download_url; $('output-download').download = result.output_filename;
    const heading = $('output-panel').querySelector('h2');
    heading.tabIndex = -1; heading.focus({preventScroll:true});
    $('output-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
function formatDuration(seconds) {
    if (!Number.isFinite(seconds)) return 'Duration unknown';
    const total = Math.round(seconds); return `${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`;
}
window.addEventListener('DOMContentLoaded', async () => {
    $('transition-input').addEventListener('input', e => $('transition-value').textContent = `${e.target.value}s`);
    $('btn-fetch').addEventListener('click', () => runOperation('fetch', {channel_url:$('channel-input').value.trim()}));
    $('btn-compile').addEventListener('click', startCompilationProcess);
    $('btn-sort-quranic').addEventListener('click', () => { if (!busy) { sortShortsQuranic(); renderShortsGrid(); } });
    $('btn-select-all').addEventListener('click', () => toggleAllClips(true)); $('btn-deselect-all').addEventListener('click', () => toggleAllClips(false));
    $('btn-cancel').addEventListener('click', cancelJob);
    $('btn-retry').addEventListener('click', async () => { if (activeJob) await cancelJob(); if (!activeJob && lastOperation) runOperation(lastOperation.kind,lastOperation.body); });
    document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText($(button.dataset.copy).value); $('copy-status').textContent = 'Copied.'; }
        catch (_) { $(button.dataset.copy).select(); $('copy-status').textContent = 'Select and copy the text with your keyboard.'; }
    }));
    try { const items = await api('/api/shorts'); shortsData = items.map(s => ({...s,selected:true,attribution_verified:false})); sortShortsQuranic(); renderShortsGrid(); }
    catch (error) { $('fetch-progress-msg').textContent = error.message; }
});
