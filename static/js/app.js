/**
 * app.js
 * ------
 * WebSocket client + renderer orchestrator.
 *
 * ┌─────────────────────────────────────────────────────────────┐
 * │  To switch renderer:  change ONE import + ONE constructor   │
 * │                                                             │
 * │  Current:  PlotlyRenderer  (Plotly.js heatmap)              │
 * │  Upgrade:  CanvasRenderer  (Canvas 2D — see below)          │
 * └─────────────────────────────────────────────────────────────┘
 */

// ── Renderer selection ──────────────────────────────────────────────────────
import { PlotlyRenderer }  from './renderers/plotly_renderer.js';
// import { CanvasRenderer } from './renderers/canvas_renderer.js';  // ← swap here

const RENDERER = new PlotlyRenderer();
// const RENDERER = new CanvasRenderer();                            // ← and here


// ── DOM refs ────────────────────────────────────────────────────────────────
const radarEl    = document.getElementById('radar-container');
const statusEl   = document.getElementById('status');
const statFrame  = document.getElementById('stat-frame');
const statFps    = document.getElementById('stat-fps');
const statPeak   = document.getElementById('stat-peak');
const statBin    = document.getElementById('stat-bin');


// ── State ───────────────────────────────────────────────────────────────────
let initialized   = false;
let serverConfig  = {};
let lastFrameTime = performance.now();
let ws            = null;


// ── FPS smoothing (rolling average over 10 frames) ──────────────────────────
const FPS_WINDOW   = 10;
const fpsHistory   = new Float32Array(FPS_WINDOW);
let   fpsIdx       = 0;

function recordFps() {
  const now  = performance.now();
  const dt   = now - lastFrameTime;
  lastFrameTime = now;
  fpsHistory[fpsIdx % FPS_WINDOW] = 1000 / dt;
  fpsIdx++;
  const count = Math.min(fpsIdx, FPS_WINDOW);
  let sum = 0;
  for (let i = 0; i < count; i++) sum += fpsHistory[i];
  return Math.round(sum / count);
}


// ── WebSocket connection ─────────────────────────────────────────────────────
function connect() {
  const url = `ws://${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onopen = () => setStatus('Connected', true);

  ws.onclose = () => {
    setStatus('Disconnected — reconnecting…', false);
    setTimeout(connect, 2000);
  };

  ws.onerror = () => setStatus('Connection error', false);

  ws.onmessage = (event) => {
    const { z, meta } = JSON.parse(event.data);

    // First frame: initialise the renderer with real grid dimensions
    if (!initialized) {
      RENDERER.init(radarEl, {
        rows:        meta.rows,
        cols:        meta.cols,
        colorscale:  'Viridis',
        logScale:    serverConfig.log_scale ?? true,
      });
      initialized = true;
    }

    RENDERER.update(z, meta);

    // Update stats panel
    const fps = recordFps();
    statFrame.textContent = meta.frame;
    statFps.textContent   = fps;
    statPeak.textContent  = meta.peak.toFixed(1) + (meta.log_scale ? ' dB' : '');
    statBin.textContent   = meta.peak_range_bin;
  };
}


// ── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(text, ok) {
  statusEl.textContent  = text;
  statusEl.className    = 'status ' + (ok ? 'ok' : 'err');
}


// ── Boot ─────────────────────────────────────────────────────────────────────
async function boot() {
  try {
    const res    = await fetch('/config');
    serverConfig = await res.json();
  } catch {
    console.warn('Could not fetch /config — using defaults');
  }
  connect();
}

boot();
