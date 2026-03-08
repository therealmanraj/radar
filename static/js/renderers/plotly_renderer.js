/**
 * plotly_renderer.js
 * ------------------
 * Heatmap renderer using Plotly.js.
 *
 * Performance notes:
 *   - init()   calls Plotly.newPlot() once to build the full chart
 *   - update() calls Plotly.restyle()  — updates ONLY the z data matrix.
 *              No axes, colorbar, or layout are re-rendered.
 *   - zsmooth: 'fast' uses ImageData pixel arrays (not SVG) → much faster
 *              for large grids.
 *
 * Upgrade path → CanvasRenderer:
 *   Change one import line in app.js.  No other code changes needed.
 */

import { BaseRenderer } from './base_renderer.js';

export class PlotlyRenderer extends BaseRenderer {
  constructor() {
    super();
    this._el = null;
    this._ready = false;
    this._config = null;
  }

  init(container, config) {
    this._el = container;
    this._config = config;

    const { rows, cols, colorscale = 'Viridis', logScale } = config;

    // Blank initial data so the chart renders immediately
    const zBlank = Array.from({ length: rows }, () => new Array(cols).fill(-120));

    const data = [
      {
        type: 'heatmap',
        z: zBlank,
        zsmooth: 'fast',          // ImageData path — avoids SVG per-cell
        colorscale: colorscale,
        colorbar: {
          title: { text: logScale ? 'Power (dB)' : 'Power (linear)', side: 'right' },
          thickness: 14,
          tickfont: { color: '#ccc', size: 11 },
          titlefont: { color: '#ccc', size: 12 },
        },
      },
    ];

    const layout = {
      margin: { t: 40, b: 50, l: 70, r: 20 },
      paper_bgcolor: '#0d0d1a',
      plot_bgcolor: '#0d0d1a',
      font: { color: '#ddd', family: 'monospace' },
      title: {
        text: 'Range-Doppler Map',
        font: { color: '#00e5ff', size: 16 },
      },
      xaxis: {
        title: { text: 'Range bin →', font: { color: '#aaa' } },
        gridcolor: '#222',
        zerolinecolor: '#333',
      },
      yaxis: {
        title: { text: '← Closing | Doppler | Opening →', font: { color: '#aaa' } },
        gridcolor: '#222',
        zerolinecolor: '#333',
      },
    };

    const plotConfig = {
      responsive: true,
      displayModeBar: false,   // no toolbar — keeps UI clean
    };

    Plotly.newPlot(this._el, data, layout, plotConfig);
    this._ready = true;
  }

  update(z, _meta) {
    if (!this._ready) return;
    // restyle touches ONLY trace[0].z — nothing else re-renders
    Plotly.restyle(this._el, { z: [z] }, [0]);
  }

  destroy() {
    if (this._el) Plotly.purge(this._el);
    this._ready = false;
  }
}
