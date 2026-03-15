"""
radar/sdk.py
------------
Infineon BGT60TR13C via the official ifxradarsdk.

Uses the board's default configuration — no custom FmcwSimpleSequenceConfig.
This matches the approach in the working sensor-radar/detect_hand.py and gives
frame shape (3, 64, 64) = (num_rx, num_chirps, num_samples).

Swap into use in server/app.py:
  from radar.sdk import InfineonRadar
  source = InfineonRadar()
"""

import numpy as np
from .base import RadarSource

# Physical axis constants (BGT60TR13C defaults)
_C          = 3e8
_BW         = 1.5e9                     # default sweep bandwidth  ~1.5 GHz
_FC         = 60.75e9
_LAMBDA     = _C / _FC
_CHIRP_DT   = 0.5e-3                    # chirp repetition time

RANGE_RES_M  = _C / (2 * _BW)          # ~0.10 m per range bin

# Default device frame dimensions (no custom config)
NUM_RX      = 3
NUM_CHIRPS  = 64                        # 64 chirps  per frame (board default)
NUM_SAMPLES = 64                        # 64 samples per chirp (board default)
NUM_RANGE   = NUM_SAMPLES // 2          # 32 one-sided range bins

V_MAX_MS    = _LAMBDA / (4 * _CHIRP_DT)           # ~2.47 m/s
V_MAX_KMH   = V_MAX_MS * 3.6                      # ~8.89 km/h
MAX_RANGE_CM = NUM_RANGE * RANGE_RES_M * 100      # 320 cm

# Extent for imshow: [v_min_kmh, v_max_kmh, range_min_cm, range_max_cm]
RD_EXTENT   = [-V_MAX_KMH, V_MAX_KMH, 0, MAX_RANGE_CM]

EMA_ALPHA   = 0.85   # background EMA — rejects static clutter (walls, desk)


class InfineonRadar(RadarSource):
    """
    Live data from the BGT60TR13C eval board.

    Uses board default config (no FmcwSimpleSequenceConfig).
    Returns a 2D range-doppler magnitude map shaped (64, 32):
      axis 0 = Doppler / velocity  (row 32 = zero velocity after fftshift)
      axis 1 = range bins          (bin 0 = closest, bin 31 = ~3.2 m)
    """

    def __init__(self, uuid: str | None = None):
        self._uuid       = uuid
        self._device     = None
        self._background = None   # per-antenna EMA: shape (num_rx, num_chirps, num_samples)

    def open(self) -> None:
        from ifxradarsdk.fmcw import DeviceFmcw

        self._device = DeviceFmcw(uuid=self._uuid) if self._uuid else DeviceFmcw()

        # Drain stale frames from hardware FIFO (same as detect_hand.py drain_buffer)
        for _ in range(10):
            try:
                self._device.get_next_frame()
            except Exception:
                pass

        self._background = None   # reset background on each open

    def get_frame(self) -> np.ndarray:
        """
        Read one frame and return a Range-Doppler magnitude map.
        Output shape: (num_chirps, num_range) = (64, 32)

        Pipeline:
          1. Per-antenna EMA background subtraction (MTI clutter filter)
          2. Hanning windows on both range and Doppler axes
          3. Range FFT — one-sided (axis 1)
          4. Doppler FFT — fftshift puts zero-velocity at row num_chirps//2 = 32
          5. Average magnitude across all 3 RX antennas  (+4.8 dB SNR)
        """
        raw     = self._device.get_next_frame()   # blocks until board is ready
        rx_data = raw[0].astype(float)             # (num_rx, num_chirps, num_samples)

        num_rx, num_chirps, num_samples = rx_data.shape

        # ── Step 1: per-antenna MTI clutter filter ───────────────────────────
        # First frame seeds the background — return zeros so the caller skips it.
        if self._background is None:
            self._background = rx_data.copy()
            return np.zeros((num_chirps, num_samples // 2))

        mti = rx_data - self._background
        self._background = EMA_ALPHA * self._background + (1 - EMA_ALPHA) * rx_data

        # ── Step 2: Hanning windows ──────────────────────────────────────────
        win_range   = np.hanning(num_samples)   # (num_samples,)
        win_doppler = np.hanning(num_chirps)    # (num_chirps,)

        # ── Steps 3–4: FFT per antenna ───────────────────────────────────────
        maps = []
        for rx in range(num_rx):
            chirp_data = mti[rx]   # (num_chirps, num_samples)
            windowed   = chirp_data * win_range[np.newaxis, :] * win_doppler[:, np.newaxis]
            range_fft  = np.fft.fft(windowed, axis=1)[:, :num_samples // 2]
            rd         = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)
            maps.append(np.abs(rd))

        # ── Step 5: average across antennas ─────────────────────────────────
        return np.mean(maps, axis=0)   # (num_chirps, num_samples//2) = (64, 32)

    def close(self) -> None:
        if self._device is not None:
            self._device._close()   # SDK uses _close(), not close()
            self._device = None
