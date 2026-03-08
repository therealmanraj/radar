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

  ws.onmessage = (_event) => {
    // Frame data arrives here.
    // Renderer will be wired up here in the next step (graph re-add).
    // const { z, meta } = JSON.parse(_event.data);
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
