/**
 * app.js
 * ------
 * Dual-sensor radar dashboard.
 *
 * SensorPanel manages all state for one BGT60TR13C board:
 *   LED state machine, WebSocket stream, stats display, range-doppler heatmap.
 *
 * Two SensorPanel instances (id=0, id=1) are created at boot.
 * A single pollDevices() loop keeps both panels' detected/idle state current.
 */

import { PlotlyRenderer } from './renderers/plotly_renderer.js';

// Physics constants — must match radar/sdk.py
const RANGE_CM_PER_BIN   = 10;   // 0.1 m/bin × 100
const V_MAX_KMH          = 8.89; // ±8.89 km/h across 64 doppler bins
const DOPPLER_CENTRE      = 32;   // bin 32 = zero velocity (fftshift on 64 chirps)
const ACTIVITY_THRESH_DB  = 6;    // dB above baseline → activity

const logEl = document.getElementById('log-msg');
function log(msg) {
  logEl.textContent = msg;
  console.log('[radar]', msg);
}

// ── LED state metadata ────────────────────────────────────────────────────────
const STATE_META = {
  idle: {
    ledClass: 'idle', labelClass: 'idle', labelText: 'No device',
    btnText: 'Connect', btnClass: 'btn-connect', btnEnabled: false,
  },
  detected: {
    ledClass: 'detected', labelClass: 'detected', labelText: 'Device found',
    btnText: 'Connect', btnClass: 'btn-connect', btnEnabled: true,
  },
  connected: {
    ledClass: 'connected', labelClass: 'connected', labelText: 'Connected',
    btnText: 'Disconnect', btnClass: 'btn-disconnect', btnEnabled: true,
  },
  error: {
    ledClass: 'error', labelClass: 'error', labelText: 'Error',
    btnText: 'Retry', btnClass: 'btn-retry', btnEnabled: true,
  },
};

// ── SensorPanel class ─────────────────────────────────────────────────────────
class SensorPanel {
  constructor(id) {
    this.id = id;

    // DOM refs — all suffixed with sensor id
    this.ledEl         = document.getElementById(`led-${id}`);
    this.labelEl       = document.getElementById(`led-label-${id}`);
    this.descEl        = document.getElementById(`device-desc-${id}`);
    this.actionBtn     = document.getElementById(`action-btn-${id}`);
    this.cardEl        = document.getElementById(`card-${id}`);
    this.dataPanelEl   = document.getElementById(`data-panel-${id}`);
    this.dPeak         = document.getElementById(`d-peak-${id}`);
    this.dRange        = document.getElementById(`d-range-${id}`);
    this.dVel          = document.getElementById(`d-vel-${id}`);
    this.dBar          = document.getElementById(`d-bar-${id}`);
    this.dFps          = document.getElementById(`d-fps-${id}`);
    this.dActivity     = document.getElementById(`d-activity-${id}`);
    this.dActivityText = document.getElementById(`d-activity-text-${id}`);
    this.plotEl        = document.getElementById(`rd-plot-${id}`);

    // Per-sensor state
    this.appState    = 'idle';
    this.lastDetected = false;
    this.ws          = null;
    this.renderer    = null;

    // Baseline / stats (reset each connection)
    this.baselinePeak   = null;
    this.baselineFrames = 0;
    this.baselineSum    = 0;
    this.sessionPeakMax = -Infinity;
    this.sessionPeakMin =  Infinity;
    this.lastFrameTime  = performance.now();

    this._bindButton();
  }

  // ── LED state machine ───────────────────────────────────────────────────
  setState(newState, desc = null) {
    this.appState = newState;
    const m = STATE_META[newState];

    // Force animation restart — prevents browser reusing old timeline
    this.ledEl.style.animation = 'none';
    this.ledEl.className       = 'led ' + m.ledClass;
    this.ledEl.offsetHeight;          // force reflow — do NOT remove
    this.ledEl.style.animation = '';

    this.labelEl.className   = 'led-label ' + m.labelClass;
    this.labelEl.textContent = m.labelText;
    this.cardEl.className    = 'device-card ' + newState;

    if (newState === 'connected') {
      this.dataPanelEl.classList.add('visible');
      // Reset session stats
      this.baselinePeak   = null;
      this.baselineFrames = 0;
      this.baselineSum    = 0;
      this.sessionPeakMax = -Infinity;
      this.sessionPeakMin =  Infinity;
      this.lastFrameTime  = performance.now();
    } else {
      this.dataPanelEl.classList.remove('visible');
    }

    this.actionBtn.textContent = m.btnText;
    this.actionBtn.className   = 'btn ' + m.btnClass;
    this.actionBtn.disabled    = !m.btnEnabled;

    if (desc !== null) this.descEl.textContent = desc;
  }

  // ── WebSocket stream ────────────────────────────────────────────────────
  openStream() {
    if (this.ws) { this.ws.close(); this.ws = null; }

    const url = `ws://${location.host}/ws/${this.id}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.setState('connected', this.descEl.textContent);
      log(`Sensor ${this.id === 0 ? 'A' : 'B'}: WebSocket connected`);
      // Init heatmap
      this.renderer = new PlotlyRenderer();
      this.renderer.init(this.plotEl, { numDoppler: 64, numRange: 32, logScale: true });
    };

    this.ws.onclose = () => {
      if (this.appState === 'connected') {
        this.setState('error', 'Stream closed unexpectedly');
        log(`Sensor ${this.id === 0 ? 'A' : 'B'}: stream closed — click Retry`);
      }
    };

    this.ws.onerror = () => {
      this.setState('error', 'WebSocket error');
      log(`Sensor ${this.id === 0 ? 'A' : 'B'}: WebSocket error`);
    };

    this.ws.onmessage = (event) => {
      const { z, meta } = JSON.parse(event.data);
      this._onFrame(z, meta);
    };
  }

  closeStream() {
    if (this.ws) { this.ws.close(); this.ws = null; }
    if (this.renderer) { this.renderer.destroy(); this.renderer = null; }
  }

  // ── Frame handler ───────────────────────────────────────────────────────
  _onFrame(z, meta) {
    // Establish baseline from first 10 frames (empty scene)
    if (this.baselineFrames < 10) {
      this.baselineSum += meta.motion_peak;
      this.baselineFrames++;
      if (this.baselineFrames === 10) this.baselinePeak = this.baselineSum / 10;
      if (this.renderer && z) this.renderer.update(z);
      return;
    }

    // Physical units
    const rangeCm = (meta.motion_range_bin * RANGE_CM_PER_BIN).toFixed(0);
    const velBin  = meta.motion_doppler_bin - DOPPLER_CENTRE;
    const velKmh  = (velBin / DOPPLER_CENTRE * V_MAX_KMH).toFixed(1);
    const velSign = velBin > 0 ? '+' : '';

    // Signal bar
    this.sessionPeakMax = Math.max(this.sessionPeakMax, meta.motion_peak);
    this.sessionPeakMin = Math.min(this.sessionPeakMin, meta.motion_peak);
    const range = this.sessionPeakMax - this.sessionPeakMin || 1;
    const pct   = ((meta.motion_peak - this.sessionPeakMin) / range * 100).toFixed(1);

    // Activity
    const isActive = meta.motion_peak > this.baselinePeak + ACTIVITY_THRESH_DB;

    // FPS
    const now = performance.now();
    const fps = Math.round(1000 / (now - this.lastFrameTime));
    this.lastFrameTime = now;

    // DOM
    this.dPeak.textContent  = meta.motion_peak.toFixed(1);
    this.dRange.textContent = rangeCm;
    this.dVel.textContent   = velSign + velKmh;
    this.dBar.style.width   = pct + '%';
    this.dFps.textContent   = fps + ' fps';

    if (isActive) {
      this.dActivity.className       = 'activity-badge active';
      this.dActivityText.textContent = `Motion detected — ${rangeCm} cm away`;
    } else {
      this.dActivity.className       = 'activity-badge';
      this.dActivityText.textContent = 'No activity — wave your hand over the sensor';
    }

    // Heatmap
    if (this.renderer && z) this.renderer.update(z);
  }

  // ── Button click handler ────────────────────────────────────────────────
  _bindButton() {
    this.actionBtn.addEventListener('click', async () => {
      const label = this.id === 0 ? 'A' : 'B';

      if (this.appState === 'detected' || this.appState === 'idle') {
        // Connect
        this.actionBtn.disabled = true;
        log(`Sensor ${label}: connecting…`);
        try {
          const res  = await fetch(`/device/connect/${this.id}`, { method: 'POST' });
          const data = await res.json();
          if (data.ok) {
            this.openStream();
          } else {
            this.setState('error', data.error || 'Connect failed');
            log(`Sensor ${label}: connect failed — ${data.error}`);
          }
        } catch {
          this.setState('error', 'Server unreachable');
          log(`Sensor ${label}: connect request failed`);
        }

      } else if (this.appState === 'connected') {
        // Disconnect
        log(`Sensor ${label}: disconnecting…`);
        this.closeStream();
        try {
          await fetch(`/device/disconnect/${this.id}`, { method: 'POST' });
        } catch { /* best effort */ }
        this.setState(this.lastDetected ? 'detected' : 'idle', this.descEl.textContent);
        log(`Sensor ${label}: disconnected`);

      } else if (this.appState === 'error') {
        // Retry
        this.setState(this.lastDetected ? 'detected' : 'idle');
      }
    });
  }
}

// ── Instantiate both panels ───────────────────────────────────────────────────
const panels = [new SensorPanel(0), new SensorPanel(1)];

// ── Device polling  (single poll updates both panels) ────────────────────────
async function pollDevices() {
  try {
    const res  = await fetch('/device/status');
    const data = await res.json();

    data.sensors.forEach((dev, i) => {
      const panel = panels[i];
      if (panel.appState === 'connected') return;   // don't disturb active stream

      if (dev.detected) {
        panel.lastDetected       = true;
        panel.descEl.textContent = dev.description || 'Device ready';
        if (panel.appState !== 'detected') {
          panel.setState('detected');
          log(`Sensor ${i === 0 ? 'A' : 'B'}: device detected`);
        }
      } else {
        panel.lastDetected = false;
        if (panel.appState !== 'idle') {
          panel.setState('idle', 'No Infineon radar device found');
          log(`Sensor ${i === 0 ? 'A' : 'B'}: no device — polling…`);
        }
      }
    });
  } catch {
    log('Could not reach server — retrying…');
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  log('Starting — scanning for devices…');
  await pollDevices();
  setInterval(pollDevices, 3000);
}

boot();
