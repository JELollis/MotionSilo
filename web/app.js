const video = document.querySelector('#preview');
const canvas = document.querySelector('#motionCanvas');
const ctx = canvas.getContext('2d', { willReadFrequently: true });
const cameraSelect = document.querySelector('#cameraSelect');
const startButton = document.querySelector('#startButton');
const stopButton = document.querySelector('#stopButton');
const refreshButton = document.querySelector('#refreshCameras');
const sensitivity = document.querySelector('#sensitivity');
const cooldown = document.querySelector('#cooldown');

let stream = null;
let monitorTimer = null;
let mediaRecorder = null;
let chunks = [];
let recordingStartedAt = 0;
let recordingStopTimer = null;
let previousFrame = null;
let isMonitoring = false;
let recordings = [];
let saveDirectoryHandle = null;

const sensitivityMap = { 1: { label: 'Low', threshold: 0.035 }, 2: { label: 'Medium', threshold: 0.018 }, 3: { label: 'High', threshold: 0.009 } };

function setStatus(connected) {
  document.querySelector('#permissionLabel').textContent = connected ? 'Camera connected' : 'Camera not connected';
  document.querySelector('.status-dot').classList.toggle('online', connected);
  document.querySelector('#liveIndicator').classList.toggle('on', connected);
  document.querySelector('#previewLabel').textContent = connected ? 'Live preview' : 'Preview offline';
}

async function listCameras() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const cameras = devices.filter(device => device.kind === 'videoinput');
    cameraSelect.innerHTML = cameras.length ? cameras.map((camera, i) => `<option value="${camera.deviceId}">${camera.label || `Camera ${i + 1}`}</option>`).join('') : '<option value="">No cameras found</option>';
    startButton.disabled = !stream;
    document.querySelector('#cameraHint').textContent = cameras.length ? `${cameras.length} camera${cameras.length === 1 ? '' : 's'} available on this device.` : 'No video input was found.';
  } catch (error) { document.querySelector('#cameraHint').textContent = 'Camera access is unavailable in this browser.'; }
}

async function connectCamera(deviceId = '') {
  if (!navigator.mediaDevices?.getUserMedia) { document.querySelector('#cameraHint').textContent = 'This browser does not support camera access.'; return; }
  if (stream) stream.getTracks().forEach(track => track.stop());
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    video.srcObject = stream;
    video.classList.add('ready');
    video.onloadedmetadata = () => { document.querySelector('#resolutionLabel').textContent = `${video.videoWidth} × ${video.videoHeight}`; };
    setStatus(true); await listCameras();
    if (deviceId) cameraSelect.value = deviceId;
    startButton.disabled = false;
  } catch (error) { stream = null; setStatus(false); document.querySelector('#cameraHint').textContent = error.name === 'NotAllowedError' ? 'Camera permission was denied. Allow access and try again.' : 'Could not connect to that camera.'; }
}

function detectMotion() {
  if (!isMonitoring || video.readyState < 2) return;
  const width = 160, height = 90; canvas.width = width; canvas.height = height; ctx.drawImage(video, 0, 0, width, height);
  const pixels = ctx.getImageData(0, 0, width, height).data; const grayscale = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < pixels.length; i += 4, p++) grayscale[p] = (pixels[i] * 0.299 + pixels[i + 1] * 0.587 + pixels[i + 2] * 0.114);
  if (!previousFrame) { previousFrame = grayscale; return; }
  let changed = 0, totalDifference = 0;
  for (let i = 0; i < grayscale.length; i++) { const diff = Math.abs(grayscale[i] - previousFrame[i]); totalDifference += diff; if (diff > 22) changed++; }
  previousFrame = grayscale;
  const activity = Math.min(100, Math.round((totalDifference / grayscale.length) * 3)); document.querySelector('#activityMeter').style.width = `${activity}%`;
  if (changed / grayscale.length > sensitivityMap[sensitivity.value].threshold) triggerMotion();
}

function triggerMotion() {
  document.querySelector('#motionBadge').style.display = 'block'; document.querySelector('#activityText').textContent = 'Movement detected';
  clearTimeout(recordingStopTimer);
  if (!mediaRecorder || mediaRecorder.state === 'inactive') startRecording();
  recordingStopTimer = setTimeout(() => { if (mediaRecorder?.state === 'recording') mediaRecorder.stop(); }, Number(cooldown.value) * 1000 + 1000);
  setTimeout(() => { if (!mediaRecorder || mediaRecorder.state !== 'recording') document.querySelector('#motionBadge').style.display = 'none'; }, 900);
}

function startRecording() {
  if (!stream) return;
  chunks = []; const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(type => MediaRecorder.isTypeSupported(type));
  mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined); recordingStartedAt = Date.now();
  mediaRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
  mediaRecorder.onstop = saveRecording; mediaRecorder.start(1000);
  document.querySelector('#recordingBadge').style.display = 'block';
}

async function saveRecording() {
  if (!chunks.length) return; const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'video/webm' });
  const date = new Date(recordingStartedAt); const filename = `motion-${date.toISOString().replace(/[:.]/g, '-')}.webm`;
  if (saveDirectoryHandle) {
    try { const fileHandle = await saveDirectoryHandle.getFileHandle(filename, { create: true }); const writable = await fileHandle.createWritable(); await writable.write(blob); await writable.close(); }
    catch (error) { console.warn('Could not write to selected folder; keeping the clip available for download.', error); }
  }
  recordings.unshift({ blob, url: URL.createObjectURL(blob), date, duration: Math.max(1, Math.round((Date.now() - recordingStartedAt) / 1000)) }); renderRecordings();
  document.querySelector('#recordingBadge').style.display = 'none'; document.querySelector('#activityText').textContent = 'Monitoring for movement';
}

function formatDuration(seconds) { return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }
function renderRecordings() {
  document.querySelector('#recordingCount').textContent = recordings.length; document.querySelector('#clearRecordings').disabled = !recordings.length;
  const grid = document.querySelector('#recordingsGrid'); document.querySelector('#recordingsEmpty').style.display = recordings.length ? 'none' : 'block';
  grid.querySelectorAll('.recording-card').forEach(card => card.remove());
  recordings.forEach((recording, index) => { const card = document.createElement('article'); card.className = 'recording-card'; card.innerHTML = `<video controls preload="metadata" src="${recording.url}"></video><div class="recording-info"><div><strong>Motion event ${recordings.length - index}</strong><small>${recording.date.toLocaleString()} · ${formatDuration(recording.duration)}</small></div><a class="download" download="motion-event-${recording.date.toISOString().replace(/[:.]/g, '-')}.webm" href="${recording.url}" title="Download recording">↓</a></div>`; grid.appendChild(card); });
}

startButton.addEventListener('click', () => { isMonitoring = true; previousFrame = null; startButton.disabled = true; stopButton.disabled = false; cameraSelect.disabled = true; document.querySelector('#sessionStatus').textContent = 'MONITORING'; document.querySelector('#sessionStatus').classList.add('active'); document.querySelector('#activityText').textContent = 'Monitoring for movement'; monitorTimer = setInterval(detectMotion, 250); });
stopButton.addEventListener('click', () => { isMonitoring = false; clearInterval(monitorTimer); clearTimeout(recordingStopTimer); if (mediaRecorder?.state === 'recording') mediaRecorder.stop(); startButton.disabled = false; stopButton.disabled = true; cameraSelect.disabled = false; document.querySelector('#sessionStatus').textContent = 'INACTIVE'; document.querySelector('#sessionStatus').classList.remove('active'); document.querySelector('#activityText').textContent = 'Monitoring stopped'; });
cameraSelect.addEventListener('change', () => { if (cameraSelect.value) connectCamera(cameraSelect.value); }); refreshButton.addEventListener('click', () => connectCamera(cameraSelect.value));
sensitivity.addEventListener('input', () => { document.querySelector('#sensitivityValue').textContent = sensitivityMap[sensitivity.value].label; }); cooldown.addEventListener('input', () => { document.querySelector('#cooldownValue').textContent = `${cooldown.value} sec`; });
document.querySelector('#clearRecordings').addEventListener('click', () => { recordings.forEach(recording => URL.revokeObjectURL(recording.url)); recordings = []; renderRecordings(); });
document.querySelector('#chooseSaveFolder').addEventListener('click', async () => {
  if (!window.showDirectoryPicker) { document.querySelector('#saveLocation').textContent = 'Folder selection is not supported; use downloads'; return; }
  try { saveDirectoryHandle = await window.showDirectoryPicker({ mode: 'readwrite' }); document.querySelector('#saveLocation').textContent = `Saving to: ${saveDirectoryHandle.name}`; }
  catch (error) { if (error.name !== 'AbortError') document.querySelector('#saveLocation').textContent = 'Could not access that folder'; }
});
if (navigator.mediaDevices) { navigator.mediaDevices.addEventListener('devicechange', listCameras); listCameras(); }
