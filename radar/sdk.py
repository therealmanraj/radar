"""
radar/sdk.py
------------
Infineon BGT60TR13C via the official ifxradarsdk.

Install the SDK:
  pip install ifxradarsdk
  (or download from Infineon's Radar Development Kit page)

Swap into use in server/app.py:
  from radar.sdk import InfineonRadar
  source = InfineonRadar(num_range=64, num_doppler=32)
"""

import numpy as np
from .base import RadarSource


class InfineonRadar(RadarSource):
    """
    Live data from the BGT60TR13C eval board.
    get_frame() is blocking — runs inside the radar reader thread.
    """

    def __init__(self, num_range: int = 64, num_doppler: int = 32):
        self.num_range = num_range
        self.num_doppler = num_doppler
        self._device = None

    def open(self) -> None:
        from ifxradarsdk.fmcw import DeviceFmcw
        from ifxradarsdk.fmcw.types import FmcwSimpleSequenceConfig, FmcwSequenceChirp

        self._device = DeviceFmcw()

        config = FmcwSimpleSequenceConfig(
            frame_repetition_time_s=1 / 20,       # target 20 fps
            chirp_repetition_time_s=0.001,
            num_chirps=self.num_doppler,
            tdm_mimo=False,
            chirp=FmcwSequenceChirp(
                start_frequency_Hz=60e9,
                end_frequency_Hz=61e9,
                sample_rate_Hz=1_000_000,
                num_samples=self.num_range * 2,   # extra samples for range FFT
                rx_mask=1,
                tx_mask=1,
                tx_power_level=31,
                lp_cutoff_Hz=500_000,
                hp_cutoff_Hz=80_000,
                if_gain_dB=33,
            ),
        )
        self._device.set_acquisition_sequence(
            self._device.create_simple_sequence(config)
        )

    def get_frame(self) -> np.ndarray:
        raw = self._device.get_next_frame()   # blocks until frame is ready
        rx0 = raw[0]                          # shape: (num_chirps, num_samples)

        # --- Range FFT (across fast-time / samples axis) ---
        range_fft = np.fft.fft(rx0, axis=1)[:, : self.num_range]

        # --- Doppler FFT (across slow-time / chirps axis) ---
        rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)

        return np.abs(rd_map)   # magnitude → (num_doppler, num_range)

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None
