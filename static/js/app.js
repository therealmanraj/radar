/**
 * app.js
 * ------
 * Device detection → connect flow → WebSocket stream.
 *
 * LED states
 * ----------
 *   idle      — no device detected (amber, slow pulse)
 *   detected  — device found, not connected (dim white, slow pulse)
 *   connected — streaming (solid white, static)
 *   error     — connection failed (red, fast blink)
 *
 * Renderer is imported but not used yet (graph is removed for now).
 * Uncomment the renderer lines when the graph step is added back.
 */

// ── DOM refs ────────────────────────────────────────────────────────────────
const ledEl      = document.getElementById('led');
const labelEl    = document.getElementById('led-label');
const nameEl     = document.getElementById('device-name');
const descEl     = document.getElementById('device-desc');
const actionBtn  = document.getElementById('action-btn');
const logEl      = document.getElementById('log-msg');
const cardEl     = document.querySelector('.device-card');
const dataPanelEl   = document.getElementById('data-panel');
const dPeak         = document.getElementById('d-peak');
const dRange        = document.getElementById('d-range');
const dVel          = document.getElementById('d-vel');
const dBar          = document.getElementById('d-bar');
const dFps          = document.getElementById('d-fps');
const dActivity     = document.getElementById('d-activity');
const dActivityText = document.getElementById('d-activity-text');

// Physics constants — must match radar/sdk.py
const RANGE_CM_PER_BIN = 10;          // 0.1 m/bin × 100
const V_MAX_KMH        = 8.89;        // ±8.89 km/h across 64 doppler bins
const DOPPLER_CENTRE   = 32;          // bin 32 = zero velocity (fftshift on 64 chirps)
const ACTIVITY_THRESH_DB = 6;         // dB above baseline in motion bins → activity

// Rolling session stats for the signal bar and baseline
let sessionPeakMax = -Infinity;
let sessionPeakMin =  Infinity;
let baselinePeak   = null;            // set from first N frames
let baselineFrames = 0;
let baselineSum    = 0;
let lastFrameTime  = performance.now();
let fpsFrames      = 0;

// ── State ───────────────────────────────────────────────────────────────────
let ws            = null;
let pollTimer     = null;
let appState      = 'idle';      // 'idle' | 'detected' | 'connected' | 'error'
let lastDetected  = false;

// ── Logging ─────────────────────────────────────────────────────────────────
function log(msg) {
  logEl.textContent = msg;
  console.log('[radar]', msg);
}

// ── LED state machine ────────────────────────────────────────────────────────
const STATE_META = {
  idle: {
    ledClass:   'idle',
    labelClass: 'idle',
    labelText:  'No device',
    btnText:    'Connect',
    btnClass:   'btn-connect',
    btnEnabled: false,
  },
  detected: {
    ledClass:   'detected',
    labelClass: 'detected',
    labelText:  'Device found',
    btnText:    'Connect',
    btnClass:   'btn-connect',
    btnEnabled: true,
  },
  connected: {
    ledClass:   'connected',
    labelClass: 'connected',
    labelText:  'Connected',
    btnText:    'Disconnect',
    btnClass:   'btn-disconnect',
    btnEnabled: true,
  },
  error: {
    ledClass:   'error',
    labelClass: 'error',
    labelText:  'Error',
    btnText:    'Retry',
    btnClass:   'btn-retry',
    btnEnabled: true,
  },
};

function setState(newState, desc = null) {
  appState = newState;
  const m  = STATE_META[newState];

  // ── LED — force animation restart ───────────────────────────────────────
  // Browsers reuse the running animation timeline when you swap CSS classes.
  // Setting animation:none + reading offsetHeight triggers a reflow that
  // flushes the old animation, so the new class animation starts from frame 0.
  ledEl.style.animation = 'none';
  ledEl.className       = 'led ' + m.ledClass;
  ledEl.offsetHeight;          // force reflow — do NOT remove this line
  ledEl.style.animation = '';  // hand control back to the CSS class

  // ── Label ────────────────────────────────────────────────────────────────
  labelEl.className   = 'led-label ' + m.labelClass;
  labelEl.textContent = m.labelText;

  // ── Card border ──────────────────────────────────────────────────────────
  cardEl.className = 'device-card ' + newState;

  // ── Data panel ───────────────────────────────────────────────────────────
  if (newState === 'connected') {
    dataPanelEl.classList.add('visible');
    // Reset session stats on each new connection
    sessionPeakMax = -Infinity;
    sessionPeakMin =  Infinity;
    baselinePeak   = null;
    baselineFrames = 0;
    baselineSum    = 0;
  } else {
    dataPanelEl.classList.remove('visible');
  }

  // ── Button ───────────────────────────────────────────────────────────────
  actionBtn.textContent = m.btnText;
  actionBtn.className   = 'btn ' + m.btnClass;
  actionBtn.disabled    = !m.btnEnabled;

  // Optional description override
  if (desc !== null) descEl.textContent = desc;
}

// ── Device polling ───────────────────────────────────────────────────────────
async function pollDevice() {
  try {
    const res  = await fetch('/device/status');
    const data = await res.json();

    // Don't update LED while we're actively connected
    if (appState === 'connected') return;

    if (data.detected) {
      lastDetected = true;
      descEl.textContent = data.description || 'Device ready';
      if (appState !== 'detected') {
        setState('detected');
        log(`Device detected: ${data.description}`);
      }
    } else {
      lastDetected = false;
      if (appState !== 'idle') {
        setState('idle', 'No Infineon radar device found');
        log('No device found — polling…');
      }
    }
  } catch {
    log('Could not reach server — retrying…');
  }
}

// ── WebSocket stream ─────────────────────────────────────────────────────────
function openStream() {
  if (ws) { ws.close(); ws = null; }

  const url = `ws://${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    setState('connected', descEl.textContent);
    log('WebSocket connected — receiving frames');
  };

  ws.onclose = () => {
    if (appState === 'connected') {
      // Unexpected close
      setState('error', 'Stream closed unexpectedly');
      log('WebSocket closed — click Retry to reconnect');
    }
  };

  ws.onerror = () => {
    setState('error', 'WebSocket error');
    log('WebSocket error');
  };

  ws.onmessage = (event) => {
    const { meta } = JSON.parse(event.data);

    // ── Establish baseline from first 10 frames (empty scene) ──────────
    // Use motion_peak for baseline — it's the clutter-rejected value
    if (baselineFrames < 10) {
      baselineSum += meta.motion_peak;
      baselineFrames++;
      if (baselineFrames === 10) baselinePeak = baselineSum / 10;
      return;
    }

    // ── Convert bins → physical units (motion-peak bins) ────────────────
    const rangeCm = (meta.motion_range_bin * RANGE_CM_PER_BIN).toFixed(0);
    const velBin  = meta.motion_doppler_bin - DOPPLER_CENTRE;
    const velKmh  = (velBin / DOPPLER_CENTRE * V_MAX_KMH).toFixed(1);
    const velSign = velBin > 0 ? '+' : '';

    // ── Signal bar — normalised to session motion_peak min/max ───────────
    sessionPeakMax = Math.max(sessionPeakMax, meta.motion_peak);
    sessionPeakMin = Math.min(sessionPeakMin, meta.motion_peak);
    const range = sessionPeakMax - sessionPeakMin || 1;
    const pct   = ((meta.motion_peak - sessionPeakMin) / range * 100).toFixed(1);

    // ── Activity detection — motion_peak vs. quiet baseline ──────────────
    const isActive = meta.motion_peak > baselinePeak + ACTIVITY_THRESH_DB;

    // ── FPS ──────────────────────────────────────────────────────────────
    fpsFrames++;
    const now = performance.now();
    const fps = Math.round(1000 / (now - lastFrameTime));
    lastFrameTime = now;

    // ── Update DOM ───────────────────────────────────────────────────────
    dPeak.textContent = meta.motion_peak.toFixed(1);
    dRange.textContent = rangeCm;
    dVel.textContent  = velSign + velKmh;
    dBar.style.width  = pct + '%';
    dFps.textContent  = fps + ' fps';

    if (isActive) {
      dActivity.className       = 'activity-badge active';
      dActivityText.textContent = `Motion detected — ${rangeCm} cm away`;
    } else {
      dActivity.className       = 'activity-badge';
      dActivityText.textContent = 'No activity — wave your hand over the sensor';
    }
  };
}

function closeStream() {
  if (ws) { ws.close(); ws = null; }
}

// ── Button handler ───────────────────────────────────────────────────────────
actionBtn.addEventListener('click', async () => {
  if (appState === 'detected' || appState === 'idle') {
    // ── Connect ──
    actionBtn.disabled = true;
    log('Sending connect request…');
    try {
      const res  = await fetch('/device/connect', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        openStream();
      } else {
        setState('error', data.error || 'Connect failed');
        log(`Connect failed: ${data.error}`);
      }
    } catch (e) {
      setState('error', 'Server unreachable');
      log('Connect request failed');
    }

  } else if (appState === 'connected') {
    // ── Disconnect ──
    log('Disconnecting…');
    closeStream();
    try {
      await fetch('/device/disconnect', { method: 'POST' });
    } catch { /* best effort */ }
    setState('detected', descEl.textContent);
    log('Disconnected');

  } else if (appState === 'error') {
    // ── Retry ──
    setState(lastDetected ? 'detected' : 'idle');
    log('Retrying…');
  }
});

// ── Boot ─────────────────────────────────────────────────────────────────────
async function boot() {
  log('Starting — scanning for devices…');
  await pollDevice();
  // Poll every 3 seconds to detect plug/unplug
  pollTimer = setInterval(pollDevice, 3000);
}

boot();
