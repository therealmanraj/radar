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
        self._device     = None
        self._background = None   # EMA of raw ADC data for MTI clutter rejection

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
        Output shape: (num_chirps, range_bins) = (32, 32)
          axis 0 = Doppler / velocity   (row 16 = zero velocity after fftshift)
          axis 1 = range bins           (bin 0 = closest, bin 31 = ~3.2 m)

        Pipeline improvements vs. old/app.py:
          1. Average all 3 RX antennas  → +4.8 dB SNR vs. single antenna
          2. MTI clutter filter          → exponential moving average subtracted
             from the raw ADC data to reject static reflections (desk, walls)
             that would otherwise swamp the hand signal at 30 cm
          3. Hanning windows on both axes
          4. Range FFT (one-sided) + Doppler FFT (fftshift)
        """
        raw     = self._device.get_next_frame()   # blocks until board is ready
        rx_data = raw[0].astype(float)             # (num_rx, num_chirps, num_samples)

        # ── Step 1: average all RX antennas for +4.8 dB SNR ────────────────
        rx_avg = np.mean(rx_data, axis=0)          # (32, 64)

        # ── Step 2: MTI clutter filter ──────────────────────────────────────
        # The EMA tracks the slow-changing static environment.
        # Subtracting it highlights fast-changing targets (moving hand).
        # alpha=0.85 at 5 fps → time constant ≈ 1.3 s (adapts to slow drift,
        # ignores hand movement which changes every frame).
        if self._background is None:
            self._background = rx_avg.copy()
            return np.zeros((NUM_CHIRPS, NUM_SAMPLES // 2))  # skip first frame

        mti = rx_avg - self._background
        self._background = 0.85 * self._background + 0.15 * rx_avg

        # ── Step 3: Hanning windows ─────────────────────────────────────────
        win_range   = np.hanning(mti.shape[1])    # (64,)
        win_doppler = np.hanning(mti.shape[0])    # (32,)
        windowed    = mti * win_range[np.newaxis, :] * win_doppler[:, np.newaxis]

        # ── Step 4: Range FFT → one-sided ───────────────────────────────────
        range_fft = np.fft.fft(windowed, axis=1)[:, : mti.shape[1] // 2]

        # ── Step 5: Doppler FFT — fftshift puts zero-velocity at row 16 ─────
        rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)

        return np.abs(rd_map)   # (num_chirps=32, range_bins=32)  NO transpose

    def close(self) -> None:
        if self._device is not None:
            self._device._close()   # SDK uses _close(), not close()
            self._device = None
