/**
 * base_renderer.js
 * ----------------
 * Renderer interface.  Both PlotlyRenderer and CanvasRenderer implement
 * these three methods — that is the ONLY contract app.js cares about.
 *
 * To add a new renderer (e.g. WebGL):
 *   1. Extend BaseRenderer
 *   2. Implement init(), update(), destroy()
 *   3. Change one import line in app.js
 */

export class BaseRenderer {
  /**
   * Called once when the first frame arrives and dimensions are known.
   * @param {HTMLElement} container  - DOM element to render into
   * @param {Object}      config     - { rows, cols, colorscale, logScale }
   */
  // eslint-disable-next-line no-unused-vars
  init(container, config) {
    throw new Error(`${this.constructor.name}.init() not implemented`);
  }

  /**
   * Called on every incoming frame.
   * @param {number[][]} z     - 2D array [rows][cols] of float values
   * @param {Object}     meta  - { frame, peak, peak_range_bin, log_scale, … }
   */
  // eslint-disable-next-line no-unused-vars
  update(z, meta) {
    throw new Error(`${this.constructor.name}.update() not implemented`);
  }

  /**
   * Clean up DOM elements / event listeners when the renderer is replaced.
   */
  destroy() {}
}
