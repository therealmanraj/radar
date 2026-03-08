/**
 * canvas_renderer.js
 * ------------------
 * High-performance heatmap renderer using HTML5 Canvas + ImageData.
 *
 * Why Canvas is faster than Plotly for very high FPS:
 *   - Zero JS library overhead per frame
 *   - Direct pixel writes via putImageData()  (single GPU upload per frame)
 *   - No DOM diffing, no SVG, no React-style reconciliation
 *
 * Achievable FPS: 40-60+ fps depending on grid size.
 *
 * Upgrade path → binary WebSocket:
 *   When you're ready, change broadcast.py to send raw Float32Array bytes,
 *   handle ws.onmessage with ArrayBuffer parsing in app.js, and pass the
 *   typed array directly to update() — no JSON.parse() cost at all.
 *
 * To activate: change one import line in app.js.
 */

import { BaseRenderer } from './base_renderer.js';

// ---------------------------------------------------------------------------
// Colormap  (Viridis approximation — 256 pre-computed RGB entries)
// ---------------------------------------------------------------------------
function buildViridisLUT() {
  // Key colour stops sampled from the real Viridis palette
  const stops = [
    [0.267, 0.004, 0.329],   //   0 – dark purple
    [0.283, 0.141, 0.458],   //  51
    [0.254, 0.265, 0.530],   // 102
    [0.163, 0.471, 0.558],   // 153
    [0.134, 0.659, 0.518],   // 179
    [0.478, 0.821, 0.318],   // 204
    [0.993, 0.906, 0.144],   // 255 – yellow
  ];

  const lut = new Uint8Array(256 * 3);
  const n = stops.length - 1;

  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    const seg = Math.min(Math.floor(t * n), n - 1);
    const lo = stops[seg];
    const hi = stops[seg + 1];
    const f = t * n - seg;

    lut[i * 3    ] = Math.round((lo[0] + (hi[0] - lo[0]) * f) * 255);
    lut[i * 3 + 1] = Math.round((lo[1] + (hi[1] - lo[1]) * f) * 255);
    lut[i * 3 + 2] = Math.round((lo[2] + (hi[2] - lo[2]) * f) * 255);
  }
  return lut;
}

const VIRIDIS = buildViridisLUT();

// ---------------------------------------------------------------------------
// CanvasRenderer
// ---------------------------------------------------------------------------
export class CanvasRenderer extends BaseRenderer {
  constructor() {
    super();
    this._canvas = null;
    this._ctx    = null;
    this._imgData = null;
    this._rows   = 0;
    this._cols   = 0;
  }

  init(container, config) {
    const { rows, cols } = config;
    this._rows = rows;
    this._cols = cols;

    this._canvas = document.createElement('canvas');
    this._canvas.width  = cols;
    this._canvas.height = rows;

    // CSS: stretch to fill the container while keeping pixel-perfect data
    Object.assign(this._canvas.style, {
      width:           '100%',
      height:          '100%',
      imageRendering:  'pixelated',   // no browser smoothing
      display:         'block',
    });

    container.appendChild(this._canvas);
    this._ctx     = this._canvas.getContext('2d');
    this._imgData = this._ctx.createImageData(cols, rows);
  }

  update(z, _meta) {
    if (!this._ctx) return;

    const rows   = this._rows;
    const cols   = this._cols;
    const pixels = this._imgData.data;

    // --- Find min/max for normalisation (single pass) ---
    let min = Infinity;
    let max = -Infinity;
    for (let r = 0; r < rows; r++) {
      const row = z[r];
      for (let c = 0; c < cols; c++) {
        const v = row[c];
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    const range = max - min || 1;

    // --- Map values → RGBA pixels ---
    for (let r = 0; r < rows; r++) {
      const row    = z[r];
      const yFlip  = rows - 1 - r;   // flip Y so low-doppler is at bottom
      const offset = yFlip * cols;

      for (let c = 0; c < cols; c++) {
        const idx  = (offset + c) * 4;
        const lut  = Math.round(((row[c] - min) / range) * 255) * 3;

        pixels[idx    ] = VIRIDIS[lut    ];
        pixels[idx + 1] = VIRIDIS[lut + 1];
        pixels[idx + 2] = VIRIDIS[lut + 2];
        pixels[idx + 3] = 255;
      }
    }

    // Single GPU upload per frame
    this._ctx.putImageData(this._imgData, 0, 0);
  }

  destroy() {
    if (this._canvas) {
      this._canvas.remove();
      this._canvas = null;
    }
    this._ctx     = null;
    this._imgData = null;
  }
}
