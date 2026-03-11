/**
 * plotly_renderer.js
 * ------------------
 * Range-Doppler heatmap using Plotly.js.
 *
 * Axes:
 *   X = Doppler frequency (Hz)   — ±PRF/2, fftshifted, zero at centre
 *   Y = Range (m)                — 0 to MAX_RANGE_M
 *   Z = Power (dB)               — colorscale Viridis
 *
 * Server sends z shaped (numDoppler=64, numRange=32).
 * We transpose to (numRange, numRange) so x=Doppler cols, y=Range rows.
 *
 * Performance:
 *   init()   → Plotly.newPlot()  once
 *   update() → Plotly.restyle()  data-only, no axes/layout re-render
 *   zsmooth:'fast' uses ImageData pixels, not SVG — much faster
 */

import { BaseRenderer } from './base_renderer.js';

// Must match radar/sdk.py constants
const CHIRP_DT_S      = 0.5e-3;   // chirp repetition time (default device config)
const RANGE_M_PER_BIN = 0.10;     // ~0.10 m per range bin

export class PlotlyRenderer extends BaseRenderer {
  constructor() {
    super();
    this._el    = null;
    this._ready = false;
  }

  /**
   * @param {HTMLElement} container
   * @param {{ numDoppler: number, numRange: number, logScale: boolean }} config
   */
  init(container, config) {
    this._el = container;
    const { numDoppler = 64, numRange = 32, logScale = true } = config;

    // Doppler frequency axis (Hz) — fftshifted: bin 0 → most negative freq
    const PRF = 1 / CHIRP_DT_S;                      // 2000 Hz
    const dopplerHz = Array.from({ length: numDoppler }, (_, i) =>
      +((i - numDoppler / 2) * (PRF / numDoppler)).toFixed(2)
    );

    // Range axis (m) — bin 0 = closest
    const rangeM = Array.from({ length: numRange }, (_, i) =>
      +(i * RANGE_M_PER_BIN).toFixed(2)
    );

    // Blank z shaped (numRange, numDoppler) — rows=y=Range, cols=x=Doppler
    const zBlank = Array.from({ length: numRange }, () =>
      new Array(numDoppler).fill(-120)
    );

    const data = [{
      type:       'heatmap',
      z:          zBlank,
      x:          dopplerHz,
      y:          rangeM,
      zsmooth:    'fast',
      colorscale: 'Viridis',
      zauto:      false,
      zmin:       -60,
      zmax:       0,
      colorbar: {
        title:     { text: logScale ? 'dB' : 'Linear', side: 'right' },
        thickness: 12,
        tickfont:  { color: '#bbb', size: 10 },
        titlefont: { color: '#bbb', size: 11 },
      },
    }];

    const layout = {
      margin:        { t: 36, b: 56, l: 64, r: 72 },
      paper_bgcolor: '#0d0d1a',
      plot_bgcolor:  '#0d0d1a',
      font:          { color: '#ccc', family: 'monospace', size: 11 },
      title: {
        text: 'Range-Doppler Map',
        font: { color: '#00e5ff', size: 13 },
        pad:  { t: 4 },
      },
      xaxis: {
        title:         { text: 'Doppler Frequency (Hz)', font: { color: '#999', size: 11 } },
        gridcolor:     '#1c1c2e',
        zerolinecolor: '#445',
        zerolinewidth: 2,
        tickfont:      { size: 10 },
      },
      yaxis: {
        title:         { text: 'Range (m)', font: { color: '#999', size: 11 } },
        gridcolor:     '#1c1c2e',
        zerolinecolor: '#333',
        tickfont:      { size: 10 },
      },
      // Vertical line at x=0 Hz marks zero velocity
      shapes: [{
        type:      'line',
        x0: 0, x1: 0,
        y0: rangeM[0], y1: rangeM[rangeM.length - 1],
        line: { color: 'rgba(255,255,255,0.25)', width: 1.5, dash: 'dot' },
      }],
    };

    Plotly.newPlot(this._el, data, layout, {
      responsive:     true,
      displayModeBar: false,
    });
    this._ready = true;
  }

  /**
   * @param {number[][]} z  shape (numDoppler, numRange) from server
   */
  update(z) {
    if (!this._ready) return;
    // Transpose: server sends (numDoppler=rows, numRange=cols)
    // Plotly needs (numRange=rows, numDoppler=cols) for x=Doppler, y=Range
    const zT = z[0].map((_, col) => z.map(row => row[col]));
    Plotly.restyle(this._el, { z: [zT] }, [0]);
  }

  destroy() {
    if (this._el) Plotly.purge(this._el);
    this._ready = false;
  }
}
