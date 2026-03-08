"""
radar/sdk.py
------------
Infineon BGT60TR13C via the official ifxradarsdk.

Config is derived from the working old/avian_test.py and old/app.py:
  - num_samples = 64  (NOT num_range * 2 — that overflows the USB buffer)
  - num_chirps  = 32
  - rx_mask     = 7   (all 3 RX antennas on the eval board)
  - fps         = 5   (safe; >10 fps risks IFX_ERROR_FRAME_ACQUISITION_FAILED)
  - Hanning windows on both range and Doppler axes (reduces sidelobes)

Swap into use in server/app.py:
  from radar.sdk import InfineonRadar
  source = InfineonRadar()
"""

import numpy as np
from .base import RadarSource

# Fixed hardware constants — do NOT change without testing on the board
NUM_CHIRPS   = 32
NUM_SAMPLES  = 64
RADAR_FPS    = 5          # safe max; UI can render faster but SDK runs at 5 Hz

# Physical axis constants (matches old/app.py)
_C           = 3e8
_BW          = 1.5e9                                   # 61.5 GHz - 60 GHz
_FC          = 60.75e9
_LAMBDA      = _C / _FC
_CHIRP_DT    = 0.5e-3                                  # chirp repetition time

RANGE_RES_M  = _C / (2 * _BW)                         # ~0.10 m per bin
V_MAX_MS     = _LAMBDA / (4 * _CHIRP_DT)              # ~2.47 m/s
V_MAX_KMH    = V_MAX_MS * 3.6                          # ~8.89 km/h
MAX_RANGE_CM = (NUM_SAMPLES // 2) * RANGE_RES_M * 100 # 320 cm

# Extent for imshow: [v_min_kmh, v_max_kmh, range_min_cm, range_max_cm]
RD_EXTENT    = [-V_MAX_KMH, V_MAX_KMH, 0, MAX_RANGE_CM]


class InfineonRadar(RadarSource):
    """
    Live data from the BGT60TR13C eval board.
    get_frame() is blocking — always called from inside the radar reader thread.
    Returns a 2D array shaped (range_bins, vel_bins) = (32, 32) in dBFS-ready linear.
    """

    def __init__(self):
        self._device = None

    def open(self) -> None:
        from ifxradarsdk.fmcw import DeviceFmcw
        from ifxradarsdk.fmcw.types import FmcwSimpleSequenceConfig, FmcwSequenceChirp

        self._device = DeviceFmcw()

        config = FmcwSimpleSequenceConfig(
            frame_repetition_time_s = 1.0 / RADAR_FPS,   # 0.2 s — safe for USB
            chirp_repetition_time_s = _CHIRP_DT,
            num_chirps              = NUM_CHIRPS,
            tdm_mimo                = False,
            chirp=FmcwSequenceChirp(
                start_frequency_Hz = 60e9,
                end_frequency_Hz   = 61.5e9,
                sample_rate_Hz     = 1_000_000,
                num_samples        = NUM_SAMPLES,
                rx_mask            = 7,    # all 3 RX antennas
                tx_mask            = 1,
                tx_power_level     = 31,
                lp_cutoff_Hz       = 500_000,
                hp_cutoff_Hz       = 80_000,
                if_gain_dB         = 33,
            ),
        )
        sequence = self._device.create_simple_sequence(config)
        self._device.set_acquisition_sequence(sequence)

    def get_frame(self) -> np.ndarray:
        """
        Read one frame and return a Range-Doppler magnitude map.
        Shape: (range_bins, vel_bins) = (NUM_SAMPLES//2, NUM_CHIRPS) = (32, 32)

        Processing pipeline matches old/app.py compute_rd_map():
          1. Take RX0 from the first acquisition  shape: (num_chirps, num_samples)
          2. Apply Hanning window on both axes
          3. Range FFT → one-sided
          4. Doppler FFT → fftshift (zero-velocity centred)
          5. Transpose → (range_bins, vel_bins)
        """
        raw     = self._device.get_next_frame()   # blocks until board is ready
        rx_data = raw[0]                           # (num_rx, num_chirps, num_samples)
        rx0     = rx_data[0].astype(float)         # (32, 64) — use RX0 only

        # Hanning windows — same as old/app.py
        win_range   = np.hanning(rx0.shape[1])                  # (64,)
        win_doppler = np.hanning(rx0.shape[0])                  # (32,)
        windowed    = rx0 * win_range[np.newaxis, :] * win_doppler[:, np.newaxis]

        # Range FFT — one-sided (positive ranges only)
        range_fft = np.fft.fft(windowed, axis=1)[:, : rx0.shape[1] // 2]

        # Doppler FFT — fftshift centres zero-velocity
        rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)

        # Transpose: (num_chirps, range_bins) → (range_bins, vel_bins)
        return np.abs(rd_map).T   # (32, 32)

    def close(self) -> None:
        if self._device is not None:
            self._device._close()   # SDK uses _close(), not close()
            self._device = None
